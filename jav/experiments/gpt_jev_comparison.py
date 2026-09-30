"""New paired measurement: a text port of the legacy GPT prompt and the same extract with JEV.

Not a rerun of the legacy full sidecar/vision process. The real, existing Burr G graph, stopping after GPT and
resuming from the saved state; the closed measurements are only inputs.
"""
from __future__ import annotations

import argparse
import json
import time
from contextlib import nullcontext
from pathlib import Path

from jav import store, policy
from jav.config import PROJECT_ROOT, OLD_PROJECT_ROOT, load_prompt
from jav.experiments.long_document_trial import read, write, sha, TrialBudget
from jav.experiments.stack_trial import DirectAdapter, run_trial
from jav.experiments.run_stack_trial import score_result
from jav.learning_runtime import code_hash, canonical_hash
from jav.models import record_from_llm
from jav.typepack import get as get_pack

ROOT = PROJECT_ROOT/'runs/20260922_gpt_jev_invoices'
OLD = PROJECT_ROOT/'runs/20260921_stack_trial/measurement_122920'
LIMITS = {'openai': (24, 1.0), 'jev': (48, .25)}


def without_jev(state):
    """The same GPT data and code checks; a separate baseline arm without the JEV verdict."""
    from jav.validators import run_all
    baseline = state.model_copy(deep=True)
    pack = get_pack(state.doc_type)
    baseline.invoice, reasons = record_from_llm(state.llm_output or {}, pack.fields)
    baseline.verdicts = None
    policy.require_review(baseline, *reasons)
    for field in pack.required:
        if baseline.invoice.get_field(field) is None:
            policy.require_review(baseline, 'llm:required_missing:'+field)
    baseline.validation = run_all(baseline.invoice, pack.validators)
    policy.apply_validation_policy(baseline)
    baseline.route = 'human' if baseline.needs_review else 'auto'
    return baseline


def prepare(root):
    if root.exists():
        raise ValueError('comparison already prepared')
    auth = PROJECT_ROOT/'runs/20260922_stack_comparison/authorization.json'
    assert read(auth)['provider_limits_usd'] == {'openai':5, 'jev':5}
    labels = read(OLD/'frozen_labels.json')
    sample = read(PROJECT_ROOT/'runs/20260921_stack_trial/sample.json')
    cases = []
    for case in sample['cases']:
        label = labels['cases'][case['case_id']]
        if not label.get('invoice'):
            continue
        assert case['text_source'] == 'pdf' and case['text_chars'] <= 16000
        assert sha(Path(case['path'])) == case['sha256']
        cases.append({'source':case, 'label':label})
    assert len(cases) == 6
    protected = {p.relative_to(PROJECT_ROOT).as_posix():sha(p) for p in OLD.rglob('*') if p.is_file()}
    parity = {}
    for key in {'invoice_hu','invoice_foreign'}:
        pack = get_pack(key)
        parity[key] = {}
        for local, old in [(pack.prompt_file,'prompt.md'),(pack.schema_file,'schema.json')]:
            a = PROJECT_ROOT/'jav/prompts'/local
            b = OLD_PROJECT_ROOT/'flows/doc-extract-bare/types'/key/old
            parity[key][old] = {'local_sha256':sha(a), 'legacy_sha256':sha(b),
                'text_equal':a.read_text(encoding='utf-8') == b.read_text(encoding='utf-8')}
    write(root/'cases.json', cases)
    write(root/'protected.json', protected)
    write(root/'plan.json', {'version':1,'repeats':2,'limits':LIMITS,
        'openai_model':'gpt-5.4-mini','jev_model':'jev-1.13.0',
        'model_settings':{'openai_reasoning_effort':'none','temperature':0,'max_tokens':5000},
        'authorization_sha256':sha(auth),'cases_sha256':sha(root/'cases.json'),
        'protected_sha256':sha(root/'protected.json'),'code_sha256':code_hash(),
        'config_sha256':canonical_hash({p.relative_to(PROJECT_ROOT).as_posix():sha(p) for p in (PROJECT_ROOT/'configs').rglob('*.json')}),
        'legacy_parity':parity,'legacy_scope':'verbatim prompt/schema port, text-only, common validators; no legacy vision/detection/ML/routing equivalence',
        'sample_authority':'reused assistant-labelled diagnostic sample, not independent human gold',
        'comparison':'same generated output before and after JEV; no JEV correction; no old S-arm remeasurement'})
    print('Prepared six paired invoices, two fresh GPT outputs each; old evidence protected.')


def validate(root):
    plan = read(root/'plan.json')
    assert sha(root/'cases.json') == plan['cases_sha256']
    assert sha(root/'protected.json') == plan['protected_sha256']
    assert code_hash() == plan['code_sha256'], 'source changed; use frozen source or a new trial'
    assert canonical_hash({p.relative_to(PROJECT_ROOT).as_posix():sha(p) for p in (PROJECT_ROOT/'configs').rglob('*.json')}) == plan['config_sha256']
    assert sha(PROJECT_ROOT/'runs/20260922_stack_comparison/authorization.json') == plan['authorization_sha256']
    for name, digest in read(root/'protected.json').items():
        assert sha(PROJECT_ROOT/name) == digest, name
    for item in read(root/'cases.json'):
        assert sha(Path(item['source']['path'])) == item['source']['sha256']
    return plan, read(root/'cases.json')


