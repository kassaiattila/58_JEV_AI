"""One-off, byte-identical port of the schemas missing per the 035 inventory and of the pure legacy validator."""
from pathlib import Path
import json
from jav.config import PROJECT_ROOT, OLD_PROJECT_ROOT
from jav.experiments.long_document_trial import read, write, sha

inventory = read(PROJECT_ROOT/'runs/20260922_legacy_capabilities/inventory-v2.json')
result = []
for item in inventory['document_types']:
    if item['current_extraction_pack']:
        continue
    key = item['key']
    old = OLD_PROJECT_ROOT/'flows/doc-extract-bare/types'/key
    dest = PROJECT_ROOT/'configs/legacy_types'/key
    dest.mkdir(parents=True,exist_ok=False)
    copied = {}
    for name in ['schema.json','prompt.md','rules.json','detect.json','meta.json']:
        source = old/name
        with (dest/name).open('xb') as f:
            f.write(source.read_bytes())
        copied[name] = sha(source)
    for source in sorted((old/'fixtures').glob('*.json')):
        target=dest/'fixtures'/source.name
        target.parent.mkdir(exist_ok=True)
        with target.open('xb') as f:
            f.write(source.read_bytes())
        copied['fixtures/'+source.name]=sha(source)
    manifest = {'version':'1.0.0','source':str(old),'files':copied,
                'legacy_catalog_active':item['legacy_catalog_active'],
                'status':'explicit_type_candidate_processing','automatic_routing_enabled':False}
    write(dest/'manifest.json',manifest)
    result.append({'key':key,'files':len(copied)})
source=OLD_PROJECT_ROOT/'sidecar/app/validate/service.py'
target=PROJECT_ROOT/'jav/legacy_validation.py'
with target.open('xb') as f:
    f.write(source.read_bytes())
write(PROJECT_ROOT/'runs/20260922_expansion/port.json',{'packs':result,
    'validator':{'source':str(source),'target':str(target),'sha256':sha(source),'byte_equal':source.read_bytes()==target.read_bytes()},
    'note':'Legacy JS float parsing retained for behavior parity; old code unchanged, monetary comparisons use minor units.'})
print('Imported',len(result),'packs and byte-identical legacy validator.')
