"""032: new claim assessment with separate document/email budgets, without closed rounds."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from jav.config import PROJECT_ROOT
from jav.document_learning import digest
from jav.claim_assessment import prepare_packet, load_config, run_assessment
from jav.experiments.long_document_trial import TrialBudget, read, write, sha

DEFAULT_ROOT = PROJECT_ROOT / 'runs/20260921_claim_assessment'
LIMITS = {'openai': (12, .5), 'jev': (24, .125)}


def source(sid, text, status='read'):
    return dict(id=sid, text=text, sha256=digest(text), status=status)


def full_evidence(sources):
    return [dict(source_id=s['id'], start=0, quote=s['text']) for s in sources if s['text'] and s['status']=='read']


def prepare(root):
    if root.exists():
        raise ValueError('trial root already exists')
    config = load_config()
    specs = read(PROJECT_ROOT/'configs/experiments/claim_assessment_cases.json')
    cases = []
    for spec in specs['cases']:
        sources = [source('body' if spec['domain']=='email' else 'document', spec['text'])]
        if spec.get('missing_attachment'):
            sources.append(source('attachment', '', 'unread'))
        case = dict(case_id=spec['id'], sources=sources, target=spec['target'],
                    evidence=full_evidence(sources), source_complete=not spec.get('missing_attachment', False))
        cases.append(dict(case=case, domain=spec['domain'], split=spec['split'], expected=spec['expected'],
                          provenance='synthetic', authority=specs['authority']))

    old = PROJECT_ROOT/'runs/20260921_long_document_trial'
    frozen = {c['case_id']:c for c in read(PROJECT_ROOT/'runs/20260921_expanded_learning/frozen_inputs.json')}
    groups = read(old/'gold.json')['groups']
    for gid in ['expanded-048-amount-roles', 'bank-roles-boundary']:
        group = next(g for g in groups if g['id']==gid)
        original = frozen[group['case_id']]
        text = original['text']
        if digest(text) != original['source_sha256']:
            raise ValueError('original document hash mismatch')
        point = group['points'][0]['proposal']
        case = dict(case_id='new-status-'+group['case_id'], sources=[source('document', text)],
                    target=dict(role=point['role'], value=point['raw_value'], unit=point.get('unit'), entity=point.get('entity_id')),
                    evidence=[dict(source_id='document', start=a, quote=text[a:b]) for a,b in group['ranges']],
                    source_complete=False)
        cases.append(dict(case=case, domain='document', split='development',
                          expected=dict(role_match='matches', assertion_status='current'),
                          provenance='original_frozen_document_new_status_question', source_case_id=group['case_id'],
                          authority='assistant_source_diagnostic_not_human_gold'))

    emails = read(PROJECT_ROOT/'runs/20260921_email_learning/inputs.json')
    splits = read(PROJECT_ROOT/'runs/20260921_email_learning/splits.json')
    for cid, value, match in [('email-006','díjbekérő','matches'), ('email-007','végszámla','mismatches')]:
        old_case = next(c for c in emails if c['case_id']==cid)
        if splits[cid]['split'] != 'development':
            raise ValueError('old holdout cannot be used for development')
        sources = [source(s['id'],s['text'],s['status']) for s in old_case['sources']]
        for before, after in zip(old_case['sources'],sources):
            if before['sha256'] != after['sha256']:
                raise ValueError('original email hash mismatch')
        case = dict(case_id='new-role-'+cid, sources=sources,
                    target=dict(role='document currently sent with this message', value=value, unit=None, entity='current message'),
                    evidence=full_evidence(sources), source_complete=False)
        cases.append(dict(case=case, domain='email', split='development',
                          expected=dict(role_match=match, assertion_status='current' if match=='matches' else 'unknown'),
                          provenance='original_frozen_email_new_role_question', source_case_id=cid,
                          authority='assistant_source_diagnostic_not_human_gold', original_split=splits[cid]))
    for item in cases:
        prepare_packet(item['case'], config)
    root.mkdir(parents=True)
    write(root/'cases.json', cases)
    write(root/'config.json', config)
    write(root/'initial-preflight.json', {'pytest':'317 passed, 1 warning in 63.58s', 'contracts':5, 'external_calls':0})
    protected = {}
    for name in ['20260921_email_learning','20260921_long_document_trial','20260921_expanded_learning']:
        for p in sorted((PROJECT_ROOT/'runs'/name).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:
                protected[p.relative_to(PROJECT_ROOT).as_posix()] = sha(p)
    write(root/'protected.json', protected)
    frozen = {name:sha(root/name) for name in ['cases.json','config.json','protected.json']}
    write(root/'frozen.json', frozen)
    write(root/'request.json', {'approved':False, 'frozen_sha256':sha(root/'frozen.json'),
          'limits':{domain:LIMITS for domain in ['document','email']},
          'scope':'14 new claim assessments: 10 synthetic, 2 existing documents, 2 existing development emails; no old measurement replay',
          'data_permission':'User instruction and modified handoff 031: OpenAI and JEV authorized',
          'budget_permission':'pending concrete new numerical caps; old budgets untouched'})
    print(json.dumps({'prepared':str(root),'cases':len(cases),'protected_files':len(protected),'budget':'pending'}),flush=True)


def validate(root, *, require_approval=True):
    for name, expected in read(root/'frozen.json').items():
        if sha(root/name) != expected:
            raise ValueError('frozen input changed: '+name)
    if require_approval:
        if not (root/'approval.json').exists():
            raise ValueError('specific trial budget approval required; see request.json')
        approval = read(root/'approval.json')
        expected_limits = {domain:{p:list(v) for p,v in LIMITS.items()} for domain in ['document','email']}
        if (approval.get('approved') is not True or approval.get('frozen_sha256') != sha(root/'frozen.json')
                or approval.get('limits') != expected_limits
                or approval.get('request_sha256') != sha(root/'request.json')):
            raise ValueError('specific trial budget approval required')
    for relative, expected in read(root/'protected.json').items():
        if sha(PROJECT_ROOT/relative) != expected:
            raise ValueError('protected historical evidence changed: '+relative)
    return read(root/'cases.json'),read(root/'config.json')


def services(root, config):
    from typesafe_sdk import RetryPolicy
    from jav.config import get_openai_key, make_client
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.models.wrapper import WrapperModel
    from jav.adapters.jev import JevAdapter
    budget = TrialBudget(root, LIMITS)
    class BoundedModel(WrapperModel):
        async def request(self, *args, **kwargs):
            budget.reserve('openai')
            return await super().request(*args, **kwargs)
    class BoundedJev(JevAdapter):
        def _live(self, *args, **kwargs):
            budget.reserve('jev')
            return super()._live(*args, **kwargs)
    model = BoundedModel(OpenAIChatModel(config['openai_model'], provider=OpenAIProvider(
        openai_client=AsyncOpenAI(api_key=get_openai_key(), max_retries=0, timeout=90))))
    adapter = BoundedJev(client=make_client(retry=RetryPolicy(max_retries=0)),
                         model=config['jev_model'], cache_dir=root/'cache')
    return model,adapter,budget


def snapshot(root):
    manifest = root/'source-snapshot.json'
    if manifest.exists():
        for name,expected in read(manifest).items():
            if sha(PROJECT_ROOT/name) != expected:
                raise ValueError('source changed; use a new trial identity')
        return
    paths = sorted((PROJECT_ROOT/'jav').rglob('*.py')) + [PROJECT_ROOT/'tests/test_claim_assessment.py']
    for path in paths:
        dest = root/'source_snapshot'/path.relative_to(PROJECT_ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path,dest)
    write(manifest,{p.relative_to(PROJECT_ROOT).as_posix():sha(p) for p in paths})


def run(root, domain, split):
    cases,config = validate(root)
    snapshot(root)
    model,adapter,budget = services(root/domain,config)
    for item in cases:
        if item['domain'] != domain or item['split'] != split:
            continue
        cid = item['case']['case_id']
        path = root/domain/(cid+'.json')
        if path.exists():
            continue
        result = run_assessment(case=item['case'], directory=root/domain/cid, run_id=cid,
                                model=model, adapter=adapter, config=config)
        write(path,result)
        print(json.dumps({'case':cid,'openai':result['openai'],'jev':result['jev'],
                          'review_noul':result['jev_review']['noul'],'budget':budget.usage()}),flush=True)


def report(root):
    """Agreement with the expectation, not human-verified accuracy; from the raw independent answers."""
    import sqlite3
    from contextlib import closing
    cases,config = validate(root, require_approval=False)
    rows = []
    for item in cases:
        cid = item['case']['case_id']
        path = root/item['domain']/(cid+'.json')
        if not path.exists():
            continue
        result = read(path)
        row = {k:item[k] for k in ['domain','split','provenance','authority','expected']}
        row.update(case_id=cid, openai=result['openai'], jev=result['jev'], agreement=result['agreement'],
                   jev_review_noul=result['jev_review']['noul'], review_reasons=result['review_reasons'],
                   correctness=result['correctness'], covered_chars=result['packet']['coverage']['covered_chars'])
        for provider in ['openai','jev']:
            row[provider+'_exact'] = result[provider] == item['expected']
            row[provider+'_false_current'] = (result[provider]['assertion_status']=='current'
                                             and item['expected']['assertion_status']!='current')
        row['agreement_wrong'] = row['agreement'] and not row['openai_exact']
        with closing(sqlite3.connect((root/item['domain']/cid/'business.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as db:
            row['accounting'] = {step:dict(calls=count,usd=round(cost,6),seconds=round(seconds,3))
                for step,count,cost,seconds in db.execute(
                    'SELECT step,count(*),sum(cost_usd),sum(seconds) FROM ledger GROUP BY step')}
        rows.append(row)
    totals = {domain:TrialBudget(root/domain,LIMITS).usage() for domain in ['document','email']}
    analysis = {'cases_planned':len(cases),'cases_completed':len(rows),'rows':rows,'budgets':totals,
                'external_truth':'not_established','old_evidence_files_unchanged':len(read(root/'protected.json'))}
    write(root/'analysis.json',analysis)
    print(json.dumps({k:v for k,v in analysis.items() if k!='rows'}),flush=True)


def replay(root):
    from contextlib import nullcontext
    cases, config = validate(root)
    class NoModel:
        system='openai'
        model_name=config['openai_model']
    class NoAdapter:
        model=config['jev_model']
        def no_cache_write(self): return nullcontext()
        def ask(self,*args,**kwargs): raise AssertionError('replay attempted external call')
    replayed=[]
    for item in cases:
        cid=item['case']['case_id']
        path=root/item['domain']/(cid+'.json')
        if not path.exists(): continue
        actual=run_assessment(case=item['case'],directory=root/item['domain']/cid,run_id=cid,
                              model=NoModel(),adapter=NoAdapter(),config=config)
        if actual != read(path): raise AssertionError('terminal result changed')
        replayed.append(cid)
    write(root/'replay.json', {'exact_cases':replayed,'external_calls':0,'method':'no callable external model or adapter'})
    print('Exact terminal replay:',len(replayed),'External calls: 0',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','validate','run','report','replay'])
    parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--domain',choices=['document','email'],default='document')
    parser.add_argument('--split',choices=['development','holdout'],default='development')
    args=parser.parse_args()
    if args.command=='prepare': prepare(args.root)
    elif args.command=='validate':
        validate(args.root,require_approval=False)
        print('Frozen inputs and historical evidence unchanged.')
    elif args.command=='report': report(args.root)
    elif args.command=='replay': replay(args.root)
    else: run(args.root,args.domain,args.split)


if __name__=='__main__':
    main()