def run(root):
    from openai import AsyncOpenAI
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.models.wrapper import WrapperModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from typesafe_sdk import RetryPolicy
    from jav.config import get_openai_key, make_client
    from jav.adapters.jev import JevAdapter
    plan,cases = validate(root)
    budget = TrialBudget(root, LIMITS)
    class BoundedModel(WrapperModel):
        async def request(self,*args,**kwargs):
            budget.reserve('openai')
            return await super().request(*args,**kwargs)
    class BoundedJev(JevAdapter):
        def _live(self,*args,**kwargs):
            budget.reserve('jev')
            return super()._live(*args,**kwargs)
    model = BoundedModel(OpenAIChatModel(plan['openai_model'],provider=OpenAIProvider(
        openai_client=AsyncOpenAI(api_key=get_openai_key(),max_retries=0,timeout=90))))
    base = BoundedJev(client=make_client(retry=RetryPolicy(max_retries=0)),model=plan['jev_model'],cache_dir=root/'cache')
    for repeat in range(plan['repeats']):
        for item in cases:
            cid = item['source']['case_id']
            rid = f'{cid}-gpt-jev-{repeat}'
            dest = root/'results'/f'{rid}.json'
            if dest.exists():
                continue
            adapter = DirectAdapter(base, force_live=True)
            class RecordedAgent:
                def __init__(self,pack):
                    self.agent = Agent(model,output_type=pack.llm_model(),instructions=load_prompt(pack.prompt_file),
                                       retries=0,model_settings=plan['model_settings'])
                def run_sync(self,prompt):
                    if store.load_artifact('comparison_started',rid) is not None:
                        raise RuntimeError('unresolved GPT action; no automatic external retry')
                    store.save_artifact('comparison_started',rid,{'prompt_sha256':canonical_hash(prompt),'plan_sha256':sha(root/'plan.json')})
                    started=time.perf_counter()
                    try:
                        result=self.agent.run_sync(prompt)
                    except Exception as exc:
                        store.ledger_add(run_id=rid,step='extract_llm',provider='openai',model=plan['openai_model'],
                            input_tokens=None,output_tokens=None,cost_usd=None,seconds=time.perf_counter()-started,
                            config_hash=sha(root/'plan.json'),error=type(exc).__name__)
                        raise
                    store.save_artifact('comparison_gpt_response',rid,{'output':result.output.model_dump(mode='json'),
                        'actual_model':result.response.model_name,'messages':json.loads(result.all_messages_json())})
                    return result
            args=dict(flow='invoice',source_path=item['source']['path'],directory=root/rid,run_id=rid,
                      adapter=adapter,doc_type=item['label']['doc_type'],arm='G',agent_factory=RecordedAgent,
                      generator_identity=sha(root/'plan.json'))
            with base.no_cache_write():
                before=run_trial(**args,halt_after=['extract_llm'])
                if before.llm_output is None:
                    raise RuntimeError('GPT extraction failed; inspect saved error, no retry')
                baseline=without_jev(before)
                write(root/'baseline'/f'{rid}.json',baseline.model_dump(mode='json'))
                after=run_trial(**args)
                if after.verdicts is None:
                    raise RuntimeError('JEV verification failed; no complete paired result')
            with store.use_store(root/rid/'business.sqlite'):
                ledger=store.ledger_for_run(rid)
                response=store.load_artifact('comparison_gpt_response',rid)
            row={'case_id':cid,'repeat':repeat,'original_split':item['label']['split'],
                 'baseline':score_result('invoice',baseline,item['label']),
                 'combined':score_result('invoice',after,item['label']),
                 'verdicts':after.verdicts.model_dump(mode='json'),
                 'actual_openai_model':response['actual_model'],'ledger':ledger,
                 'same_extraction':before.llm_output == after.llm_output}
            write(dest,row)
            write(root/'states'/f'{rid}.json',after.model_dump(mode='json'))
            write(root/'requests'/f'{rid}.json',adapter.audit)
            print(json.dumps({'case':cid,'repeat':repeat,'baseline_fields':sum(row['baseline']['field_checks'].values()),
                'fields':len(row['baseline']['field_checks']),'baseline_auto':row['baseline']['automatic'],
                'combined_auto':row['combined']['automatic'],'complete':row['combined']['complete_document_correct'],
                'budget':budget.usage()}),flush=True)


def replay(root):
    plan,cases=validate(root)
    class NoAdapter:
        model=plan['jev_model']
        def ask(self,*a,**kw): raise AssertionError('external JEV call')
    def no_agent(pack): raise AssertionError('external GPT call')
    exact=[]
    for repeat in range(plan['repeats']):
        for item in cases:
            rid=f"{item['source']['case_id']}-gpt-jev-{repeat}"
            adapter=DirectAdapter(NoAdapter())
            result=run_trial('invoice',item['source']['path'],root/rid,rid,adapter,
                doc_type=item['label']['doc_type'],arm='G',agent_factory=no_agent,generator_identity=sha(root/'plan.json'))
            assert result.model_dump(mode='json') == read(root/'states'/f'{rid}.json')
            exact.append(rid)
    write(root/'replay.json',{'exact':exact,'external_calls':0,'real_burr_sqlite':True})
    print('Exact Burr terminal replay:',len(exact),'External calls: 0')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','run','replay'])
    p.add_argument('--root',type=Path,default=ROOT)
    a=p.parse_args()
    {'prepare':prepare,'run':run,'replay':replay}[a.command](a.root)


if __name__=='__main__': main()
