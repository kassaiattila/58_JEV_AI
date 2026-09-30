"""Re-checks only the three newly uncovered exact-context errors, with zero GPT calls."""
from jav.experiments.long_document_trial import *
from jav.evidence_learning import build_bundle,run_evidence_learning
from jav.document_learning import check_proposals

cases={c['case_id']:c for c in validate()}
root=OUT/'repair-v2'
snapshot('repair-v2')
group=next(g for g in read(OUT/'gold.json')['groups'] if g['id']=='expanded-048-amount-roles')
prior=read(OUT/'repair-v1'/(group['id']+'.json'))
source=cases[group['case_id']]['text'];spans=group['ranges']
bundle=build_bundle(source,spans,source_sha256=digest(source))
config=read(OUT/'repair-v1/config.json')|{'expand_exact_context':True}
write(root/'config.json',config)
batch=ProposalBatch(source_sha256=digest(bundle['text']),points=[p['proposal'] for p in prior['generated']['points']])
model,adapter,budget=services()
kwargs=dict(text=source,spans=spans,source_sha256=digest(source),directory=root/'runs',run_id='exact-context-expansion',
            adapter=adapter,config=config,proposals=batch,source_char_limit=50000)
result=run_evidence_learning(**kwargs)
before=budget.usage()
assert run_evidence_learning(**kwargs)==result and before==budget.usage()
write(root/(group['id']+'.json'),{'group_id':group['id'],'generated':result,
    'prior':'repair-v1/'+group['id']+'.json','terminal_replay_exact':True,'new_gpt_calls':0})
# Local, typed check of the model proposal that really was wrong.
original=read(OUT/'baseline-v2/receipt-repeated-missing-probes.json')
bad=next(p['proposal'] for p in original['generated']['points'] if p['proposal']['name']=='vat_amount')
receipt_source=cases['expanded-005']['text']
def forbidden(*args):
    raise AssertionError('invalid amount reached provider')
rejected=check_proposals(receipt_source,ProposalBatch(source_sha256=digest(receipt_source),points=[bad]),forbidden,config)
assert rejected.points[0].verification['status']=='invalid_value'
write(root/'real-vat-identifier-rejection.json',rejected.model_dump(mode='json'))
write(root/'complete.json',{'usage':budget.usage(),'protected_unchanged':bool(validate()),
    'fixed_statuses':[p['verification']['status'] for p in result['points']]})
print(read(root/'complete.json'))
