"""Only legacy synthetic fixtures; real bank documents cannot enter this runner."""
from jav.experiments.expansion_trial import ROOT, services, validate
from jav.experiments.long_document_trial import read, write
from jav.legacy_packs import keys, PACK_ROOT, schema_model
from jav.legacy_runtime import run_pack
from jav.provider_generation import generate
from jav.learning_runtime import canonical_hash
from jav.config import PROJECT_ROOT
from jav import store
from pydantic_ai import Agent
import json


def main(replay=False):
    validate()
    cfg=read(PROJECT_ROOT/'configs/experiments/legacy_extraction.json')
    if not replay:model,adapter,budget=services()
    count=0
    for key in keys():
        for source in sorted((PACK_ROOT/key/'fixtures').glob('*.json')):
            expected=read(source)['datapoints']
            text='Document record supplied by the source system:\n'+json.dumps(expected,ensure_ascii=False,indent=2)
            rid='fixture-'+key
            target=ROOT/'document_results'/(rid+'.json')
            if target.exists() and not replay:continue
            def extract(pack,text,run_id):
                if replay:raise AssertionError('GPT on replay')
                agent=Agent(model,output_type=schema_model('Legacy_'+pack['key'],pack['schema']),
                    instructions=pack['prompt'],retries=0,model_settings=cfg['model_settings'])
                return generate(agent,text,run_id=run_id,step='legacy_extract',model_name='gpt-5.4-mini',
                    config_hash=canonical_hash(cfg))['output']
            def ask(step,state,questions,run_id):
                if replay:raise AssertionError('JEV on replay')
                with adapter.no_cache_write():
                    response=adapter.ask(step,state,questions,run_id=run_id,use_cache=False,config_hash=canonical_hash(cfg))
                store.save_artifact('legacy_jev_exchange',run_id+':'+canonical_hash(list(questions)),
                    {'state':state,'questions':{k:q.model_dump(mode='json') for k,q in questions.items()},
                     'response':response.response.model_dump(mode='json')})
                return response.response
            args=dict(key=key,text=text,directory=ROOT/'documents'/rid,run_id=rid,config=cfg,generate=extract,ask=ask)
            if not replay:run_pack(**args,halt_after=['generate'])
            result=run_pack(**args)
            if replay:assert result==read(target)['state']
            else:write(target,{'case_id':rid,'kind':'legacy_structured_fixture','state':result,
                          'exact_fixture_match':result['result']['raw_record']==expected})
            count+=1
            print(rid,'valid',result['result']['validation']['valid'],flush=True)
    if replay:write(ROOT/'synthetic-document-replay.json',{'exact_cases':count,'external_calls':0,'mechanism':'Burr persisted terminal state'})
    else:write(ROOT/'synthetic-document-usage.json',{'new_cases':count,'usage':budget.usage(),
        'source':'configs/legacy_types/*/fixtures/*.json only; no real documents read'})


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--replay',action='store_true')
    main(parser.parse_args().replay)
