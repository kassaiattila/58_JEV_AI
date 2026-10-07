"""Local summary of the closed matter-link trials, keeping the source identifiers."""
import json
import sqlite3
import statistics
from contextlib import closing
from jav.config import PROJECT_ROOT
from jav.experiments.long_document_trial import read, write, sha

OUT = PROJECT_ROOT/'runs/20260922_legacy_capabilities'


def summarize(rows, key):
    errors = [r['case_id'] for r in rows if r['state']['result'][key] not in (r['expected'], 'review')]
    decided = [r for r in rows if r['state']['result'][key] != 'review']
    return {'total': len(rows), 'decided': len(decided), 'review': len(rows)-len(decided),
        'exact': sum(r['state']['result'][key] == r['expected'] for r in rows),
        'false_link': sum(r['expected']=='none' and r['state']['result'][key] not in ('none','review') for r in rows),
        'missed_link': sum(r['expected']!='none' and r['state']['result'][key]=='none' for r in rows),
        'errors': errors}


def ledger(root):
    rows = []
    for path in root.rglob('business.sqlite'):
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            rows.extend(dict(r) for r in db.execute('SELECT * FROM ledger WHERE cached=0'))
    return rows


def main():
    full = PROJECT_ROOT/'runs/20260922_matter_trial_v2'
    mini = PROJECT_ROOT/'runs/20260922_matter_minimal'
    collections = {name: [read(p) for p in sorted((root/'results').glob('*.json'))]
                   for name,root in [('legacy_prompt',full),('minimal_prompt',mini)]}
    assert all(len(rows)==42 for rows in collections.values())
    result = {'label_authority': 'legacy synthetic fixtures and assistant predeclared synthetic controls; not independent human gold',
              'arms': {}, 'cost_latency': {}, 'source_hashes': {}}
    for name,rows in collections.items():
        keys = ['gpt_relation','hybrid_relation'] + (['jev_relation','jev_guarded_relation'] if name=='legacy_prompt' else [])
        for key in keys:
            arm = {}
            for repeat in (0,1):
                for split in ('all','legacy_regression','new_control'):
                    selected = [r for r in rows if r['repeat']==repeat and (split=='all' or r['split']==split)]
                    arm[f'{split}_repeat_{repeat}'] = summarize(selected,key)
            first = {r['case_id']:r for r in rows if r['repeat']==0}
            arm['changed_between_repeats'] = sum(r['state']['result'][key] != first[r['case_id']]['state']['result'][key]
                                                for r in rows if r['repeat']==1)
            result['arms'][name+':'+key] = arm
    for name,root,provider in [('gpt_legacy',full,'openai'),('jev_typed',full,'jev'),('gpt_minimal',mini,'openai')]:
        rows = [r for r in ledger(root) if r['provider']==provider]
        assert len(rows)==42 and all(not r['error'] and r['cost_usd'] is not None for r in rows)
        times = [r['seconds'] for r in rows]
        result['cost_latency'][name] = {'calls':len(rows),'usd':round(sum(r['cost_usd'] for r in rows),6),
            'mean_seconds':statistics.mean(times),'median_seconds':statistics.median(times),
            'input_tokens':sum(r['input_tokens'] for r in rows),'output_tokens':sum(r['output_tokens'] for r in rows),
            'models':sorted({r['model'] for r in rows})}
    result['latency_scope'] = 'GPT: typed agent wall time incl output validation; JEV: adapter SDK wall time. Sequential calls, no concurrency/load test.'
    result['label_ambiguity'] = {'case_id':'synthetic-same_case_event_support',
        'frozen_expected':'same_case','observed_all_arms':'same_thread',
        'note':'Legacy prompt says choose most specific relation and includes request/answer under same_thread. Frozen label kept; requires independent rubric adjudication.'}
    for root in (full,mini):
        for p in [root/'config.json',root/'cases.json',root/'replay.json',root/'usage.json',*sorted((root/'results').glob('*.json'))]:
            result['source_hashes'][str(p.relative_to(PROJECT_ROOT))] = sha(p)
    write(OUT/'matter-analysis.json',result)
    old = read(PROJECT_ROOT/'runs/20260922_stack_comparison/accounting.json')
    accounting = {'providers': {}, 'prior_accounting':old, 'new_runs':['20260922_matter_trial_v2','20260922_matter_minimal'],
                  'unknown_attempts':['20260921_claim_assessment/document/doc-current','20260922_matter_trial/synthetic-invoice_order_po-0'],
                  'cost_basis':'configured token prices, not provider billing invoice'}
    for provider in ('openai','jev'):
        rows = [r for root in (full,mini) for r in ledger(root) if r['provider']==provider]
        usd = round(old['providers'][provider]['recorded_usd']+sum(r['cost_usd'] for r in rows),6)
        reserve = .75 if provider=='openai' else 0
        accounting['providers'][provider] = {'successful_calls':old['providers'][provider]['successful_calls']+len(rows),
            'recorded_usd':usd,'authorized_usd':5,'uncertain_attempts':2 if provider=='openai' else 0,
            'uncertainty_reserve_usd':reserve,'available_after_reserve_usd':round(5-usd-reserve,6)}
    write(OUT/'accounting.json',accounting)
    print(json.dumps({'cost_latency':result['cost_latency'],'accounting':accounting['providers']},indent=2))


if __name__ == '__main__':
    main()
