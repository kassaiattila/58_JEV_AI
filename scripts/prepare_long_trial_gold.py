"""A diagnostic golden set recorded from the document reading before any model answers; PII only under runs."""
from jav.experiments.long_document_trial import OUT, write, sha, validate
from jav.document_chunks import plan_document, ChunkPolicy, load_chunk_config
from jav.models import LineLayout

cases = {c['case_id']:c for c in validate()}
groups = []

def point(name, role, value, quote, expected='supported', unit=None, entity=None):
    return {'proposal':dict(name=name,role=role,raw_value=value,quote=quote,unit=unit,entity_id=entity),
            'expected':expected}

def add(cid, name, ranges, points, targets, derived_suffix=''):
    c = cases[cid]
    context = '\n\n'.join(c['text'][a:b] for a,b in ranges)+derived_suffix
    assert len(context)<=8000
    assert all(p['proposal']['quote'] in context for p in points)
    groups.append(dict(id=name,case_id=cid,ranges=ranges,text=context,points=points,targets=targets,
        provenance='controlled_counterfactual' if derived_suffix else 'original_frozen_text',
        appended_text=derived_suffix))

amounts = [('expanded-048','26 766','9011','14 489','FVV/19854820'),
           ('expanded-049','7 476','7917','12 583','FVV/21516301'),
           ('expanded-059','26 766','9011','14 489','FVV/19001949')]
for cid, total, water, sewer, invoice in amounts:
    c = cases[cid]
    plan = plan_document(c['text'],ChunkPolicy.model_validate(load_chunk_config()['chunk_policy']),
        layout=[LineLayout.model_validate(r) for r in c['layout']])
    pages = {x.page:x for x in plan.chunks}
    text = c['text']
    total_quote = next(s for s in text[:pages[1].end].splitlines() if 'Fizetendő ' in s)
    wquote = next(s for s in text[pages[4].start:pages[4].end].splitlines() if s.startswith('Fizetendő összeg'))
    squote = next(s for s in text[pages[7].start:pages[7].end].splitlines() if s.startswith('Fizetendő összeg'))
    points = [point('bundle_payable','amount payable for the entire collection summary, not one component invoice',total,total_quote,unit='HUF'),
              point('water_payable','amount payable for water invoice '+invoice,water,wquote,unit='HUF'),
              point('sewer_payable','amount payable for the sewer invoice, not water or collection summary',sewer,squote,unit='HUF'),
              point('wrong_bundle','amount payable for the entire collection summary, not one component invoice',water,wquote,'contradicted',unit='HUF'),
              point('wrong_water','amount payable for water invoice '+invoice,sewer,squote,'contradicted',unit='HUF')]
    add(cid,cid+'-amount-roles',[(pages[i].start,pages[i].end) for i in (1,4,7)],points,
        [{'name':p['proposal']['name'],'role':p['proposal']['role']} for p in points[:3]])
    if cid == 'expanded-048':
        add(cid,'water-cross-page',[(pages[3].start,pages[4].end)],
            [point('water_supplier','supplier of invoice '+invoice,'Fővárosi Vízművek', 'Fővárosi Vízművek'),
             point('water_payable','amount payable for water invoice '+invoice,water,wquote,unit='HUF'),
             point('wrong_supplier','supplier of invoice '+invoice,'MOHU MOL',wquote,'contradicted')],
            [{'name':'water_supplier','role':'supplier of invoice '+invoice},
             {'name':'water_payable','role':'amount payable for water invoice '+invoice}])
        for kind,suffix in [('corrected','\n\nControlled test amendment. The earlier collection-summary payable amount of 26 766 HUF is cancelled. The corrected current collection-summary payable amount is 27 000 HUF.'),
                            ('conflict','\n\nControlled test statement: the collection-summary amount payable is 27 000 HUF. This statement does not specify which of the two amounts takes precedence.')]:
            add(cid,'remote-'+kind,[(0,pages[1].end)],
                [point('old_current','current collection-summary amount payable','26 766',total_quote,
                       'contradicted' if kind=='corrected' else 'review_required',unit='HUF'),
                 point('new_current','current collection-summary amount payable','27 000','27 000 HUF',
                       'supported' if kind=='corrected' else 'review_required',unit='HUF')],
                [{'name':'current_payable','role':'current collection-summary amount payable after considering all amendments or contradictions; omit if unresolved'}],suffix)

c = cases['expanded-043']; t=c['text']
bankpoints = [
    point('closing_balance','closing balance of the EUR account','265,86','ZÁRÓ EGYENLEG:   265,86',unit='EUR'),
    point('available_balance','available balance of the EUR account','265,86','ELÉRHETŐ EGYENLEG:   265,86',unit='EUR'),
    point('wrong_opening','opening balance of the EUR account','265,86','ZÁRÓ EGYENLEG:   265,86','contradicted',unit='EUR'),
    point('terms_effective','effective date of the amendment to the Bankszámlákra és Fizetési Műveletekre vonatkozó különös Üzletszabályzat Fogyasztók és Egyéni Vállalkozók részére','2026. október 1.','elnevezésű dokumentumot 2026. október 1. napi hatállyal módosítja.'),
    point('wrong_effective','effective date of the amendment to the bank account terms','2026. július 31.','2026. július 31.','contradicted'),
    point('missing_invoice','invoice number for the bank account statement','INV-NOT-STATED-030','BANKSZÁMLA KIVONAT','unsupported')]
add(c['case_id'],'bank-roles-boundary',[(0,len(t))],bankpoints,
    [{'name':p['proposal']['name'],'role':p['proposal']['role']} for p in (bankpoints[0],bankpoints[1],bankpoints[3],bankpoints[5])])
c=cases['expanded-005'];t=c['text']
add(c['case_id'],'receipt-repeated-missing',[(0,len(t))],
    [point('receipt_total','total receipt amount','97.13','TOTAL AMOUNT:   $97.13',unit='USD'),
     point('amount_due','amount due as literally stated on this receipt','97.13','Amount due   97.13',unit='USD'),
     point('wrong_vat','VAT amount charged on the receipt','97.13','TOTAL AMOUNT:   $97.13','unsupported',unit='USD'),
     point('missing_iban','supplier IBAN','HU001234567890','Upwork Global Inc.','unsupported'),
     point('ambiguous_total','total receipt amount','97.13','97.13','ambiguous_quote',unit='USD')],
    [{'name':'receipt_total','role':'total receipt amount'}, {'name':'amount_due','role':'amount due as literally stated'},
     {'name':'vat_amount','role':'explicit VAT amount, omit if absent'}, {'name':'supplier_iban','role':'supplier IBAN, omit if absent'}])
write(OUT/'gold.json',{'authority':'assistant source-reading labels, fixed before new model calls; not human certified',
    'source_truth':'frozen extracted text, not rendered PDF; no OCR correctness claim',
    'groups':groups})
write(OUT/'frozen.json',{p.name:sha(p) for p in [OUT/'inputs.json',OUT/'gold.json',OUT/'config.json',OUT/'approval.json']})
print('frozen groups',len(groups),'assertions',sum(len(g['points']) for g in groups))
