def test_wrong_model_offset_is_recovered_only_for_one_exact_literal_occurrence():
    from jav.document_learning import ProposalBatch,digest,resolve_literal_spans
    text='Owner: Alice\nValue: 10\nValue: 10'
    batch=ProposalBatch(source_sha256=digest(text),points=[
        dict(name='owner',role='owner',raw_value='Alice',quote='Owner: Alice',start=4),
        dict(name='value',role='value',raw_value='10',quote='Value: 10',start=1),
        dict(name='altered',role='owner',raw_value='Alice',quote='Owner:  Alice',start=0)])
    result,changes=resolve_literal_spans(text,batch)
    assert result.points[0].start==0
    assert result.points[0].quote==batch.points[0].quote
    assert result.points[1:]==batch.points[1:]
    assert changes==[{'point_index':0,'old_start':4,'new_start':0,'reason':'unique_exact_quote'}]
    assert batch.points[0].start==4


def test_resumable_flow_can_opt_in_to_audited_literal_span_resolution(tmp_path,monkeypatch):
    from tests.test_learning_flow import services
    from jav.document_learning import ProposalBatch,digest
    from jav.learning_runtime import run_learning
    from jav import store
    kwargs,calls=services(tmp_path,monkeypatch)
    text='Owner: Alice'
    batch=ProposalBatch(source_sha256=digest(text),points=[
        dict(name='owner',role='owner',raw_value='Alice',quote=text,start=4)])
    kwargs.update(text=text,model=None,proposals=batch,run_id='strict')
    assert run_learning(**kwargs)['result']['points'][0]['verification']['status']=='invalid_quote'
    kwargs.update(run_id='resolved',config=kwargs['config']|{'resolve_literal_spans':True})
    result=run_learning(**kwargs)
    assert result['result']['points'][0]['verification']['status']=='supported'
    assert result['proposals']['points'][0]['start']==4
    assert result['result']['points'][0]['start']==0
    assert run_learning(**kwargs)==result and len(calls)==1
    with store.use_store(tmp_path/'business.sqlite'):
        assert store.load_artifact('learning_span_resolution','resolved')['changes'][0]['new_start']==0


def test_repeated_quote_requires_unique_literal_context_in_strict_flow(tmp_path,monkeypatch):
    from tests.test_learning_flow import services
    from jav.document_learning import ProposalBatch,digest
    from jav.learning_runtime import run_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    text='Buyer\nAmount: 10\nSeller\nAmount: 10'
    batch=ProposalBatch(source_sha256=digest(text),points=[
        dict(name='amount',role='seller amount',raw_value='10',quote='Amount: 10',start=0,
             context_quote='Seller\nAmount: 10'),
        dict(name='unknown',role='amount',raw_value='10',quote='Amount: 10',start=6)])
    kwargs.update(text=text,model=None,proposals=batch,
                  config=kwargs['config']|{'resolve_context_spans':True})
    result=run_learning(**kwargs)
    points=result['result']['points']
    assert points[0]['start']==text.rindex('Amount: 10')
    assert points[0]['verification']['status']=='supported'
    assert points[1]['verification']['status']=='ambiguous_quote'
    assert len(calls)==1
    assert result['proposals']['points'][0]['start']==0
    assert run_learning(**kwargs)==result and len(calls)==1
