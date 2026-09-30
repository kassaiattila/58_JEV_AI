import pytest


def test_requested_amount_cannot_accept_a_tax_identifier_even_if_verifier_supports_it():
    from jav.document_learning import check_proposals, ProposalBatch, load_config, digest
    text='VAT ID: HU28994028'
    proposal=ProposalBatch(source_sha256=digest(text),points=[dict(
        name='vat_amount',role='VAT amount charged',raw_value='HU28994028',quote=text)])
    config=load_config() | {'field_patterns':{'vat_amount':r'\d+(?:[.,]\d+)?'}}
    def forbidden(*args):
        pytest.fail('tax identifier must not reach amount verification')
    result=check_proposals(text,proposal,forbidden,config)
    assert result.points[0].verification['status']=='invalid_value'


def test_distant_evidence_preserves_gaps_and_original_quote_positions():
    from jav.evidence_learning import build_bundle, source_position
    from jav.document_learning import digest
    text='Invoice A\nAmount: 10\nUnrelated B\nAmount: 10\nCorrection A: 12'
    spans=[(0,20),(text.index('Correction'),len(text))]
    bundle=build_bundle(text,spans,source_sha256=digest(text))
    assert 'Unrelated B' not in bundle['text']
    assert source_position(bundle,bundle['text'].index('Amount: 10'),len('Amount: 10'))==(10,20)
    start=bundle['text'].index('Invoice A')
    assert source_position(bundle,start,len('Invoice A'))==(0,9)
    assert bundle['source_coverage_complete'] is False
    # The artificial separator must not become a source quote.
    assert source_position(bundle,0,len(bundle['text'])) is None
    with pytest.raises(ValueError):
        build_bundle(text,[(0,len(text))],source_sha256=digest(text),max_chars=10)
    with pytest.raises(ValueError):
        build_bundle(text,spans,source_sha256='0'*64)


def test_evidence_runtime_keeps_equal_values_separate_and_resumes_without_calls(tmp_path,monkeypatch):
    from tests.test_learning_flow import services
    from jav.document_learning import ProposalBatch,digest
    from jav.evidence_learning import build_bundle,run_evidence_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    text='Opening: 10\nOmitted text\nClosing: 10'
    spans=[(0,11),(text.index('Closing:'),len(text))]
    bundle=build_bundle(text,spans,source_sha256=digest(text))
    points=[dict(name=role,role=role,raw_value='10',quote=quote)
            for role,quote in [('opening','Opening: 10'),('closing','Closing: 10')]]
    batch=ProposalBatch(source_sha256=digest(bundle['text']),points=points)
    kwargs.update(text=text,spans=spans,source_sha256=digest(text),model=None,proposals=batch)
    result=run_evidence_learning(**kwargs)
    assert len(calls)==2
    assert [p['source_start'] for p in result['points']]==[0,text.index('Closing:')]
    assert result['document_correctness']=='not_established'
    assert result['source_coverage_complete'] is False
    assert run_evidence_learning(**kwargs)==result and len(calls)==2
    with pytest.raises(ValueError):
        run_evidence_learning(**(kwargs|{'text':text+'changed'}))


def test_evidence_rejects_quotes_crossing_artificial_gap(tmp_path,monkeypatch):
    from tests.test_learning_flow import services
    from jav.document_learning import ProposalBatch,digest
    from jav.evidence_learning import build_bundle,run_evidence_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    text='A: 10\nHidden\nB: 10'
    spans=[(0,5),(13,len(text))]
    bundle=build_bundle(text,spans,source_sha256=digest(text))
    batch=ProposalBatch(source_sha256=digest(bundle['text']),points=[dict(
        name='x',role='x',raw_value='10',quote=bundle['text'])])
    kwargs.update(text=text,spans=spans,source_sha256=digest(text),model=None,proposals=batch)
    result=run_evidence_learning(**kwargs)
    assert result['points'][0]['verification']['status']=='invalid_source_span'
    assert result['points'][0]['source_start'] is None


def test_exact_separate_context_is_expanded_only_within_one_source_part(tmp_path,monkeypatch):
    from tests.test_learning_flow import services
    from jav.document_learning import ProposalBatch,digest
    from jav.learning_runtime import run_learning
    from jav import store
    kwargs,calls=services(tmp_path,monkeypatch)
    text='Invoice: A\nDetails\nAmount: 10'
    batch=ProposalBatch(source_sha256=digest(text),points=[dict(name='amount',role='invoice A payable',
        raw_value='10',quote='Amount: 10',context_quote='Invoice: A')])
    kwargs.update(text=text,model=None,proposals=batch,
        config=kwargs['config']|{'resolve_context_spans':True,'expand_exact_context':True,
            'context_ranges':[(0,len(text))]})
    result=run_learning(**kwargs)['result']
    assert result['points'][0]['verification']['status']=='supported'
    with store.use_store(tmp_path/'business.sqlite'):
        saved=store.load_artifact('learning_proposals','one')
        assert saved['points'][0]['context_quote']=='Invoice: A'
        changes=store.load_artifact('learning_span_resolution','one')['changes']
        assert any(c['reason']=='expanded_exact_context' for c in changes)
    # No repair is allowed across the two separate parts.
    kwargs['run_id']='gap'
    kwargs['config']=kwargs['config']|{'context_ranges':[(0,10),(19,len(text))]}
    assert run_learning(**kwargs)['result']['points'][0]['verification']['status']=='invalid_context'
    assert len(calls)==1


@pytest.mark.parametrize('text,context',[
    ('Invoice: A\nAmount: 10','Invoice:  A'),
    ('Invoice: A\nAmount: 10\nAmount: 10','Invoice: A'),
    ('Invoice: A\nInvoice: A\nAmount: 10','Invoice: A'),
])
def test_expansion_does_not_guess_modified_or_repeated_source(text,context):
    from jav.document_learning import ProposalBatch,digest,resolve_context_spans
    batch=ProposalBatch(source_sha256=digest(text),points=[dict(name='amount',role='amount',
        raw_value='10',quote='Amount: 10',context_quote=context)])
    fixed,changes=resolve_context_spans(text,batch,expand_exact_context=True)
    assert fixed==batch and changes==[]
