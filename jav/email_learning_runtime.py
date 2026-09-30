"""Durable Burr trial for emails; it records its own JEV responses and never blindly resends after an interruption."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typesafe_sdk import SystemOneResponse

from jav import store, policy, cfg, flow_email_learning
from jav.intent import build_state, build_questions, decode_result, CONFIG_HASH
from jav.emails import EmailMessage
from jav.email_learning import validate_case, build_evidence_state
from jav.learning_runtime import canonical_hash, code_hash
from jav.models import JevCall
from jav.runtime.persistence import ClosingSQLitePersister
from jav.source_evidence import select_evidence


class EmailLearningService:
    def __init__(self,case,adapter,config,fault=None,baseline_record=None):
        self.case,self.adapter,self.config,self.fault=case,adapter,config,fault
        self.baseline_record=baseline_record

    def ask(self,key,state,questions,run_id,config_hash):
        request=dict(state=state,questions={k:q.model_dump(mode='json') for k,q in questions.items()},config_hash=config_hash)
        aid=run_id+':'+key
        saved=store.load_artifact('email_exchange',aid)
        if saved:
            if saved['request']!=request: raise ValueError('recorded request mismatch')
            return SystemOneResponse.model_validate(saved['response']),JevCall.model_validate(saved['call'])
        if store.load_artifact('email_exchange_started',aid):
            raise RuntimeError('unresolved external attempt; no automatic retry')
        store.save_artifact('email_exchange_started',aid,request)
        result=self.adapter.ask(key,state,questions,run_id=run_id,use_cache=False,config_hash=config_hash)
        store.save_artifact('email_exchange',aid,dict(request=request,response=result.response.model_dump(mode='json'),
                                                     call=result.call.model_dump(mode='json')))
        if self.fault: self.fault('after_exchange:'+key)
        return result.response,result.call

    def classify_baseline_jev(self,*,run_id):
        if self.baseline_record is not None:
            return self.baseline_record['baseline']
        state=build_state(EmailMessage.model_validate(self.case['message']))
        r,call=self.ask('baseline',state,build_questions(),run_id,CONFIG_HASH)
        return decode_result(r,call,state).model_dump(mode='json')

    def scan_jev(self,*,run_id):
        searches={}
        for source in self.case['sources']:
            if source['status']!='read': continue
            def ask(step,state,questions):
                return self.ask(source['id']+':'+step,state,questions,run_id,canonical_hash(self.config))[0]
            query=self.config['query']+' Source role: '+source['kind']+'.'
            searches[source['id']]=select_evidence(source['text'],query,ask,source_limit=50000,
                                                    guard_instructions=self.config.get('scan_guard'))
        return searches

    def classify_evidence(self,searches,*,run_id):
        state,coverage=build_evidence_state(self.case,searches)
        r,call=self.ask('evidence_intent',state,build_questions(self.config),run_id,canonical_hash(self.config))
        result=decode_result(r,call,state).model_dump(mode='json')
        raw_guard=result['signals']['prompt_injection']
        scan_guard=max([d.get('prompt_injection') or 0 for search in searches.values() for d in search['decisions']]+[0])
        result['guard_evidence']=dict(final=raw_guard,all_scanned_parts=scan_guard,aggregation='max; existing email.signal policy')
        result['signals']['prompt_injection']=max(raw_guard,scan_guard)
        result.update(evidence=state['evidence'],coverage=coverage,
                      extra_signals={k:float(r.nouls[k].noul) for k in self.config['extra_signals']})
        return result

    def candidate(self,baseline,result):
        msg=EmailMessage.model_validate(self.case['message'])
        reasons=list(result['coverage']['review_reasons'])
        if baseline['intent']!=result['intent']: reasons.append('baseline_evidence_disagreement')
        reasons+=policy.email_signal_reasons(result['signals'])
        for key,value in result['extra_signals'].items():
            reason=policy.noul_review_reason('evidence',key,value,'email.signal')
            if reason: reasons.append(reason)
        route=policy.email_next_flow(result['intent'],result['confidence'],msg.attachments,result['probabilities'],result['signals'])
        if route.startswith('human:'): reasons.append('policy:'+route)
        return dict(case_id=self.case['case_id'],case_sha256=canonical_hash(self.case),status='unreviewed',
            baseline=baseline,prediction=result,review_reasons=sorted(set(reasons)) or ['control_sample'],
            suggested_route=route,route_executed=False,correctness='not_established',gold_label=None,
            config_sha256=canonical_hash(self.config),model=self.adapter.model)


def run_email_learning(*,case,directory,run_id,adapter,config,halt_after=None,fault=None,baseline_record=None):
    validate_case(case)
    if not run_id or adapter.model in ('jev-latest','jev-stable') or not adapter.model.startswith('jev-'):
        raise ValueError('run ID and concrete JEV model required')
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    identity=dict(case_sha256=canonical_hash(case),config=config,baseline_hash=CONFIG_HASH,
                  registry=cfg.load('intents'),model=adapter.model,code_sha256=code_hash(),baseline_record=baseline_record)
    if baseline_record is not None and (baseline_record['case_sha256']!=canonical_hash(case) or
            baseline_record['config_hash']!=CONFIG_HASH or baseline_record['baseline']['call']['model']!=adapter.model):
        raise ValueError('baseline source/config/model mismatch')
    with closing(sqlite3.connect(directory/'worker.sqlite',timeout=0)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        with store.use_store(directory/'business.sqlite'):
            store.save_artifact('email_learning_identity',run_id,identity)
            service=EmailLearningService(case,adapter,config,fault,baseline_record)
            persister=ClosingSQLitePersister(str(directory/'burr.sqlite'))
            try:
                persister.initialize()
                saved=persister.load('email-learning',run_id)
                if saved and saved['status']=='completed' and saved['position']=='done':
                    return saved['state'].get_all()
                app=(flow_email_learning.builder(service).with_identifiers(app_id=run_id,partition_key='email-learning')
                     .initialize_from(persister,resume_at_next_action=True,default_state={'run_id':run_id},default_entrypoint='baseline')
                     .with_state_persister(persister).build())
                with adapter.no_cache_write():
                    _,_,state=app.run(halt_after=halt_after or ['done'])
                return state.get_all()
            finally:
                persister.cleanup()
