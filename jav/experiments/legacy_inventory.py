"""Read-only inventory of the legacy project's on-disk state; it does not claim live DB activation."""
from __future__ import annotations

import ast
import re
from jav.config import OLD_PROJECT_ROOT, PROJECT_ROOT
from jav.experiments.long_document_trial import read, write, sha


def inventory(old=OLD_PROJECT_ROOT, current=PROJECT_ROOT):
    flow_root = old/'flows'
    source_hashes = {}
    def record(path):
        source_hashes[str(path)] = sha(path)
        return path
    flows = []
    for path in sorted(flow_root.glob('*/flow.py')):
        tree = ast.parse(record(path).read_text(encoding='utf-8-sig'))
        contract = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(n, ast.Name) and n.id=='CONTRACT' for n in node.targets):
                try:
                    contract = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
        manifests = []
        for p in sorted(path.parent.glob('golden/manifest*.json')):
            data = read(record(p))
            manifests.append({'path': str(p), 'inline_cases': len(data.get('cases', [])),
                              'cases_ref': data.get('cases_ref'), 'data_dir': data.get('data_dir')})
        flows.append({'flow': path.parent.name, 'source': str(path), 'description': ast.get_docstring(tree),
                      'contract': contract, 'manifests': manifests})
    catalog = record(flow_root/'registry/DOCTYPES.md').read_text(encoding='utf-8')
    active = re.search(r'^## Active[^\n]*\n(.*?)(?=^## |\Z)', catalog, re.M | re.S)
    if active is None:
        raise ValueError('active document section missing')
    active_keys = set(re.findall(r'\*\*`([^`]+)`\*\*', active.group(1)))
    mapping = read(record(current/'configs/doc_types.json'))
    packs = {p.stem for p in (current/'configs/types').glob('*.json')}
    types = []
    for p in sorted((flow_root/'doc-extract-bare/types').glob('*/schema.json')):
        schema = read(record(p))
        types.append({'key': p.parent.name, 'legacy_catalog_active': p.parent.name in active_keys,
                      'current_detection_key': mapping['old_type_map'].get(p.parent.name),
                      'current_extraction_pack': p.parent.name in packs,
                      'fields': list(schema.get('properties', {})),
                      'fixtures': [str(x) for x in sorted(p.parent.glob('fixtures/*.json'))],
                      'source': str(p)})
    old_intents = read(record(flow_root/'registry/intent_types.json'))['rows']
    new_intents = read(record(current/'configs/intents.json'))['intents']
    old_active = {r['intent_key'] for r in old_intents if r['active']}
    new_keys = {r['key'] for r in new_intents}
    return {'scope': 'committed/local disk, not runtime DB or deployment verification',
            'flows': flows, 'document_types': types,
            'intents': {'legacy_active': sorted(old_active), 'current': sorted(new_keys),
                        'missing_active': sorted(old_active-new_keys),
                        'legacy_retired': [r['intent_key'] for r in old_intents if not r['active']]},
            'source_sha256': source_hashes}


if __name__ == '__main__':
    data = inventory()
    target = PROJECT_ROOT/'runs/20260922_legacy_capabilities/inventory-v2.json'
    write(target, data)
    print('flows', len(data['flows']), 'types', len(data['document_types']),
          'missing_active_intents', data['intents']['missing_active'], 'saved', target)
