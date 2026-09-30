"""Larger, pre-frozen document trial; the preparation is strictly local."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from collections import Counter
from pathlib import Path

from jav.config import PROJECT_ROOT
from jav import store
from jav.adapters.jev import JevAdapter
from jav.document_learning import ProposalBatch, digest, load_config, propose_labels
from jav.experiments.prepare_stack_trial import CATEGORIES, roots
from jav.experiments.real_grounded_trial import read, write, code_hashes, reserve_call
from jav.learning_runtime import run_learning
from jav.pdf import PdfText, read_pdf

OUT=PROJECT_ROOT/'runs/20260921_expanded_learning'


def eligibility(pdf):
    return ('no_readable_text' if pdf.text_source not in ('pdf','ocr') else
            'context_limit' if len(pdf.text)>16000 else 'eligible')


def prepare():
    if (OUT/'sample.json').exists():
        raise RuntimeError('sample already frozen')
    OUT.mkdir(parents=True,exist_ok=True)
    previous={c['sha256'] for c in read(PROJECT_ROOT/'runs/20260921_stack_trial/sample.json')['cases']}
    seen=set(previous)
    cases=[]
    inventory=[]
    # Hash order by file path: no manual selection by year or supplier names.
    for category,quota in [('business',30),('bank',15),('household',15)]:
        root=roots()[category]  # 066 Á13: from the local selection file that git excludes
        paths=sorted(root.rglob('*.pdf'),key=lambda p:digest(str(p.relative_to(root)).casefold()))
        inventory.append({'category':category,'available_pdf_paths':len(paths),'target':quota})
        selected=0
        for path in paths:
            if selected>=quota:
                break
            try:
                file_hash=hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            if file_hash in seen:
                continue
            seen.add(file_hash)
            selected+=1
            case={'case_id':f'expanded-{len(cases)+1:03d}','category':category,'path':str(path),
                  'sha256':file_hash,'previous_selected20':False}
            try:
                pdf=read_pdf(path)
                case.update(text=pdf.text,lines=pdf.lines,page_count=pdf.page_count,text_source=pdf.text_source,
                            text_chars=len(pdf.text),source_sha256=digest(pdf.text))
                case['eligibility']=eligibility(pdf)
                if case['eligibility']=='eligible':
                    batch=propose_labels(pdf.text,load_config()|{'max_points':6})
                    case['label_baseline']=batch.model_dump(mode='json')
            except Exception as exc:
                case.update(eligibility='read_error',error=type(exc).__name__)
            cases.append(case)
            print(case['case_id'],category,case['eligibility'],case.get('page_count'),case.get('text_chars'),flush=True)
    write(OUT/'sample.json',{'selection':'path-hash ordered, content deduplicated, excludes prior selected20; 30 business/15 bank/15 household; no model-based selection',
        'inventory':inventory,'cases':cases})
    config=load_config()|{'max_points':6,'proposal_request_limit':1,
        'proposal_model_settings':{'openai_reasoning_effort':'none','temperature':0.0,'max_tokens':2500}}
    config['proposal_instructions']=config['proposal_instructions'].replace('at most 24 points','at most 6 points')
    repeats=[]
    for category in CATEGORIES:
        repeats += [c['case_id'] for c in cases if c['category']==category and c['eligibility']=='eligible'][:2]
    scope={'sample_sha256':digest((OUT/'sample.json').read_text(encoding='utf-8')),
        'config':config,'generator':'gpt-5.4-mini','jev_model':'jev-1.13.0','repeat_cases':repeats,
        'maximum_generation_calls':66,'maximum_jev_calls':600,'openai_recorded_stop_usd':3,
        'jev_recorded_stop_usd':1,'max_output_tokens_per_generation':2500,
        'personal_data_recipients':{'typesafe':'document detection and extracted claim verification; original text and necessary filename',
                                    'openai':'full readable text of eligible selected documents, at most 16000 characters per document'},
        'eligibility':dict(Counter(c['eligibility'] for c in cases)),
        'note':'Oversize or unreadable documents are reported, not silently truncated. No full-document completeness claim.'}
    write(OUT/'scope.json',scope)
    print('selected',len(cases),'eligibility',scope['eligibility'],'repeats',len(repeats))


def prepare_ocr():
    from jav.ocr import ocr_pdf
    if (OUT/'inputs.json').exists():
        raise RuntimeError('inputs already frozen')
    cases=read(OUT/'sample.json')['cases']
    for case in cases:
        if case['eligibility']!='no_readable_text':
            continue
        receipt=OUT/(case['case_id']+'-ocr.json')
        if receipt.exists():
            case.update(read(receipt))
            continue
        try:
            pdf=ocr_pdf(case['path'],page_count=case['page_count'],engine_name='native')
            result=dict(text=pdf.text,lines=pdf.lines,text_source=pdf.text_source,text_chars=len(pdf.text),
                        source_sha256=digest(pdf.text),ocr=pdf.ocr,
                        eligibility=eligibility(pdf))
            if result['eligibility']=='eligible':
                result['label_baseline']=propose_labels(pdf.text,load_config()|{'max_points':6}).model_dump(mode='json')
        except Exception as exc:
            result={'eligibility':'ocr_error','error':type(exc).__name__}
        write(receipt,result)
        case.update(result)
        print(case['case_id'],case['eligibility'],case.get('text_chars'),flush=True)
    write(OUT/'inputs.json',cases)
    print('final eligibility',dict(Counter(c['eligibility'] for c in cases)),flush=True)


def freeze():
    if (OUT/'manifest.json').exists():
        raise RuntimeError('measurement already frozen')
    scope=read(OUT/'scope.json')
    if scope['sample_sha256']!=digest((OUT/'sample.json').read_text(encoding='utf-8')):
        raise RuntimeError('selected sample changed')
    cases=read(OUT/'inputs.json')
    from jav.policy import ocr_review_reasons
    for case in cases:
        # The early OCR preparation used the PDF's text-layer signal; the OCR text_source is authoritative.
        case['eligibility']=eligibility(PdfText(path=case['path'],text=case.get('text',''),text_source=case.get('text_source')))
        signals=case.get('ocr') or {}
        case['reading_review_reasons']=ocr_review_reasons(signals.get('mean_conf'),signals.get('low_conf_ratio')) if signals else []
        if signals and signals.get('pages_ocr')!=case['page_count']:
            case['eligibility']='incomplete_ocr'
        if case['eligibility']=='eligible':
            case['label_baseline']=propose_labels(case['text'],scope['config']|{'max_points':2}).model_dump(mode='json')
    write(OUT/'frozen_inputs.json',cases)
    repeat_cases=[]
    for category in CATEGORIES:
        repeat_cases += [c['case_id'] for c in cases if c['category']==category and c['eligibility']=='eligible'][:2]
    manifest=scope|{'frozen_inputs_sha256':digest((OUT/'frozen_inputs.json').read_text(encoding='utf-8')),
                   'repeat_cases':repeat_cases,'hashes':code_hashes(),
                   'eligibility':dict(Counter(c['eligibility'] for c in cases)),
                   'baseline_max_points':2,'gold_claim':'no independent whole-document gold; separate source review required'}
    write(OUT/'manifest.json',manifest)
    for relative in manifest['hashes']:
        dest=OUT/'source_snapshot'/relative
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(PROJECT_ROOT/relative,dest)
    print('frozen',manifest['eligibility'],'repeat cases',len(repeat_cases),flush=True)


def check_frozen():
    manifest=read(OUT/'manifest.json')
    if manifest['hashes']!=code_hashes():
        raise RuntimeError('code/config changed after measurement freeze')
    if manifest['frozen_inputs_sha256']!=digest((OUT/'frozen_inputs.json').read_text(encoding='utf-8')):
        raise RuntimeError('frozen text changed')
    cases=read(OUT/'frozen_inputs.json')
    for case in cases:
        if hashlib.sha256(Path(case['path']).read_bytes()).hexdigest()!=case['sha256']:
            raise RuntimeError('selected source changed')
    return manifest,cases


def enforce_cost(provider, maximum):
    with store.connect(OUT/'business.sqlite') as db:
        rows=list(db.execute('SELECT cost_usd,error FROM ledger WHERE provider=? AND cached=0',(provider,)))
    if any(r['cost_usd'] is None or r['error'] for r in rows):
        raise RuntimeError('unresolved provider cost or error; automatic spending stopped')
    if sum(r['cost_usd'] for r in rows)>=maximum:
        raise RuntimeError('recorded cost threshold reached')


class ExpandedAdapter(JevAdapter):
    def _live(self,*args,**kwargs):
        manifest=read(OUT/'manifest.json')
        enforce_cost('jev',manifest['jev_recorded_stop_usd'])
        reserve_call(OUT/'jev_budget.sqlite',already_used=0,maximum=manifest['maximum_jev_calls'])
        return super()._live(*args,**kwargs)

    def ask(self,request_id,state,questions,**kwargs):
        result=super().ask(request_id,state,questions,**kwargs)
        if request_id=='detect':
            store.save_artifact('expanded_detection_response',kwargs['run_id'],{
                'state':state,'questions':{k:q.model_dump(mode='json') for k,q in questions.items()},
                'response':result.response.model_dump(mode='json'),'call':result.call.model_dump(mode='json')})
        return result


def scan():
    from jav.detect import detect
    manifest,cases=check_frozen()
    adapter=ExpandedAdapter(model=manifest['jev_model'],cache_dir=OUT/'cache')
    config=manifest['config']
    with store.use_store(OUT/'business.sqlite'),adapter.no_cache_write():
        for case in cases:
            receipt=OUT/(case['case_id']+'-scan.json')
            if receipt.exists():
                continue
            if case['eligibility']!='eligible':
                write(receipt,{'case_id':case['case_id'],'status':case['eligibility']})
                continue
            run_id=case['case_id']+'-detect'
            if store.load_artifact('expanded_detection_started',run_id) is not None:
                raise RuntimeError('unfinished detection requires inspection; do not silently repeat')
            store.save_artifact('expanded_detection_started',run_id,{'source_sha256':case['source_sha256']})
            pdf=PdfText(path=case['path'],text=case['text'],lines=case['lines'],page_count=case['page_count'],
                        text_source=case['text_source'],has_text_layer=case['text_source']=='pdf')
            detected=detect(adapter,pdf,case['path'],run_id=run_id,use_cache=False).model_dump(mode='json')
            result=run_learning(text=case['text'],directory=OUT,run_id=case['case_id']+'-baseline',adapter=adapter,
                config=config,proposals=ProposalBatch.model_validate(case['label_baseline']))['result']
            write(receipt,{'case_id':case['case_id'],'status':'completed','detection':detected,'baseline':result})
            print(case['case_id'],'scan',detected['doc_type'],len(result['points']),flush=True)


def generate():
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from jav.config import get_openai_key
    manifest,cases=check_frozen()
    approval=read(OUT/'openai_approval.json')
    if approval.get('sample_sha256')!=manifest['sample_sha256'] or approval.get('approved') is not True:
        raise RuntimeError('explicit OpenAI sample approval required')
    model=OpenAIChatModel(manifest['generator'],provider=OpenAIProvider(
        openai_client=AsyncOpenAI(api_key=get_openai_key(),max_retries=0,timeout=90)))
    adapter=ExpandedAdapter(model=manifest['jev_model'],cache_dir=OUT/'cache')
    for repeat in range(2):
        for case in cases:
            if case['eligibility']!='eligible' or (repeat and case['case_id'] not in manifest['repeat_cases']):
                continue
            run_id=f"{case['case_id']}-gen-{repeat}"
            receipt=OUT/(run_id+'.json')
            if receipt.exists():
                continue
            with store.use_store(OUT/'business.sqlite'):
                if store.load_artifact('learning_generation_started',run_id) is None:
                    enforce_cost('openai',manifest['openai_recorded_stop_usd'])
                    reserve_call(OUT/'generation_budget.sqlite',already_used=0,maximum=manifest['maximum_generation_calls'])
            started=time.perf_counter()
            kwargs=dict(text=case['text'],directory=OUT,run_id=run_id,adapter=adapter,model=model,config=manifest['config'])
            paused=run_learning(**kwargs,halt_after=['generate'])
            result=run_learning(**kwargs)['result']
            with store.use_store(OUT/'business.sqlite'):
                before=store.ledger_for_run(run_id)
                restored=run_learning(**kwargs)['result']
                assert restored==result and before==store.ledger_for_run(run_id)
            control_result=None
            if repeat:
                batch=ProposalBatch.model_validate(paused['proposals'])
                if batch.points:
                    control=batch.model_copy(update={'points':[batch.points[0].model_copy(update={'raw_value':'VALUE_NOT_STATED_928374'})]})
                    control_result=run_learning(text=case['text'],directory=OUT,run_id=run_id+'-control',adapter=adapter,
                        proposals=control,config=manifest['config'])['result']
            write(receipt,{'case_id':case['case_id'],'run_id':run_id,'repeat':repeat,'result':result,
                'control_result':control_result,'seconds':time.perf_counter()-started,'resume_exact':True})
            print(run_id,dict(Counter(p['verification']['status'] for p in result['points'])),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','ocr','freeze','scan','generate'])
    args=parser.parse_args()
    {'prepare':prepare,'ocr':prepare_ocr,'freeze':freeze,'scan':scan,'generate':generate}[args.mode]()
