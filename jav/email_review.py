"""Local full source view, human label and a separate manual candidate export. No API calls."""
import argparse
import html
import json
from pathlib import Path
from jav.email_learning import review_record, export_candidate
from jav.learning_runtime import canonical_hash


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path,value):
    with Path(path).open('x',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2)


def make_review(case,candidate,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    parts=['<!doctype html><meta charset="utf-8"><title>Email ellenőrzés</title>',
           '<style>body{max-width:1000px;margin:3em auto;font:16px system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}section{border-top:1px solid #aaa;margin-top:2em}</style>',
           '<h1>Teljes helyi forrás és kézi ellenőrzés</h1>',
           '<p>A gépi besorolás jelölt. Olvasatlan csatolmány vagy rövidített beérkezés esetén a forrás teljessége nem igazolt.</p>',
           '<pre>'+html.escape(json.dumps(case['message'],ensure_ascii=False,indent=2))+'</pre>']
    for s in case['sources']:
        parts.append('<section><h2>'+html.escape(s['id']+' — '+s['status'])+'</h2><pre>'+html.escape(s['text'])+'</pre></section>')
    parts.append('<section><h2>Gépi jelölt és bizonyítékhelyek</h2><pre>'+html.escape(json.dumps(candidate,ensure_ascii=False,indent=2))+'</pre></section>')
    with (directory/'review.html').open('x',encoding='utf-8') as f:f.write('\n'.join(parts))
    write(directory/'label-template.json',dict(case_id=case['case_id'],case_sha256=canonical_hash(case),
        reviewer='',intent='',rationale='',evidence=[dict(source_id='body',start=0,end=0,quote='')]))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['view','label','export'])
    p.add_argument('--inputs',type=Path,required=True)
    p.add_argument('--case',required=True)
    p.add_argument('--result',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--label',type=Path)
    p.add_argument('--confirm-human',action='store_true')
    a=p.parse_args()
    case=next(c for c in read(a.inputs) if c['case_id']==a.case)
    candidate=read(a.result)['candidate']
    if candidate['case_sha256']!=canonical_hash(case):raise ValueError('result does not belong to source')
    if a.command=='view':make_review(case,candidate,a.out)
    elif a.command=='label':
        label=read(a.label)
        if label['case_sha256']!=canonical_hash(case) or label['case_id']!=a.case:raise ValueError('label source mismatch')
        checked=review_record(case,**{k:label[k] for k in ['intent','reviewer','rationale','evidence']},human_confirmed=a.confirm_human)
        write(a.out,checked)
    else:
        export_candidate(case,candidate,read(a.label),a.out)
    print(str(a.out))


if __name__=='__main__':main()
