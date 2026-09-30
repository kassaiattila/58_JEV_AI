"""Korlátos K1-próba: helyi címkejelöltek + élő JEV, ugyanazon engedélyezett mintán."""
from __future__ import annotations

import argparse
from pathlib import Path
from collections import Counter

from jav import store
from jav.adapters.jev import JevAdapter
from jav.config import PROJECT_ROOT
from jav.document_learning import ProposalBatch,check_proposals,load_config,propose_labels,save_result,load_result,digest
from jav.experiments.real_grounded_trial import DATA,OUT as INPUTS,read,write,code_hashes,reserve_call

OUT = PROJECT_ROOT / "runs/20260921_document_learning"
PREVIOUS = PROJECT_ROOT / "runs/20260921_grounded_revision"


class TrialAdapter(JevAdapter):
    def _live(self,*args,**kwargs):
        # A 024-ben megnyitott 200-as keret közös, már 150 foglalást tartalmaz.
        with store.connect(PREVIOUS/'business.sqlite') as db:
            prior = db.execute("SELECT coalesce(sum(cost_usd),0) FROM ledger WHERE cached=0").fetchone()[0]
        with store.connect() as db:
            current = db.execute("SELECT coalesce(sum(cost_usd),0) FROM ledger WHERE cached=0").fetchone()[0]
        if prior + current >= 1:
            raise RuntimeError("recorded round cost stop threshold reached")
        reserve_call(PREVIOUS/'budget.sqlite',already_used=0,maximum=200)
        return super()._live(*args,**kwargs)


def prepare():
    if (OUT/'manifest.json').exists():
        raise RuntimeError('prepared evidence already exists')
    OUT.mkdir(exist_ok=True)
    config = load_config() | {"max_points":3}
    inputs = [dict(case_id=c['case_id'],text=c['text'],source_sha256=c['source_sha256'],origin='authorized_invoice')
              for c in read(INPUTS/'frozen_inputs.json')]
    inputs += [dict(case_id='synthetic-maintenance',text='Bearing temperature: 68 Celsius\nInspection time: 14:20',origin='synthetic'),
               dict(case_id='synthetic-meeting',text='Meeting chair: Alice\nTask owner: Peter',origin='synthetic')]
    for case in inputs:
        batch = propose_labels(case['text'],config | {"max_points":2})
        points = list(batch.points)
        case['control_index'] = len(points) if points else None
        if points:
            points.append(points[0].model_copy(update={"raw_value":"FABRICATED_VALUE_NOT_IN_SOURCE"}))
        case['proposals'] = batch.model_copy(update={"points":points}).model_dump(mode='json')
    maximum = 2*sum(len(c['proposals']['points']) for c in inputs)
    if maximum > 50:
        raise RuntimeError("remaining round budget would be exceeded")
    write(OUT/'inputs.json',inputs)
    write(OUT/'manifest.json',dict(config=config,model='jev-1.13.0',hashes=code_hashes(),
        inputs_hash=digest((OUT/'inputs.json').read_text(encoding='utf-8')),
        sample_hash=digest((DATA/'sample.json').read_text(encoding='utf-8')),
        maximum_new_calls=maximum,previous_calls=150,previous_cost_usd=.018697,
        scope='same six authorized invoices, unknown schema forced for pipeline testing; two synthetic unknown-family texts; '
              'local labelled-line proposals, no live generative model; two uncached repeats; no new type accuracy claim'))
    print('prepared',len(inputs),'cases; max new calls',maximum)


def live():
    manifest=read(OUT/'manifest.json')
    if manifest['hashes'] != code_hashes():
        raise RuntimeError('code changed after preparation')
    if manifest['inputs_hash'] != digest((OUT/'inputs.json').read_text(encoding='utf-8')):
        raise RuntimeError('input snapshot changed')
    if manifest['sample_hash'] != digest((DATA/'sample.json').read_text(encoding='utf-8')):
        raise RuntimeError('authorized sample changed')
    for case in read(DATA/'sample.json')['cases']:
        if __import__('hashlib').sha256(Path(case['path']).read_bytes()).hexdigest()!=case['sha256']:
            raise RuntimeError('authorized source changed')
    with (OUT/'live.started').open('x') as f:
        f.write('exclusive measurement')
    adapter=TrialAdapter(model=manifest['model'],cache_dir=OUT/'cache')
    results=[]
    config_hash=digest((OUT/'manifest.json').read_text(encoding='utf-8'))
    with store.use_store(OUT/'business.sqlite'),adapter.no_cache_write():
        for repeat in range(2):
            for case in read(OUT/'inputs.json'):
                run_id=f"{case['case_id']}-{repeat}"
                calls=[]
                def ask(step,state,questions):
                    response=adapter.ask(step,state,questions,run_id=run_id,config_hash=config_hash,use_cache=False)
                    call=dict(step=step,state=state,questions={k:q.model_dump(mode='json') for k,q in questions.items()},
                              response=response.response.model_dump(mode='json'),call=response.call.model_dump(mode='json'))
                    store.save_artifact('jev_exchange',f'{run_id}:{len(calls)}',call)
                    calls.append(call)
                    return response.response
                result=check_proposals(case['text'],ProposalBatch.model_validate(case['proposals']),ask,manifest['config'])
                save_result(run_id,result)
                assert load_result(run_id)==result
                row=dict(run_id=run_id,case_id=case['case_id'],repeat=repeat,origin=case['origin'],control_index=case['control_index'],
                         result=result.model_dump(mode='json'),calls=calls)
                write(OUT/(run_id+'.json'),row)
                results.append(row)
                print(run_id,Counter(p.verification['status'] for p in result.points),flush=True)
        write(OUT/'results.json',results)
        ledger=[c for r in results for c in store.ledger_for_run(r['run_id'])]
        write(OUT/'ledger.json',ledger)
        print('calls',len(ledger),'cost',round(sum(c['cost_usd'] for c in ledger),6),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','live'])
    args=parser.parse_args()
    prepare() if args.mode=='prepare' else live()
