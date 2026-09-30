"""031: külön, befagyasztott e-mailminta és saját JEV-elszámolás."""
from pathlib import Path
import json
import hashlib
import os

from jav.config import PROJECT_ROOT
from jav.emails import load_message_dir
from jav.pdf import read_pdf

ROOT = PROJECT_ROOT/'runs/20260921_email_learning'


def mailboxes():
    """070: a két jóváhagyott postafiók címe saját adat, ezért nincs a kódban. A lezárt futás jóváhagyása a helyi
    `runs/20260921_email_learning/approval.json`-ban van; újrafuttatáshoz `JAV_TRIAL_031_MAILBOXES="<céges>,<gmail>"`."""
    parts=[x.strip() for x in os.environ.get('JAV_TRIAL_031_MAILBOXES','').split(',') if x.strip()]
    if len(parts)!=2:
        raise SystemExit('JAV_TRIAL_031_MAILBOXES: két postafiók-cím kell (céges, gmail)')
    return parts[0], parts[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def prepare():
    work_box,gmail_box=mailboxes()
    work=list((PROJECT_ROOT/'inbox'/work_box.replace('@','_')).glob('*/message.json'))
    # Előre rögzített, címke nélküli célzott rétegezés; nem reprezentatív eloszlás.
    work.sort(key=lambda p:(-len(read(p).get('attachments',[])), -len(read(p).get('body','')), p.parent.name))
    gmail=sorted((ROOT/'inbox'/gmail_box.replace('@','_')).glob('*/message.json'))
    assert len(gmail)==20
    inputs=[]
    for i,path in enumerate(work[:20]+gmail,1):
        msg=load_message_dir(path.parent)
        meta=read(path)
        sources=[dict(id='body',kind='body',text=msg.body,status='read',sha256=sha(msg.body))]
        attachments=[]
        for n,att in enumerate(msg.attachments,1):
            src=dict(id=f'attachment-{n}',kind='attachment',filename=att.filename,text='',status='missing',sha256=sha(''))
            if att.path:
                p=Path(att.path)
                src['file_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
                if p.suffix.lower()=='.pdf':
                    try:
                        pdf=read_pdf(p)
                        src.update(text=pdf.text,sha256=sha(pdf.text),pages=pdf.page_count,
                                   status='read' if pdf.has_text_layer else 'unreadable')
                    except Exception as exc:
                        src['status']='read_error:'+type(exc).__name__
                else:
                    src['status']='unsupported'
            sources.append(src)
            attachments.append(att.model_dump())
        total=sum(len(s['text']) for s in sources)
        inputs.append(dict(case_id=f'email-{i:03d}',message=msg.model_dump(),sources=sources,
                           source_path=str(path),source_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                           source_chars=total,eligible=total<=50000,attachment_failures=meta.get('attachments_failed') or 0,
                           upstream_body_limit_possible=len(msg.body)>=20000))
    write(ROOT/'inputs.json', inputs)
    write(ROOT/'approval.json',dict(approved=True,authority='User explicit answer 2026-09-21: Igen, a fenti külön JEV-kerettel',
        allowed_mailboxes=[gmail_box,work_box],allowed_providers=['jev'],
        max_emails=40,max_source_chars=50000,max_part_chars=8000,max_calls=400,recorded_stop_usd=2,
        personal_invoice_banking_data=True,retries_included=True,openai_calls=0,
        inputs_sha256=hashlib.sha256((ROOT/'inputs.json').read_bytes()).hexdigest()))
    print(json.dumps(dict(cases=len(inputs),eligible=sum(x['eligible'] for x in inputs),
        chars=sum(x['source_chars'] for x in inputs),attachments=sum(len(x['sources'])-1 for x in inputs),
        statuses=[s['status'] for x in inputs for s in x['sources'] if s['kind']=='attachment'])))


def validate():
    from jav.learning_runtime import canonical_hash
    from jav.email_learning import validate_case
    frozen=read(ROOT/'frozen.json')
    for name,expected in frozen.items():
        if canonical_hash(read(ROOT/name))!=expected:
            raise ValueError('frozen file changed: '+name)
    approval=read(ROOT/'approval.json')
    assert approval['approved'] and approval['max_calls']==400 and approval['recorded_stop_usd']==2
    inputs=read(ROOT/'inputs.json')
    assert len(inputs)<=40 and hashlib.sha256((ROOT/'inputs.json').read_bytes()).hexdigest()==approval['inputs_sha256']
    for c in inputs:
        assert c['message']['mailbox'] in approval['allowed_mailboxes']
        validate_case(c)
    return inputs


def services():
    from jav.experiments.long_document_trial import TrialBudget
    from jav.adapters.jev import JevAdapter
    from jav.config import make_client
    from typesafe_sdk import RetryPolicy
    budget=TrialBudget(ROOT,limits={'jev':(400,2)})
    class BoundedJev(JevAdapter):
        def _live(self,*args,**kwargs):
            budget.reserve('jev')
            return super()._live(*args,**kwargs)
    return BoundedJev(client=make_client(retry=RetryPolicy(max_retries=0)),model='jev-1.13.0',cache_dir=ROOT/'cache'),budget


def run(split,limit=None,version='v2'):
    import shutil
    from jav.learning_runtime import code_hash
    from jav.email_learning_runtime import run_email_learning
    cases=validate()
    stage=ROOT/version
    config=read(ROOT/('config-'+version+'.json'))
    if version=='v2':
        from jav.learning_runtime import canonical_hash
        assert canonical_hash(config)==read(ROOT/'v2-frozen.json')['config_sha256']
    if (stage/'code.json').exists():
        if read(stage/'code.json')['sha256']!=code_hash():
            raise ValueError('stage code changed; use a new measured revision')
    else:
        write(stage/'code.json',dict(sha256=code_hash()))
        for p in (PROJECT_ROOT/'jav').rglob('*.py'):
            target=stage/'source_snapshot'/p.relative_to(PROJECT_ROOT)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    adapter,budget=services(); splits=read(ROOT/'splits.json');count=0
    for c in cases:
        cid=c['case_id']; dest=stage/(cid+'.json')
        if splits[cid]['split']!=split or dest.exists(): continue
        baseline_record=None
        previous=ROOT/'v1'/(cid+'.json')
        if version!='v1' and previous.exists():
            from jav.intent import CONFIG_HASH
            from jav.learning_runtime import canonical_hash
            assert hashlib.sha256(previous.read_bytes()).hexdigest()==read(ROOT/'v1-sealed.json')[previous.name]
            old=read(previous)
            assert old['candidate']['case_sha256']==canonical_hash(c)
            baseline_record=dict(case_sha256=canonical_hash(c),config_hash=CONFIG_HASH,baseline=old['baseline'])
        result=run_email_learning(case=c,directory=stage/cid,run_id=cid,adapter=adapter,config=config,baseline_record=baseline_record)
        write(dest,result)
        print(cid,result['baseline']['intent'],'->',result['result']['intent'],
              result['result']['coverage']['review_reasons'],budget.usage(),flush=True)
        count+=1
        if limit and count>=limit: break
    write(ROOT/('usage-'+version+'-'+split+'-'+str(budget.usage()['jev']['reserved'])+'.json'),budget.usage())


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['prepare','run'])
    p.add_argument('--split',choices=['development','holdout'],default='development')
    p.add_argument('--limit',type=int)
    p.add_argument('--version',choices=['v1','v2'],default='v2')
    a=p.parse_args()
    prepare() if a.command=='prepare' else run(a.split,a.limit,a.version)
