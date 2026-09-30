"""A meglévő document_learning Burr-gráf új szolgáltatása: régi séma szerinti kivonat."""
from __future__ import annotations
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from jav import store, flow_learning
from jav.legacy_packs import load, schema_model, validate_record
from jav.learning_runtime import canonical_hash
from jav.runtime.persistence import ClosingSQLitePersister


def leaves(value,path=''):
    if isinstance(value,dict):
        for key,item in value.items():
            yield from leaves(item,path+'/'+str(key).replace('~','~0').replace('/','~1'))
    elif isinstance(value,list):
        for index,item in enumerate(value):
            yield from leaves(item,path+'/'+str(index))
    elif value is not None:
        yield {'path':path,'value':value}


def run_pack(*, key, text, directory, run_id, config, generate, ask, halt_after=None):
    if not text.strip() or len(text)>config['source_max_chars']:
        raise ValueError('empty source or source transfer ceiling exceeded')
    pack=load(key)
    identity={'key':key,'source_sha256':canonical_hash(text),'pack':pack['manifest'],'config':config,
              'runtime_sha256':canonical_hash(Path(__file__).read_text(encoding='utf-8'))}
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(directory/'worker.sqlite',timeout=0)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        with store.use_store(directory/'business.sqlite'):
            store.save_artifact('legacy_identity',run_id,identity)
            def stage(name,fn):
                sid=run_id+':'+name
                saved=store.load_artifact('legacy_stage',sid)
                if saved is not None: return saved
                if store.load_artifact('legacy_started',sid) is not None:
                    raise RuntimeError('unresolved external call: '+name)
                store.save_artifact('legacy_started',sid,{'identity':canonical_hash(identity)})
                value=fn()
                store.save_artifact('legacy_stage',sid,value)
                return value
            class Service:
                def extract(self, *,run_id):
                    return stage('generate',lambda:generate(pack,text,run_id))
                def verify(self, proposals, *,run_id):
                    from typesafe_sdk import Noul
                    validation=validate_record(pack,proposals)
                    points=list(leaves(proposals))
                    selected=points[:config['max_verified_leaves']]
                    verified=[]
                    size=config['verification_batch_fields']
                    for start in range(0,len(selected),size):
                        batch=selected[start:start+size]
                        qs={f'f{start+i}':Noul(instructions={'question':config['verification_question'],'field':point})
                            for i,point in enumerate(batch)}
                        def execute():
                            response=ask('legacy_verify',{'source':text,'document_type':key},qs,run_id)
                            return {k:v.noul for k,v in response.nouls.items()}
                        answers=stage('verify-'+str(start),execute)
                        verified.extend(point|{'support':answers[f'f{start+i}']} for i,point in enumerate(batch))
                    return {'document_type':key,'raw_record':proposals,'validation':validation,
                        'field_verification':verified,'non_null_leaves':len(points),'verified_leaves':len(verified),
                        'verification_complete_for_extracted_values':len(verified)==len(points),
                        'source_sha256':canonical_hash(text),'candidate_only':True,
                        'correctness':'not_established','extraction_completeness':'not_established','human_gold':None}
            persister=ClosingSQLitePersister(str(directory/'burr.sqlite'))
            try:
                persister.initialize()
                saved=persister.load('legacy',run_id)
                if saved and saved['position']=='done' and saved['status']=='completed':
                    return saved['state'].get_all()
                app=(flow_learning.builder(Service()).with_identifiers(app_id=run_id,partition_key='legacy')
                     .initialize_from(persister,resume_at_next_action=True,default_state={'run_id':run_id},default_entrypoint='generate')
                     .with_state_persister(persister).build())
                _,_,state=app.run(halt_after=halt_after or ['done'])
                return state.get_all()
            finally: persister.cleanup()
