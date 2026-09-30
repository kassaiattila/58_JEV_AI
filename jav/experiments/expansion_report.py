"""Saved-evidence analysis; no provider calls and no human labels inferred."""
from collections import Counter, defaultdict
from contextlib import closing
import sqlite3
from jav.experiments.expansion_trial import ROOT, LIMITS, validate
from jav.experiments.long_document_trial import read, write, TrialBudget, sha
from jav.config import PROJECT_ROOT


def label(row, arm):
    return row[arm]['output']['intent'] if arm == 'gpt' else row[arm]['intent']


def main(expected_documents=12, suffix=''):
    validate()
    files = sorted((ROOT/'email_results').glob('*.json'))
    emails = [read(p) for p in files]
    originals = [r for r in emails if r['repeat'] == 0]
    fresh = [r for r in originals if r['kind'] == 'fresh_unlabelled']
    controls = [r for r in originals if r['kind'] == 'synthetic_control']
    arms = ['baseline', 'expanded', 'gpt']
    initial = {r['case_id']:r for r in originals}
    repeats = [r for r in emails if r['repeat'] != 0]
    docs = [read(p) for p in sorted((ROOT/'document_results').glob('*.json'))]
    assert len(fresh)==60 and len(controls)==11 and len(repeats)==6 and len(docs)==expected_documents
    mismatches = [{'case_id':r['case_id'], **{a:label(r,a) for a in arms}}
                  for r in fresh if len({label(r,a) for a in arms})>1]
    costs = defaultdict(lambda: {'calls':0,'usd':0.,'seconds':0.})
    models = Counter()
    for path in ROOT.rglob('business.sqlite'):
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            rows = db.execute('SELECT step,provider,model,cost_usd,seconds,error FROM ledger WHERE cached=0').fetchall()
        for step,provider,model,cost,seconds,error in rows:
            assert error is None and cost is not None
            key = ('email' if 'emails' in path.parts else 'document')+'/'+provider
            item = costs[key]; item['calls']+=1;item['usd']+=cost;item['seconds']+=seconds
            models[provider+'/'+str(model)]+=1
    for row in costs.values():
        row['usd']=round(row['usd'],6)
        row['mean_seconds']=round(row['seconds']/row['calls'],3)
        row['seconds']=round(row['seconds'],3)
    document_summary=[]
    for row in docs:
        result=row['state']['result']
        document_summary.append({'id':row['case_id'],'kind':row['kind'],
            'exact_fixture_match':row['exact_fixture_match'],'valid':result['validation']['valid'],
            'validation_flags':result['validation'].get('flags',[]),
            'extracted_leaves':result['non_null_leaves'],'verified_leaves':result['verified_leaves'],
            'support_min':min((p['support'] for p in result['field_verification']),default=None),
            'support_below_0_8_diagnostic_only':sum(p['support']<.8 for p in result['field_verification'])})
    cases=read(ROOT/'emails.json')
    summary={'human_gold':False,'fresh_count':len(fresh),'synthetic_count':len(controls),
        'planned_documents':12,'completed_documents':len(docs),
        'unrun_document_ids':sorted({c['id'] for c in read(ROOT/'documents.json')}-{r['case_id'] for r in docs}),
        'synthetic_matches':{a:sum(label(r,a)==r['expected'] for r in controls) for a in arms},
        'synthetic_mismatches':[{ 'id':r['case_id'],'expected':r['expected'],**{a:label(r,a) for a in arms}}
                                for r in controls if any(label(r,a)!=r['expected'] for a in arms)],
        'fresh_distributions':{a:dict(Counter(label(r,a) for r in fresh)) for a in arms},
        'fresh_pair_agreement':{a+'/'+b:sum(label(r,a)==label(r,b) for r in fresh)
                                for a,b in [('baseline','expanded'),('baseline','gpt'),('expanded','gpt')]},
        'fresh_disagreements':mismatches,
        'repeat_changes':{a:sum(label(r,a)!=label(initial[r['case_id']],a) for r in repeats) for a in arms},
        'coverage':{'truncated_bodies':sum(r['coverage']['body_truncated'] for r in fresh),
            'attachment_content_read':False,
            'emails_with_attachment_names':sum(bool(r['message']['attachments']) for r in cases if r['kind']=='fresh_unlabelled')},
        'documents':document_summary,'costs':dict(costs),'models':dict(models),
        'limits':'agreement is not accuracy; fixture transport is not natural document extraction accuracy; support does not establish completeness',
        'result_hashes':{str(p.relative_to(ROOT)):sha(p) for p in files+sorted((ROOT/'document_results').glob('*.json'))}}
    usage=TrialBudget(ROOT,LIMITS).usage()
    prior=read(PROJECT_ROOT/'runs/20260922_legacy_capabilities/accounting.json')
    providers={}
    for p,row in usage.items():
        assert row['reserved']==row['logged'] and row['errors']==0
        old=prior['providers'][p]; recorded=round(old['recorded_usd']+row['usd'],6)
        providers[p]={'successful_calls':old['successful_calls']+row['logged'],'recorded_usd':recorded,
            'authorized_usd':5,'uncertain_attempts':old['uncertain_attempts'],
            'uncertainty_reserve_usd':old['uncertainty_reserve_usd'],
            'available_after_reserve_usd':round(5-recorded-old['uncertainty_reserve_usd'],6)}
    write(ROOT/('analysis'+suffix+'.json'),summary)
    write(ROOT/('accounting'+suffix+'.json'),{'providers':providers,'this_run':usage,
        'prior_accounting':'runs/20260922_legacy_capabilities/accounting.json',
        'prior_sha256':sha(PROJECT_ROOT/'runs/20260922_legacy_capabilities/accounting.json'),
        'unknown_attempts':prior['unknown_attempts'],'cost_basis':prior['cost_basis']})
    print({k:v for k,v in summary.items() if k!='result_hashes'})
    print(providers)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--expected-documents',type=int,choices=[10,12],default=12)
    parser.add_argument('--suffix',choices=['','-v2'],default='')
    args=parser.parse_args()
    main(args.expected_documents,args.suffix)
