import pytest


def test_chunk_plan_preserves_unicode_whitespace_pages_and_limits():
    from jav.document_chunks import plan_document, ChunkPolicy
    from jav.models import LineLayout
    text='Ár: 10\n' + 'hosszú ' * 20 + '\nMásodik oldal\nÁr: 10'
    lines=text.split('\n')
    layout=[LineLayout(no=i+1,page=1 if i<2 else 2,text=line,cells=[])
            for i,line in enumerate(lines)]
    policy=ChunkPolicy(max_chars=64,overlap_chars=12,max_chunks=20)
    plan=plan_document(text,policy,layout=layout)
    assert plan==plan_document(text,policy,layout=layout)
    assert {c.page for c in plan.chunks}=={1,2}
    assert all(c.end-c.start<=64 for c in plan.chunks)
    assert set().union(*(set(range(c.start,c.end)) for c in plan.chunks))==set(range(len(text)))
    assert all(text[c.start:c.end] for c in plan.chunks)
    assert plan.coverage_complete and plan.source_chars==len(text)
    with pytest.raises(ValueError,match='max_chunks'):
        plan_document(text,policy.model_copy(update={'max_chunks':1}))
    with pytest.raises(ValueError,match='layout'):
        plan_document(text+'!',policy,layout=layout)


def test_chunked_runtime_resumes_and_preserves_distinct_repeated_occurrences(tmp_path,monkeypatch):
    from tests.test_learning_flow import services
    from jav.document_chunks import ChunkPolicy, plan_document
    from jav.document_learning import propose_labels
    from jav.learning_runtime import run_chunked_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    text='Amount: 10\n' * 6
    policy=ChunkPolicy(max_chars=22,overlap_chars=11,max_chunks=20)
    plan=plan_document(text,policy)
    batches={c.id:propose_labels(text[c.start:c.end],kwargs['config']) for c in plan.chunks}
    kwargs.update(text=text,model=None,proposals=batches,chunk_policy=policy)
    partial=run_chunked_learning(**kwargs,stop_after_chunks=1)
    assert partial['coverage']['chunks_completed']==1
    assert partial['coverage']['complete'] is False
    finished=run_chunked_learning(**kwargs)
    assert finished['coverage']['complete']
    assert finished['completeness']=='not_established'
    # A repeated quote within a part is not verified merely because of its local position.
    assert all(p['evidence'][0]['point']['verification']['status']=='ambiguous_quote'
               for p in finished['points'])
    count=len(calls)
    assert run_chunked_learning(**kwargs)==finished and len(calls)==count
    with pytest.raises(ValueError):
        run_chunked_learning(**(kwargs|{'text':text+'extra'}))


def test_overlap_merges_same_source_fact_but_keeps_equal_values_elsewhere(tmp_path,monkeypatch):
    from tests.test_learning_flow import services
    from jav.document_chunks import ChunkPolicy,plan_document
    from jav.document_learning import ProposalBatch
    from jav.learning_runtime import run_chunked_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    text='A: 10\nB: 10\nC: 10\nD: 10\n'
    policy=ChunkPolicy(max_chars=12,overlap_chars=6,max_chunks=10)
    plan=plan_document(text,policy)
    batches={}
    for chunk in plan.chunks:
        points=[]
        for line in text[chunk.start:chunk.end].splitlines():
            points.append(dict(name='value',role='measured value',raw_value='10',quote=line))
        batches[chunk.id]=ProposalBatch(source_sha256=chunk.source_sha256,points=points)
    kwargs.update(text=text,model=None,proposals=batches,chunk_policy=policy)
    final=run_chunked_learning(**kwargs)
    assert len(final['points'])==4
    assert [p['start'] for p in final['points']]==[0,6,12,18]
    assert [len(p['evidence']) for p in final['points']]==[1,2,2,1]
    assert all(text[p['start']:p['end']]==p['fact']['quote'] for p in final['points'])
    count=len(calls)
    assert run_chunked_learning(**kwargs)==final and len(calls)==count
    with pytest.raises(ValueError,match='different content'):
        run_chunked_learning(**(kwargs|{'config':kwargs['config']|{'max_points':30}}))


