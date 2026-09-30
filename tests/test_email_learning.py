from pathlib import Path
import pytest
from jav.email_learning import build_evidence_state, validate_case, review_record, export_candidate
from jav.document_learning import digest


def case(body='Please book the attached invoice.', attachment='Invoice 120 EUR'):
    return dict(case_id='e1',message=dict(message_id='e1',subject='Invoice',body=body,attachments=[dict(filename='a.pdf')]),
        sources=[dict(id='body',kind='body',text=body,status='read',sha256=digest(body)),
                 dict(id='attachment-1',kind='attachment',text=attachment,status='read',sha256=digest(attachment))],
        attachment_failures=0,upstream_body_limit_possible=False)


def test_evidence_keeps_offsets_and_missing_attachment_forces_review():
    c=case(); c['sources'][1].update(status='unsupported',text='',sha256=digest(''))
    st,coverage=build_evidence_state(c,{'body':dict(scanned_chars=len(c['sources'][0]['text']),candidates=[])})
    assert st['evidence'][0]['quote']==c['message']['body']
    assert coverage['text_scan_complete'] and not coverage['all_sources_read']
    assert 'attachment-1:unsupported' in coverage['review_reasons']


def test_tampered_frozen_source_rejected():
    c=case(); c['sources'][0]['text']='changed'
    with pytest.raises(ValueError,match='hash'):
        validate_case(c)


def test_manual_export_cannot_use_unreviewed_prediction(tmp_path):
    c=case(); prediction={'intent':'szamlakuldes'}
    with pytest.raises(ValueError,match='human'):
        export_candidate(c,prediction,dict(authority='model',intent='szamlakuldes'),tmp_path/'x.json')
    label=review_record(c,intent='szamlakuldes',reviewer='test-human',rationale='Body asks to book the invoice.',
                        evidence=[dict(source_id='body',start=0,end=6,quote='Please')],human_confirmed=True)
    export_candidate(c,prediction,label,tmp_path/'candidate.json')
    import json
    doc=json.loads((tmp_path/'candidate.json').read_text())
    assert doc['status']=='candidate_only' and doc['activation_allowed'] is False
    changed=case(body='Different request')
    with pytest.raises(ValueError):
        export_candidate(changed,prediction,label,tmp_path/'bad.json')


def test_burr_resume_uses_own_responses_and_rejects_drift(tmp_path):
    import json
    from test_email_signals import FakeClient
    from jav.adapters.jev import JevAdapter
    from jav.email_learning_runtime import run_email_learning
    client=FakeClient()
    adapter=JevAdapter(client=client,cache_dir=tmp_path/'cache',model='jev-1.13.0')
    config=json.loads(Path('configs/experiments/email_learning.json').read_text(encoding='utf-8'))
    kwargs=dict(case=case(),directory=tmp_path/'run',run_id='one',adapter=adapter,config=config)
    def fault(event):
        if event=='after_exchange:body:evidence_scan_0': raise RuntimeError('crash')
    with pytest.raises(RuntimeError,match='crash'): run_email_learning(**kwargs,fault=fault)
    assert len(client.requests)==2
    result=run_email_learning(**kwargs)
    assert len(client.requests)==4
    assert result['candidate']['gold_label'] is None
    assert run_email_learning(**kwargs)==result and len(client.requests)==4
    with pytest.raises(ValueError):
        run_email_learning(**(kwargs|{'case':case(body='changed')}))


def test_related_threads_and_repeated_attachments_stay_in_same_split():
    from jav.email_learning import group_splits
    a=case();b=case(body='Other');b['case_id']='b'
    b['message'].update(subject='Re: Invoice',sender='different@example.com')
    c=case(body='Third');c['case_id']='c';c['message']['subject']='Unrelated'
    result=group_splits([a,b,c])
    assert len({x['group_id'] for x in result.values()})==1


def test_tracking_url_cannot_hide_current_body_when_model_selects_none():
    body='New possibilities.\n<https://example.com/'+('a'*3000)+'>\nTry our new image tool now.\n'
    c=case(body=body)
    searches={s['id']:dict(scanned_chars=len(s['text']),candidates=[]) for s in c['sources']}
    st,coverage=build_evidence_state(c,searches)
    assert any('Try our new image tool now.' in e['quote'] for e in st['evidence'])
    for e in st['evidence']:
        s=next(s for s in c['sources'] if s['id']==e['source_id'])
        assert s['text'][e['start']:e['end']]==e['quote']
    assert 'no_selected_evidence:body' in coverage['review_reasons']


def test_unresolved_external_attempt_is_not_retried(tmp_path):
    import json
    from test_email_signals import FakeClient
    from jav.adapters.jev import JevAdapter
    from jav.email_learning_runtime import run_email_learning
    class BrokenClient(FakeClient):
        def system_one(self,**kwargs):
            self.requests.append(kwargs)
            raise RuntimeError('lost connection after sending')
    client=BrokenClient()
    config=json.loads(Path('configs/experiments/email_learning_v2.json').read_text(encoding='utf-8'))
    kwargs=dict(case=case(),directory=tmp_path/'run',run_id='unresolved',config=config,
        adapter=JevAdapter(client=client,cache_dir=tmp_path/'cache',model='jev-1.13.0'))
    with pytest.raises(RuntimeError,match='lost connection'):run_email_learning(**kwargs)
    with pytest.raises(RuntimeError,match='unresolved external'):run_email_learning(**kwargs)
    assert len(client.requests)==1


def test_review_view_renders_untrusted_source_as_text(tmp_path):
    from jav.email_review import make_review
    c=case(body='<script>alert(1)</script>')
    make_review(c,{'intent':'other'},tmp_path)
    page=(tmp_path/'review.html').read_text(encoding='utf-8')
    assert '<script>' not in page and '&lt;script&gt;' in page
