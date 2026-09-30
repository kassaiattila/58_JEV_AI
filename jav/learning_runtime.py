"""Tartós Burr-futtató saját válasznaplóval; a kísérleti stack_trial mintájára."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from typesafe_sdk import SystemOneResponse

from jav import store, flow_learning
from jav.config import PROJECT_ROOT
from jav.document_learning import ProposalBatch, check_proposals, digest, propose, resolve_literal_spans, resolve_context_spans
from jav.runtime.persistence import ClosingSQLitePersister


def canonical_hash(value):
    return digest(json.dumps(value,sort_keys=True,ensure_ascii=False))


def code_hash():
    return canonical_hash({p.relative_to(PROJECT_ROOT).as_posix():digest(p.read_text(encoding='utf-8'))
                           for p in sorted((PROJECT_ROOT/'jav').rglob('*.py'))})


class LearningService:
    def __init__(self, text, model, adapter, config, batch, fault, use_cache):
        self.text,self.model,self.adapter,self.config,self.batch,self.fault = text,model,adapter,config,batch,fault
        self.use_cache=use_cache

    def event(self, name):
        if self.fault:
            self.fault(name)

    def extract(self, *, run_id):
        saved=store.load_artifact('learning_proposals',run_id)
        if saved is not None:
            return saved
        if self.batch is not None:
            batch=self.batch
        else:
            if store.load_artifact('learning_generation_started',run_id) is not None:
                raise RuntimeError('unresolved external call: generation; inspect ledger before a new run')
            store.save_artifact('learning_generation_started',run_id,{'source_sha256':digest(self.text)})
            batch=propose(self.text,model=self.model,config=self.config,run_id=run_id)
        saved=batch.model_dump(mode='json')
        store.save_artifact('learning_proposals',run_id,saved)
        self.event('after_proposals')
        return saved

    def verify(self, proposals, *, run_id):
        batch=ProposalBatch.model_validate(proposals)
        if self.config.get('resolve_context_spans',False):
            batch,changes=resolve_context_spans(self.text,batch,
                expand_exact_context=self.config.get('expand_exact_context',False),
                context_ranges=self.config.get('context_ranges'))
            store.save_artifact('learning_span_resolution',run_id,{'method':'unique_exact_context','changes':changes})
        elif self.config.get('resolve_literal_spans',False):
            batch,changes=resolve_literal_spans(self.text,batch)
            store.save_artifact('learning_span_resolution',run_id,{'method':'unique_exact_quote','changes':changes})
        index=0
        def ask(step,state,questions):
            nonlocal index
            current=index
            index+=1
            key=f'{run_id}:{current}'
            request={'step':step,'state':state,'questions':{k:q.model_dump(mode='json') for k,q in questions.items()}}
            saved=store.load_artifact('learning_exchange',key)
            if saved is not None:
                if saved['request'] != request:
                    raise ValueError('recorded request mismatch')
                if saved.get('error'):
                    from jav.adapters.jev import JevUnavailableError
                    raise JevUnavailableError(saved['error'])
                return SystemOneResponse.model_validate(saved['response'])
            if store.load_artifact('learning_exchange_started',key) is not None:
                raise RuntimeError('unresolved external call: JEV; inspect ledger before a new run')
            store.save_artifact('learning_exchange_started',key,request)
            from jav.adapters.jev import JevUnavailableError
            try:
                result=self.adapter.ask(step,state,questions,run_id=run_id,use_cache=self.use_cache,
                                        config_hash=canonical_hash(self.config))
            except JevUnavailableError as exc:
                store.save_artifact('learning_exchange',key,{'request':request,'error':exc.reason})
                raise
            self.event(f'before_exchange_save:{current}')
            store.save_artifact('learning_exchange',key,{'request':request,
                'response':result.response.model_dump(mode='json'),'call':result.call.model_dump(mode='json')})
            self.event(f'after_exchange:{current}')
            return result.response
        return check_proposals(self.text,batch,ask,self.config).model_dump(mode='json')


def run_learning(*, text: str, directory: Path, run_id: str, adapter, config: dict,
                 model=None, proposals: ProposalBatch | None=None, halt_after=None, fault=None, use_cache=False):
    """Azonos futás folytatása, változó forrás/konfig/kód/modell esetén elutasítás.

    A külső válasz megérkezése és tartós mentése közötti összeomlás nem tehető
    pontosan-egyszerivé szolgáltatói idempotenciakulcs nélkül: ilyenkor megállunk.
    """
    if not run_id or (model is None)==(proposals is None):
        raise ValueError('provide a run ID and exactly one of model or proposals')
    if not text.strip() or len(text)>min(config['max_text_chars'],config['claims']['max_context_chars']):
        raise ValueError('source empty or exceeds explicit context limit')
    if proposals is not None and (proposals.source_sha256!=digest(text) or len(proposals.points)>config['max_points']):
        raise ValueError('invalid proposal source or count')
    if not adapter.model.startswith('jev-') or adapter.model in ('jev-latest','jev-stable'):
        raise ValueError('pin a concrete JEV model for durable runs')
    identity={'source_sha256':digest(text),'config':config,
        'generator':{'provider':getattr(model,'system',None),'model':str(getattr(model,'model_name',model))},
        'proposals':proposals.model_dump(mode='json') if proposals is not None else None,
        'jev_model':adapter.model,'use_cache':use_cache,
        'code_sha256':code_hash()}
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    # SQLite-foglalás: párhuzamos futtató nem végezhet kétszer ugyanazt a külső hívást.
    with closing(sqlite3.connect(directory/'worker.sqlite',timeout=0)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        with store.use_store(directory/'business.sqlite'):
            store.save_artifact('learning_identity',run_id,identity)
            service=LearningService(text,model,adapter,config,proposals,fault,use_cache)
            class Persister(ClosingSQLitePersister):
                def save(self,partition_key,app_id,sequence_id,position,state,status,**kwargs):
                    if status=='completed':
                        service.event('after_action:'+position)
                    return super().save(partition_key,app_id,sequence_id,position,state,status,**kwargs)
            persister=Persister(str(directory/'burr.sqlite'))
            try:
                persister.initialize()
                saved=persister.load('learning',run_id)
                if saved and saved['status']=='completed' and saved['position'] in flow_learning.TERMINALS:
                    return saved['state'].get_all()
                app=(flow_learning.builder(service).with_identifiers(app_id=run_id,partition_key='learning')
                     .initialize_from(persister,resume_at_next_action=True,default_state={'run_id':run_id},
                                      default_entrypoint='generate')
                     .with_state_persister(persister).build())
                with adapter.no_cache_write():
                    _,_,state=app.run(halt_after=halt_after or flow_learning.TERMINALS)
                return state.get_all()
            finally:
                persister.cleanup()


def run_chunked_learning(*, text, directory, run_id, adapter, config, chunk_policy,
                         model=None, proposals=None, layout=None, stop_after_chunks=None,
                         fault=None, use_cache=False, offline=False, source_char_limit=16000):
    """Dokumentumrészenként a meglévő Burr-folyamat, összesített forráslefedéssel.

    A küldési korlát a TELJES dokumentumra vonatkozik, nem a rész méretére.
    offline esetben kizárólag importált javaslat és CacheOnlyAdapter megengedett.
    A source_char_limit növelése külön adatküldési engedélyt igényel.
    """
    from jav.document_chunks import plan_document, load_chunk_config
    from jav.adapters.jev import CacheOnlyAdapter
    if not run_id or (model is None)==(proposals is None):
        raise ValueError('provide a run ID and exactly one of model or proposals')
    if stop_after_chunks is not None and stop_after_chunks < 1:
        raise ValueError('stop_after_chunks must be positive')
    if offline:
        if model is not None or not isinstance(adapter, CacheOnlyAdapter):
            raise ValueError('offline requires imported proposals and CacheOnlyAdapter')
    elif len(text)>source_char_limit:
        raise ValueError('document exceeds external source character limit; no requests were sent')
    plan=plan_document(text,chunk_policy,layout=layout)
    if chunk_policy.max_chars>min(config['max_text_chars'],config['claims']['max_context_chars']):
        raise ValueError('chunk exceeds verifier context limit')
    batches=None if proposals is None else {k:ProposalBatch.model_validate(v) for k,v in proposals.items()}
    if batches is not None:
        if set(batches)!={c.id for c in plan.chunks}:
            raise ValueError('provide exactly one proposal batch for every chunk')
        for chunk in plan.chunks:
            batch=batches[chunk.id]
            if batch.source_sha256!=chunk.source_sha256 or len(batch.points)>config['max_points']:
                raise ValueError('invalid chunk proposal source or count')
            if not text[chunk.start:chunk.end].strip() and batch.points:
                raise ValueError('blank chunk cannot contain point proposals')
    chunk_config=load_chunk_config()
    effective=config|{'resolve_context_spans':True,
        'proposal_instructions':config['proposal_instructions']+' '+chunk_config['proposal_context_instructions']}
    identity={'plan':plan.model_dump(mode='json'),'config':effective,'code_sha256':code_hash(),
              'chunk_config':chunk_config,
              'generator':{'provider':getattr(model,'system',None),'model':str(getattr(model,'model_name',model))},
              'proposals':{k:v.model_dump(mode='json') for k,v in batches.items()} if batches is not None else None,
              'jev_model':adapter.model,'use_cache':use_cache,'offline':offline,'source_char_limit':source_char_limit}
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    # A szülő és a gyermek külön zárolást használ; az egész dokumentum egy munkásé.
    with closing(sqlite3.connect(directory/'document_worker.sqlite',timeout=0)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        with store.use_store(directory/'document.sqlite'):
            store.save_artifact('learning_document_identity',run_id,identity)
            saved=store.load_artifact('learning_document_result',run_id)
            if saved is not None:
                return saved
        completed=[]
        grouped={}
        omitted=0
        for chunk in plan.chunks:
            child_id=canonical_hash({'parent':run_id,'chunk':chunk.id})
            chunk_text=text[chunk.start:chunk.end]
            if chunk_text.strip():
                child=run_learning(text=chunk_text,directory=directory/'parts',run_id=child_id,
                    adapter=adapter,config=effective,model=model,
                    proposals=batches[chunk.id] if batches is not None else None,fault=fault,use_cache=use_cache)
                result=child['result']
            else:
                result={'points':[],'omitted_candidates':0}
                child_id=None
            completed.append({'chunk_id':chunk.id,'run_id':child_id,'start':chunk.start,'end':chunk.end,
                              'points':len(result['points']),'blank':not chunk_text.strip()})
            omitted+=result['omitted_candidates']
            for index,point in enumerate(result['points']):
                start=None if point['start'] is None else point['start']+chunk.start
                end=None if point['end'] is None else point['end']+chunk.start
                fact={k:point['proposal'][k] for k in ('name','role','raw_value','unit','entity_id','quote')}
                # Csak ugyanaz a forráshely ÉS ugyanaz az állítás vonható össze.
                # Feloldatlan idézet és eltérő szerep/entitás sosem esik ki.
                key=canonical_hash({'start':start,'end':end,'fact':fact,
                                    'unresolved':[chunk.id,index] if start is None else None})
                if key not in grouped:
                    grouped[key]={'id':key,'source_sha256':plan.source_sha256,'start':start,'end':end,
                                  'page':chunk.page,'section_id':chunk.section_id,'fact':fact,'evidence':[]}
                grouped[key]['evidence'].append({'chunk_id':chunk.id,'point':point})
            if stop_after_chunks is not None and len(completed)>=stop_after_chunks:
                break
        covered=0
        last=0
        for chunk in plan.chunks[:len(completed)]:
            covered+=max(0,chunk.end-max(last,chunk.start))
            last=max(last,chunk.end)
        evidence=[e for p in grouped.values() for e in p['evidence']]
        report={'source_sha256':plan.source_sha256,'plan':plan.model_dump(mode='json'),
                'completeness':'not_established','omitted_candidates':omitted,
                'coverage':{'chunks_total':len(plan.chunks),'chunks_completed':len(completed),
                            'source_chars':len(text),'covered_chars':covered,'complete':covered==len(text)},
                'verification_complete':covered==len(text) and all(e['point']['verification']['status'] not in
                    ('unavailable','not_checked') for e in evidence),
                'completed':completed,'points':list(grouped.values())}
        with store.use_store(directory/'document.sqlite'):
            store.save_artifact('learning_document_progress',f'{run_id}:{len(completed)}',report)
            if report['coverage']['complete']:
                store.save_artifact('learning_document_result',run_id,report)
        return report
