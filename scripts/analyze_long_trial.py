"""Summary without any calls. Raw match and the role-bound golden set are reported separately."""
import json
import argparse
from collections import Counter
from decimal import Decimal
from pathlib import Path
from jav.experiments.long_document_trial import OUT,read,write,validate,TrialBudget
from jav.document_learning import digest

gold=read(OUT/'gold.json')

def normalized(value):
    # Only for comparing the money values of this frozen golden set; not a production normaliser.
    return value.replace(' ','').replace('$','').replace(',','.')

def expected_target(group,target):
    name=target['name']
    if name=='current_payable':
        return '27 000' if group['id']=='remote-corrected' else None
    values=[p['proposal']['raw_value'] for p in group['points'] if p['proposal']['name']==name and p['expected']=='supported']
    return values[0] if values else None

def score_targets(group,points):
    rows=[]
    for target in group['targets']:
        expected=expected_target(group,target)
        found=[p for p in points if p['proposal']['name']==target['name']]
        matches=[]
        for p in found:
            actual=p['proposal']['raw_value']
            match=expected is not None and normalized(actual)==normalized(expected)
            if target['name']=='water_supplier' and expected is not None:
                match=actual in ('Fővárosi Vízművek','Fővárosi Vízművek Zártkörűen Működő Részvénytársaság')
            matches.append(match)
        rows.append(dict(group_id=group['id'],name=target['name'],provenance=group['provenance'],
            expected=expected,present=len(found),correct_value=any(matches),
            strict_raw_match=expected is not None and any(p['proposal']['raw_value']==expected for p in found),
            supported_correct=any(m and p['verification']['status']=='supported' for m,p in zip(matches,found)),
            absent_correct=expected is None and not found,
            emitted=[{'raw_value':p['proposal']['raw_value'],'role':p['proposal']['role'],
                      'status':p['verification']['status'],'quote':p['proposal']['quote']} for p in found]))
    return rows

def summarize(stage, final=False):
    assertions=[]; targets=[]
    for group in gold['groups']:
        suffix='-probes.json' if stage=='baseline-v2' else '.json'
        path=OUT/stage/(group['id']+suffix)
        if not path.exists():
            continue
        result=read(path)
        checked=result['checked']['points']
        gen=result['generated']['points']
        if final and (OUT/'repair-v2'/(group['id']+'.json')).exists():
            gen=read(OUT/'repair-v2'/(group['id']+'.json'))['generated']['points']
        for label,p in zip(group['points'],checked):
            expected=label['expected']; actual=p['verification']['status']
            assertions.append(dict(group_id=group['id'],name=p['proposal']['name'],
                provenance=group['provenance'],expected=expected,actual=actual,exact=expected==actual,
                false_support=expected!='supported' and actual=='supported'))
        targets.extend(score_targets(group,gen))
    real=[r for r in assertions if r['provenance']=='original_frozen_text']
    real_targets=[r for r in targets if r['provenance']=='original_frozen_text']
    positive=[r for r in real_targets if r['expected'] is not None]
    missing=[r for r in real_targets if r['expected'] is None]
    return dict(assertions=assertions,targets=targets,
        real_assertions=len(real),exact_real_assertions=sum(r['exact'] for r in real),
        false_supports=sum(r['false_support'] for r in real),
        real_target_present=len(positive),real_target_value_matches=sum(r['correct_value'] for r in positive),
        real_target_raw_matches=sum(r['strict_raw_match'] for r in positive),
        real_target_supported_correct=sum(r['supported_correct'] for r in positive),
        missing_fields=len(missing),missing_correctly_omitted=sum(r['absent_correct'] for r in missing),
        real_statuses=dict(Counter(r['actual'] for r in real)))

coverage=[];points=[]
for cid in ('expanded-048','expanded-049','expanded-059'):
    d=read(OUT/'baseline-v2'/(cid+'.json'))
    coverage.append({'case_id':cid,**d['coverage']})
    points.extend(d['points'])
parser=argparse.ArgumentParser()
parser.add_argument('--final',action='store_true')
args=parser.parse_args()
result=dict(coverage=coverage,generated_points=len(points),
    generated_statuses=dict(Counter(e['point']['verification']['status'] for p in points for e in p['evidence'])),
    baseline=summarize('baseline-v2'),repair=summarize('repair-v1',final=args.final),usage=TrialBudget(OUT).usage(),
    protected_unchanged=bool(validate()),
    caveat='Target names bind requested roles; listed emitted roles and quotes separately reviewed by assistant. No human-certified gold or whole-document precision.')
output=OUT/('analysis-final.json' if args.final else 'analysis.json')
if output.exists():
    raise RuntimeError('analysis already frozen; choose a new version')
write(output,result)
print(json.dumps({k:v for k,v in result.items() if k not in ('baseline','repair')},indent=2))
for stage in ('baseline','repair'):
    print(stage,json.dumps({k:v for k,v in result[stage].items() if k not in ('assertions','targets')},indent=2))
