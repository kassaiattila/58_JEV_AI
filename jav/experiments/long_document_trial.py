"""030: elkülönített, engedélyhez kötött hosszúdokumentum-próba; nincs OCR."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from jav import store
from jav.config import PROJECT_ROOT
from jav.document_learning import digest, load_config, ProposalBatch, PointProposal
from jav.document_chunks import ChunkPolicy, load_chunk_config, plan_document
from jav.models import LineLayout
from jav.learning_runtime import run_chunked_learning, run_learning
from jav.adapters.jev import JevAdapter

OUT = PROJECT_ROOT/'runs/20260921_long_document_trial'
OLD = PROJECT_ROOT/'runs/20260921_expanded_learning'
LONG = PROJECT_ROOT/'runs/20260921_long_documents'
IDS = ['expanded-048', 'expanded-049', 'expanded-059', 'expanded-043', 'expanded-005']


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TrialBudget:
    """Egy munkás, minden fizikai hívás előtt foglal; bizonytalan hívást nem ismétel."""
    def __init__(self, root, limits=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.limits = limits or {'openai': (120, 6), 'jev': (1200, 2)}
        self.path = self.root/'attempts.sqlite'
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, provider TEXT NOT NULL)')
            db.commit()

    def usage(self):
        rows = {p: {'reserved': 0, 'logged': 0, 'usd': 0., 'errors': 0} for p in self.limits}
        with closing(sqlite3.connect(self.path)) as db:
            for provider, count in db.execute('SELECT provider,count(*) FROM attempts GROUP BY provider'):
                rows[provider]['reserved'] = count
        for path in self.root.rglob('business.sqlite'):
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
                for row_id, p, cost, error in db.execute('SELECT id,provider,cost_usd,error FROM ledger WHERE cached=0'):
                    if p in rows:
                        rows[p]['logged'] += 1
                        reconciliation = self.root/'reconciliations'/f'{digest(path.relative_to(self.root).as_posix())}-{row_id}.json'
                        if reconciliation.exists():
                            fix = read(reconciliation)
                            if (fix['provider']!=p or fix['original_error']!=error or fix['original_cost']!=cost
                                    or fix['ledger_sha256']!=sha(path)):
                                raise RuntimeError('invalid cost reconciliation')
                            cost, error = fix['recorded_cost'], None
                        rows[p]['usd'] += cost or 0
                        rows[p]['errors'] += int(cost is None or bool(error))
        for p, row in rows.items():
            row['usd'] = round(row['usd'], 6)
            row['remaining_calls'] = self.limits[p][0]-row['reserved']
            row['remaining_usd'] = round(self.limits[p][1]-row['usd'], 6)
        return rows

    def reserve(self, provider):
        if provider not in self.limits:
            raise ValueError('provider outside approval')
        with closing(sqlite3.connect(self.path, timeout=0)) as db:
            db.execute('BEGIN IMMEDIATE')
            for p, row in self.usage().items():
                if ((p == provider and row['reserved'] >= self.limits[p][0]) or row['usd'] >= self.limits[p][1]
                        or row['errors'] or row['reserved'] != row['logged']):
                    raise RuntimeError('trial stopped: limit or unresolved external attempt: '+p)
            db.execute('INSERT INTO attempts(provider) VALUES (?)', (provider,))
            db.commit()


def prepare():
    if OUT.exists():
        raise RuntimeError('trial already prepared')
    sample_hash = sha(OLD/'sample.json')
    approval = read(OLD/'openai_approval.json')
    # Régi jóváhagyás szöveghash-t használt, nem Windows-sorvég szerinti fájlhash-t.
    assert digest((OLD/'sample.json').read_text(encoding='utf-8')) == approval['sample_sha256']
    cases = {c['case_id']: c for c in read(OLD/'frozen_inputs.json')}
    source_sample = {c['case_id']: c for c in read(OLD/'sample.json')['cases']}
    selected = []
    for cid in IDS:
        c = cases[cid]
        assert c['sha256'] == source_sample[cid]['sha256'] == sha(Path(c['path']))
        assert digest(c['text']) == c['source_sha256'] and len(c['text']) <= 50000
        item = {k:c[k] for k in ('case_id','sha256','source_sha256','text','category','page_count')}
        item['layout'] = read(LONG/(cid+'-layout.json')) if cid in IDS[:3] else None
        selected.append(item)
    OUT.mkdir(parents=True)
    protected = {}
    for folder in (OLD,LONG):
        for path in folder.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                protected[path.relative_to(PROJECT_ROOT).as_posix()] = sha(path)
    for folder in ('configs','docs/handoffs'):
        for path in (PROJECT_ROOT/folder).rglob('*'):
            if path.is_file():
                protected[path.relative_to(PROJECT_ROOT).as_posix()] = sha(path)
    write(OUT/'protected.json', protected)
    write(OUT/'inputs.json', selected)
    write(OUT/'approval.json', {'approved':True,'authority':'Explicit user instruction 2026-09-21, handoff 030',
        'sample_sha256':sample_hash,'previous_approval_sample_sha256':approval['sample_sha256'],
        'selected_ids':IDS,'allowed_providers':['openai','jev'],'max_document_chars':50000,
        'max_source_part_chars':8000,'maximum_generation_calls':120,'maximum_jev_calls':1200,
        'openai_recorded_stop_usd':6,'jev_recorded_stop_usd':2,
        'personal_invoice_banking_data_approved':True,'old_budget_unchanged':True})
    config = load_config()
    config.update(max_points=8, max_text_chars=8000, proposal_request_limit=1,
        resolve_context_spans=True,
        proposal_model_settings={'openai_reasoning_effort':'none','temperature':0.,'max_tokens':4000})
    config['claims']['max_context_chars'] = 8000
    config['proposal_instructions'] = config['proposal_instructions'].replace('at most 24 points','at most 8 points')
    write(OUT/'config.json', config)
    write(OUT/'initial-preflight.json', {'pytest':'297 passed, 1 warning','contracts':'4 PASS','external_calls':0})
    print('prepared', IDS, flush=True)


def validate():
    approval = read(OUT/'approval.json')
    assert approval['approved'] is True and approval['sample_sha256'] == sha(OLD/'sample.json')
    if (OUT/'frozen.json').exists():
        for name, expected in read(OUT/'frozen.json').items():
            if sha(OUT/name) != expected:
                raise RuntimeError('frozen trial input changed: '+name)
    for relative, expected in read(OUT/'protected.json').items():
        if sha(PROJECT_ROOT/relative) != expected:
            raise RuntimeError('protected evidence changed: '+relative)
    cases = read(OUT/'inputs.json')
    old = {c['case_id']: c for c in read(OLD/'frozen_inputs.json')}
    assert {c['case_id'] for c in cases} == set(IDS)
    for c in cases:
        assert c['text'] == old[c['case_id']]['text'] and digest(c['text']) == c['source_sha256']
        assert len(c['text']) <= 50000
    return cases


def snapshot(stage):
    target = OUT/stage/'snapshot.json'
    if target.exists():
        for relative, expected in read(target).items():
            if sha(PROJECT_ROOT/relative) != expected:
                raise RuntimeError('stage code changed; use a new stage')
        return
    paths = list((PROJECT_ROOT/'jav').rglob('*.py')) + list((PROJECT_ROOT/'tests').glob('test_long_document_trial.py'))
    for p in paths:
        dest = OUT/stage/'source_snapshot'/p.relative_to(PROJECT_ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p,dest)
    write(target,{p.relative_to(PROJECT_ROOT).as_posix():sha(p) for p in paths})


def services():
    from typesafe_sdk import RetryPolicy
    from jav.config import get_openai_key, make_client
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.models.wrapper import WrapperModel
    budget = TrialBudget(OUT)
    class BoundedModel(WrapperModel):
        async def request(self, *args, **kwargs):
            budget.reserve('openai')
            return await super().request(*args, **kwargs)
    class BoundedJev(JevAdapter):
        def _live(self,*args,**kwargs):
            budget.reserve('jev')
            return super()._live(*args,**kwargs)
    model = BoundedModel(OpenAIChatModel('gpt-5.4-mini', provider=OpenAIProvider(
        openai_client=AsyncOpenAI(api_key=get_openai_key(), max_retries=0, timeout=90))))
    adapter = BoundedJev(client=make_client(retry=RetryPolicy(max_retries=0)), model='jev-1.13.0',cache_dir=OUT/'cache')
    return model, adapter, budget


def generate(limit=None, stage='baseline-v2'):
    cases = validate()
    assert (OUT/'gold.json').exists(), 'freeze expected outcomes before model calls'
    snapshot(stage)
    model, adapter, budget = services()
    config = read(OUT/'config.json')
    policy = ChunkPolicy.model_validate(load_chunk_config()['chunk_policy'])
    for case in cases[:3]:
        path = OUT/stage/(case['case_id']+'.json')
        if path.exists():
            continue
        result = run_chunked_learning(text=case['text'],layout=[LineLayout.model_validate(r) for r in case['layout']],
            directory=OUT/stage/case['case_id'],run_id=case['case_id']+'-long',adapter=adapter,model=model,
            config=config,chunk_policy=policy,source_char_limit=50000,stop_after_chunks=limit)
        if result['coverage']['complete']:
            write(path,result)
        print(case['case_id'],result['coverage'],budget.usage(),flush=True)
        if limit:
            break


def probes(stage='baseline-v2'):
    validate()
    snapshot(stage)
    model, adapter, budget = services()
    config = read(OUT/'config.json')
    for group in read(OUT/'gold.json')['groups']:
        run_id = group['id']
        receipt = OUT/stage/(run_id+'-probes.json')
        if receipt.exists():
            continue
        points = [PointProposal.model_validate(x['proposal']) for x in group['points']]
        batch = ProposalBatch(source_sha256=digest(group['text']),points=points)
        result = run_learning(text=group['text'],directory=OUT/stage/'probes',run_id=run_id+'-claims',
            adapter=adapter,config=config,proposals=batch)['result']
        specific = config | {'proposal_instructions': config['proposal_instructions']+' '+load_chunk_config()['proposal_context_instructions']+
            ' Extract only the following requested fields, using these exact names. Omit missing or contradictory values. '+json.dumps(group['targets'],ensure_ascii=False)}
        generated = run_learning(text=group['text'],directory=OUT/stage/'probes',run_id=run_id+'-gen',
            adapter=adapter,config=specific,model=model)['result']
        local = None
        if group['provenance']=='controlled_counterfactual':
            local_text = group['text'][:-len(group['appended_text'])]
            local_batch = ProposalBatch(source_sha256=digest(local_text),points=points[:1])
            local = run_learning(text=local_text,directory=OUT/stage/'probes',run_id=run_id+'-local-only',
                adapter=adapter,config=config,proposals=local_batch)['result']
        write(receipt, {'group_id':run_id,'provenance':group['provenance'],
            'expected':[x['expected'] for x in group['points']], 'checked':result,'generated':generated,'local_only':local})
        print(run_id, [p['verification']['status'] for p in result['points']],
            'generated',len(generated['points']),budget.usage(),flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['prepare','generate','probes','usage','validate'])
    p.add_argument('--limit',type=int)
    args = p.parse_args()
    if args.command == 'prepare': prepare()
    elif args.command == 'generate': generate(args.limit)
    elif args.command == 'probes': probes()
    elif args.command == 'validate': validate(); print('protected evidence unchanged')
    else: print(json.dumps(TrialBudget(OUT).usage(),indent=2))


if __name__ == '__main__':
    main()