def test_document_send_limit_cannot_be_bypassed_by_small_chunks(tmp_path,monkeypatch):
    from tests.test_learning_flow import services
    from jav.document_chunks import ChunkPolicy
    from jav.learning_runtime import run_chunked_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    kwargs.update(text='Label: value\n'*1500,chunk_policy=ChunkPolicy(max_chars=1000,overlap_chars=50,max_chunks=30))
    with pytest.raises(ValueError,match='external source character limit'):
        run_chunked_learning(**kwargs)
    assert calls==[]
    assert not (tmp_path/'document.sqlite').exists()


def test_context_conflicts_and_repetition_stop_before_verifier():
    from jav.document_learning import ProposalBatch,digest,check_proposals,load_config
    text='One\nValue: 10\nTwo\nValue: 10'
    cases=[('Two\nValue:  10',None,'invalid_context'),
           ('Value: 10',None,'ambiguous_quote'),
           ('Two\nValue: 10',4,'invalid_context')]
    def forbidden(*args):
        pytest.fail('invalid context reached verifier')
    for context,start,expected in cases:
        batch=ProposalBatch(source_sha256=digest(text),points=[dict(
            name='value',role='value',raw_value='10',quote='Value: 10',context_quote=context,start=start)])
        result=check_proposals(text,batch,forbidden,load_config())
        assert result.points[0].verification['status']==expected


def test_long_synthetic_source_recovers_mid_chunk_without_repeating_provider(tmp_path,monkeypatch):
    from tests.test_learning_flow import services
    from jav.document_chunks import ChunkPolicy,plan_document
    from jav.document_learning import propose_labels
    from jav.learning_runtime import run_chunked_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    text=('Padding.\n'*900+'Marker: 10\n')*2
    policy=ChunkPolicy(max_chars=8000,overlap_chars=300,max_chunks=10)
    batches={c.id:propose_labels(text[c.start:c.end],kwargs['config'])
             for c in plan_document(text,policy).chunks}
    kwargs.update(text=text,model=None,proposals=batches,chunk_policy=policy,source_char_limit=len(text))
    exchanges=[]
    def crash(event):
        if event=='after_exchange:0':
            exchanges.append(event)
            if len(exchanges)==2:
                raise RuntimeError('second chunk interrupted')
    with pytest.raises(RuntimeError,match='second chunk'):
        run_chunked_learning(**kwargs,fault=crash)
    assert len(calls)==2
    final=run_chunked_learning(**kwargs)
    assert final['coverage']['complete'] and len(final['points'])==2
    assert len(calls)==2


def test_whitespace_chunks_are_covered_without_generation_or_verification(tmp_path,monkeypatch):
    from tests.test_learning_flow import services
    from jav.document_chunks import ChunkPolicy,plan_document
    from jav.document_learning import ProposalBatch
    from jav.learning_runtime import run_chunked_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    text='Header\n'+' '*100
    policy=ChunkPolicy(max_chars=20,overlap_chars=2,max_chunks=20)
    batches={c.id:ProposalBatch(source_sha256=c.source_sha256,points=[]) for c in plan_document(text,policy).chunks}
    final=run_chunked_learning(**(kwargs|dict(text=text,model=None,proposals=batches,chunk_policy=policy)))
    assert final['coverage']['complete'] and final['points']==[] and calls==[]


def test_chunked_generation_is_page_scoped_and_restores_without_new_spend(tmp_path,monkeypatch):
    from tests.test_learning_flow import services
    from jav.document_chunks import ChunkPolicy
    from jav.learning_runtime import run_chunked_learning
    from jav.models import LineLayout
    from jav import store
    kwargs,calls=services(tmp_path,monkeypatch)
    page=kwargs['text']
    kwargs.update(text=page+'\n'+page,layout=[
        LineLayout(no=1,page=1,text=page,cells=[]),LineLayout(no=2,page=2,text=page,cells=[])],
        chunk_policy=ChunkPolicy(max_chars=80,overlap_chars=8,max_chunks=10))
    first=run_chunked_learning(**kwargs,stop_after_chunks=1)
    assert len(calls)==2 and first['coverage']['complete'] is False
    final=run_chunked_learning(**kwargs)
    assert len(calls)==4 and len(final['points'])==4
    assert [p['page'] for p in final['points']]==[1,1,2,2]
    assert run_chunked_learning(**kwargs)==final and len(calls)==4
    with store.use_store(tmp_path/'parts/business.sqlite'):
        generation=[row for child in final['completed'] for row in store.ledger_for_run(child['run_id'])
                    if row['step']=='generic_propose']
        assert len(generation)==2
