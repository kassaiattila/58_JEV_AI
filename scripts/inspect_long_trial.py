import json
import sqlite3
from pathlib import Path
from collections import Counter

root=Path('runs/20260921_long_document_trial')
for path in sorted((root/'baseline-v2').rglob('business.sqlite')):
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        values=[json.loads(r[0]) for r in db.execute('select payload from artifacts where kind=?',('generic_extraction',))]
    points=[p for v in values for p in v['points']]
    print(path.parent.relative_to(root),len(values),Counter(p['verification']['status'] for p in points))
for path in sorted((root/'baseline-v2').glob('*-probes.json')):
    data=json.loads(path.read_text(encoding='utf8'))
    print(path.name, 'expected',data['expected'],'actual',[p['verification']['status'] for p in data['checked']['points']])
    print('GEN',[(p['proposal']['name'],p['proposal']['raw_value'],p['verification']['status']) for p in data['generated']['points']])
    if data['local_only']:
        print('LOCAL',[p['verification']['status'] for p in data['local_only']['points']])
