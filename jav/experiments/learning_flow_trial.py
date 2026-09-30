"""Self-authored synthetic running text → Pydantic AI → JEV → durable Burr; 4+12 call limit."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import shutil
import time

from jav import store
from jav.adapters.jev import JevAdapter
from jav.config import PROJECT_ROOT, OPENAI_MODEL
from jav.document_learning import ProposalBatch, digest, load_config, propose_labels
from jav.experiments.real_grounded_trial import read, write, code_hashes, reserve_call
from jav.learning_runtime import run_learning

OUT=PROJECT_ROOT/'runs/20260921_learning_flow_v3'
FIRST=PROJECT_ROOT/'runs/20260921_learning_flow_v2'
PREVIOUS=PROJECT_ROOT/'runs/20260921_grounded_revision'
LABEL_TRIAL=PROJECT_ROOT/'runs/20260921_document_learning'


def prepare():
    if (OUT/'manifest.json').exists():
        raise RuntimeError('prepared evidence already exists')
    OUT.mkdir(parents=True,exist_ok=True)
    cases=[{'id':'en-prose','text':'The bearing temperature reached 68 Celsius. The coolant pressure measured 4.2 bar.',
            'gold':[{'raw_value':'68','unit':'Celsius','quote':'The bearing temperature reached 68 Celsius.'},
                    {'raw_value':'4.2','unit':'bar','quote':'The coolant pressure measured 4.2 bar.'}]},
           {'id':'hu-prose','text':'A csapágy hőmérséklete 72 Celsius volt. A hűtőfolyadék nyomása 5,1 bar volt.',
            'gold':[{'raw_value':'72','unit':'Celsius','quote':'A csapágy hőmérséklete 72 Celsius volt.'},
                    {'raw_value':'5,1','unit':'bar','quote':'A hűtőfolyadék nyomása 5,1 bar volt.'}]}]
    config=load_config()|{'max_points':2,'proposal_request_limit':1,
        'proposal_model_settings':{'openai_reasoning_effort':'none','temperature':0.0,'max_tokens':1500}}
    config['proposal_instructions']=config['proposal_instructions'].replace('at most 24 points','at most 2 points')
    write(OUT/'inputs.json',cases)
    manifest={'scope':'self-authored synthetic text only; no personal documents; two languages, two uncached repeats',
        'generator':OPENAI_MODEL,'jev_model':'jev-1.13.0','config':config,'hashes':code_hashes(),
        'inputs_sha256':digest((OUT/'inputs.json').read_text(encoding='utf-8')),
        'maximum_generation_calls':3,'maximum_jev_calls':9,'generation_recorded_stop_usd':.10,
        'jev_round_recorded_stop_usd':1,'round_prior_calls':189,'round_prior_usd':.020986,
        'continuation':'en-prose-0 completed in v2; unknown snapshot price caused stop, no output discarded',
        'first_generator_cost_estimate_usd':.000764,'first_generator_pricing':'431 input * .75/M + 98 output * 4.5/M; rounded',
        'schedule':[['hu-prose',0],['en-prose',1],['hu-prose',1]]}
    write(OUT/'manifest.json',manifest)
    for relative in manifest['hashes']:
        dest=OUT/'source_snapshot'/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(PROJECT_ROOT/relative,dest)
    print('prepared continuation: 3 generation calls, at most 9 JEV calls')


def cost_at(path, provider):
    with store.connect(path) as db:
        rows=db.execute('SELECT cost_usd,error FROM ledger WHERE provider=? AND cached=0',(provider,)).fetchall()
    if any(r['cost_usd'] is None or r['error'] for r in rows):
        raise RuntimeError('unknown cost or previous provider error; automatic spending stopped')
    return sum(r['cost_usd'] for r in rows)


class TrialAdapter(JevAdapter):
    def _live(self,*args,**kwargs):
        total=sum(cost_at(p,'jev') for p in [PREVIOUS/'business.sqlite',LABEL_TRIAL/'business.sqlite',FIRST/'business.sqlite',OUT/'business.sqlite'])
        if total>=1:
            raise RuntimeError('round recorded cost stop reached')
        reserve_call(OUT/'jev_budget.sqlite',already_used=0,maximum=9)
        reserve_call(PREVIOUS/'budget.sqlite',already_used=0,maximum=200)
        return super()._live(*args,**kwargs)


def live():
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from jav.config import get_openai_key
    manifest=read(OUT/'manifest.json')
    if manifest['hashes']!=code_hashes() or manifest['inputs_sha256']!=digest((OUT/'inputs.json').read_text(encoding='utf-8')):
        raise RuntimeError('frozen trial identity changed')
    with (OUT/'live.started').open('x') as f:
        f.write('exclusive synthetic trial')
    model=OpenAIChatModel(manifest['generator'],provider=OpenAIProvider(
        openai_client=AsyncOpenAI(api_key=get_openai_key(),max_retries=0,timeout=60)))
    adapter=TrialAdapter(model=manifest['jev_model'],cache_dir=OUT/'cache')
    config=manifest['config']
    rows=[]
    for repeat in range(2):
        for case in read(OUT/'inputs.json'):
            if [case['id'],repeat] not in manifest['schedule']:
                continue
            if cost_at(OUT/'business.sqlite','openai')+manifest['first_generator_cost_estimate_usd']>=manifest['generation_recorded_stop_usd']:
                raise RuntimeError('generation recorded cost stop reached')
            reserve_call(OUT/'generation_budget.sqlite',already_used=0,maximum=3)
            run_id=f"{case['id']}-{repeat}"
            kwargs=dict(text=case['text'],directory=OUT,run_id=run_id,adapter=adapter,model=model,config=config)
            started=time.perf_counter()
            # A real Burr pause after generation, then the continuation of the same run.
            paused=run_learning(**kwargs,halt_after=['generate'])
            final=run_learning(**kwargs)
            elapsed=time.perf_counter()-started
            with store.connect(OUT/'business.sqlite') as db:
                before=db.execute('SELECT count(*) FROM ledger').fetchone()[0]
            restored=run_learning(**kwargs)
            with store.connect(OUT/'business.sqlite') as db:
                after=db.execute('SELECT count(*) FROM ledger').fetchone()[0]
            assert final==restored and before==after
            # One deliberately corrupted value: the quote and the role are unchanged.
            batch=ProposalBatch.model_validate(paused['proposals'])
            control_result=None
            if batch.points:
                control=batch.model_copy(update={'points':[batch.points[0].model_copy(update={'raw_value':'9999'})]})
                control_result=run_learning(text=case['text'],directory=OUT,run_id=run_id+'-control',
                    adapter=adapter,config=config,proposals=control)['result']
            row={'run_id':run_id,'case_id':case['id'],'repeat':repeat,'seconds':elapsed,'result':final['result'],
                 'control_result':control_result,'terminal_resume_exact':True,'terminal_resume_new_calls':after-before,
                 'label_baseline_points':len(propose_labels(case['text'],config).points)}
            rows.append(row)
            write(OUT/(run_id+'.json'),row)
            print(run_id,Counter(p['verification']['status'] for p in final['result']['points']),flush=True)
    write(OUT/'results.json',rows)
    with store.connect(OUT/'business.sqlite') as db:
        ledger=[dict(r) for r in db.execute('SELECT * FROM ledger ORDER BY id')]
    write(OUT/'ledger.json',ledger)
    print('calls',len(ledger),'cost',round(sum(r['cost_usd'] or 0 for r in ledger),6))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','live'])
    args=parser.parse_args()
    prepare() if args.mode=='prepare' else live()
