"""Targeted repair round within the same new budget; the original results stay unchanged."""
import json
from jav.experiments.long_document_trial import (OUT,PROJECT_ROOT,read,write,validate,snapshot,services)
from jav.document_learning import ProposalBatch,PointProposal,digest
from jav.evidence_learning import build_bundle,run_evidence_learning

cases={c['case_id']:c for c in validate()}
config=read(OUT/'config.json')
revision=read(PROJECT_ROOT/'configs/experiments/evidence_learning.json')
config['proposal_instructions']=revision['proposal_instructions']
config['field_patterns']={name:revision['money_pattern'] for name in revision['money_fields']}
config['evidence_revision']=revision['version']
root=OUT/'repair-v1'
if not (root/'config.json').exists():
    write(root/'config.json',config)
else:
    assert read(root/'config.json')==config
snapshot('repair-v1')
model,adapter,budget=services()
for group in read(OUT/'gold.json')['groups']:
    receipt=root/(group['id']+'.json')
    if receipt.exists():
        continue
    source=cases[group['case_id']]['text']
    spans=[tuple(x) for x in group['ranges']]
    if group['appended_text']:
        old_length=len(source)
        source+=group['appended_text']
        spans.append((old_length,len(source)))
    bundle=build_bundle(source,spans,source_sha256=digest(source))
    points=[PointProposal.model_validate(x['proposal']) for x in group['points']]
    batch=ProposalBatch(source_sha256=digest(bundle['text']),points=points)
    kwargs=dict(text=source,spans=spans,source_sha256=digest(source),directory=root/'runs',
                adapter=adapter,config=config,source_char_limit=50000)
    checked=run_evidence_learning(**kwargs,run_id=group['id']+'-checked',proposals=batch)
    targeted=config | {'proposal_instructions':config['proposal_instructions']+' Requested fields: '+json.dumps(group['targets'],ensure_ascii=False)}
    generated=run_evidence_learning(**(kwargs|{'config':targeted}),run_id=group['id']+'-gen',model=model)
    before=budget.usage()
    restored=run_evidence_learning(**(kwargs|{'config':targeted}),run_id=group['id']+'-gen',model=model)
    assert restored==generated and budget.usage()==before
    write(receipt,dict(group_id=group['id'],provenance=group['provenance'],
                      checked=checked,generated=generated,terminal_replay_exact=True,usage=before))
    print(group['id'],[p['verification']['status'] for p in checked['points']],
          'generated',[(p['proposal']['name'],p['verification']['status']) for p in generated['points']],
          budget.usage(),flush=True)
write(root/'complete.json',{'usage':budget.usage(),'protected_unchanged':bool(validate()),'groups':8})
