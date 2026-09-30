import pytest

from jav.document_learning import digest


def sample():
    text = 'Invoice A-17. Original payable: 100 EUR. Correction: payable is 120 EUR.'
    return dict(case_id='correction', sources=[dict(id='doc', text=text, sha256=digest(text), status='read')],
                target=dict(role='amount payable for invoice A-17', value='100', unit='EUR', entity='A-17'),
                evidence=[dict(source_id='doc', start=0, quote=text)], source_complete=True)


def test_source_packet_has_stable_identity_and_rejects_tampered_quote():
    from jav.claim_assessment import prepare_packet, load_config
    case = sample()
    packet = prepare_packet(case, load_config())
    assert packet['evidence'][0]['quote'] == case['sources'][0]['text']
    assert packet['claim_id'] == prepare_packet(case, load_config())['claim_id']
    case['evidence'][0]['quote'] = 'Payable 999 EUR'
    with pytest.raises(ValueError, match='evidence'):
        prepare_packet(case, load_config())


def test_agreement_never_promotes_a_candidate_or_hides_missing_sources():
    from jav.claim_assessment import compare_assessments, prepare_packet, load_config
    case = sample()
    case['sources'].append(dict(id='image', text='', sha256=digest(''), status='unread'))
    assessment = dict(role_match='matches', assertion_status='current')
    result = compare_assessments(prepare_packet(case, load_config()), assessment, assessment, {'noul': .99})
    assert result['agreement'] is True
    assert result['correctness'] == 'not_established'
    assert result['status'] == 'candidate_only' and result['activation_allowed'] is False
    assert result['needs_review'] is True
    assert 'unread_source:image' in result['review_reasons']


def test_structured_openai_and_independent_jev_keep_separate_answers(tmp_path):
    from pydantic_ai.models.test import TestModel
    from typesafe_sdk import SystemOneResponse
    from jav import store
    from jav.claim_assessment import prepare_packet, load_config, assess_openai, assess_jev, review_proposal
    config = load_config()
    packet = prepare_packet(sample(), config)
    model = TestModel(custom_output_args=dict(role_match='matches', assertion_status='superseded'))
    with store.use_store(tmp_path / 'business.sqlite'):
        generated = assess_openai(packet, model=model, config=config, run_id='one')
        assert len(store.ledger_for_run('one')) == 1
    calls = []
    def ask(step, state, questions):
        calls.append(state)
        if step == 'claim_independent':
            assert 'proposal' not in state
            return SystemOneResponse.model_validate(dict(model='jev-1.13.0', answers={
                'role_match': dict(type='choice', choice='matches', confidence=.99, probabilities={'matches':.99,'mismatches':.005,'unknown':.005}),
                'assertion_status': dict(type='choice', choice='superseded', confidence=.99, probabilities={'current':.003,'superseded':.99,'disputed':.003,'unknown':.004})}, usage=dict(input_tokens=10, output_tokens=4)))
        assert state['proposal'] == generated['assessment']
        return SystemOneResponse.model_validate(dict(model='jev-1.13.0', answers={
            'proposal_supported': dict(type='noul', noul=.95)}, usage=dict(input_tokens=10, output_tokens=1)))
    independent = assess_jev(packet, ask, config)
    reviewed = review_proposal(packet, generated['assessment'], ask, config)
    assert independent['assessment'] == generated['assessment']
    assert reviewed['noul'] == .95 and len(calls) == 2


def test_resume_preserves_answers_without_new_calls_and_refuses_source_drift(tmp_path):
    from pydantic_ai.models.test import TestModel
    from test_email_signals import FakeClient
    from jav.adapters.jev import JevAdapter
    from jav.claim_assessment import run_assessment, load_config
    client = FakeClient()
    adapter = JevAdapter(client=client, cache_dir=tmp_path/'cache', model='jev-1.13.0')
    model = TestModel(custom_output_args=dict(role_match='matches', assertion_status='superseded'))
    kwargs = dict(case=sample(), directory=tmp_path/'run', run_id='resume', model=model,
                  adapter=adapter, config=load_config())
    def fault(event):
        if event == 'after_independent':
            raise RuntimeError('interrupted')
    with pytest.raises(RuntimeError, match='interrupted'):
        run_assessment(**kwargs, fault=fault)
    assert len(client.requests) == 1
    result = run_assessment(**kwargs)
    assert len(client.requests) == 2
    assert run_assessment(**kwargs) == result and len(client.requests) == 2
    changed = sample()
    changed['target']['value'] = '120'
    with pytest.raises(ValueError, match='different content'):
        run_assessment(**(kwargs | {'case': changed}))


@pytest.mark.parametrize('stage', ['openai', 'independent', 'review'])
def test_uncertain_response_is_not_silently_reissued(tmp_path, stage):
    from pydantic_ai.models.test import TestModel
    from test_email_signals import FakeClient
    from jav.adapters.jev import JevAdapter
    from jav.claim_assessment import run_assessment, load_config
    client = FakeClient()
    kwargs = dict(case=sample(), directory=tmp_path/'run', run_id='lost',
                  model=TestModel(custom_output_args=dict(role_match='matches', assertion_status='superseded')),
                  adapter=JevAdapter(client=client,cache_dir=tmp_path/'cache',model='jev-1.13.0'), config=load_config())
    def fault(event):
        if event == 'before_save:' + stage:
            raise RuntimeError('response not durably recorded')
    with pytest.raises(RuntimeError, match='response not durably'):
        run_assessment(**kwargs, fault=fault)
    count = len(client.requests)
    with pytest.raises(RuntimeError, match='unresolved external call'):
        run_assessment(**kwargs)
    assert len(client.requests) == count


@pytest.mark.parametrize('mutation', ['duplicate', 'hash', 'budget', 'position', 'unread'])
def test_bad_sources_fail_before_any_provider_call(tmp_path, mutation):
    from jav.claim_assessment import run_assessment, load_config
    case = sample()
    config = load_config()
    if mutation == 'duplicate': case['sources'].append(case['sources'][0])
    elif mutation == 'hash': case['sources'][0]['sha256'] = 'f'*64
    elif mutation == 'budget': config['max_evidence_chars'] = 1
    elif mutation == 'position': case['evidence'][0]['start'] = 2
    else: case['sources'][0]['status'] = 'unread'
    # None client: any accidental provider access would raise a different error.
    with pytest.raises(ValueError):
        run_assessment(case=case, directory=tmp_path/'run', run_id='invalid', model=None, adapter=None, config=config)
    assert not (tmp_path/'run').exists()


def test_omitted_context_stays_visible_and_conflicting_model_dimensions_are_flagged():
    from jav.claim_assessment import prepare_packet, compare_assessments, load_config
    case = sample()
    case['evidence'] = [dict(source_id='doc', start=0, quote='Invoice A-17.')]
    packet = prepare_packet(case, load_config())
    bad = dict(role_match='mismatches', assertion_status='current')
    result = compare_assessments(packet, bad, bad, {'noul':.99})
    assert packet['coverage']['covered_chars'] == len('Invoice A-17.')
    assert 'source_excerpts_only' in result['review_reasons']
    assert 'inconsistent_attribution_status:jev' in result['review_reasons']
    assert result['agreement'] and result['correctness'] == 'not_established'


def test_live_trial_requires_approval_bound_to_frozen_sample_and_exact_separate_caps(tmp_path):
    from jav.experiments.claim_assessment_trial import validate, write, sha, LIMITS
    write(tmp_path/'cases.json', [])
    write(tmp_path/'config.json', {})
    write(tmp_path/'protected.json', {})
    write(tmp_path/'frozen.json', {n:sha(tmp_path/n) for n in ['cases.json','config.json','protected.json']})
    write(tmp_path/'request.json', {'approved':False})
    with pytest.raises(ValueError, match='specific trial budget approval'):
        validate(tmp_path)
    caps = {domain:{p:list(v) for p,v in LIMITS.items()} for domain in ['document','email']}
    write(tmp_path/'approval.json', dict(approved=True, frozen_sha256=sha(tmp_path/'frozen.json'),
                                       request_sha256=sha(tmp_path/'request.json'), limits=caps))
    assert validate(tmp_path) == ([], {})
    (tmp_path/'cases.json').write_text('[1]',encoding='utf-8')
    with pytest.raises(ValueError, match='frozen input changed'):
        validate(tmp_path)


def test_review_preserves_separate_role_and_status_signals_when_overall_signal_conflicts():
    from typesafe_sdk import SystemOneResponse
    from jav.claim_assessment import load_config, prepare_packet, review_proposal, compare_assessments
    config = load_config()
    config['review_dimensions'] = {'role_supported': 'Is the proposed role attribution supported?',
                                   'status_supported': 'Is the proposed assertion status supported?'}
    packet = prepare_packet(sample(), config)
    proposal = {'role_match':'mismatches', 'assertion_status':'superseded'}
    def ask(step,state,questions):
        assert set(questions) == {'proposal_supported','role_supported','status_supported'}
        return SystemOneResponse.model_validate({'model':'jev-1.13.0','answers':{
            k:{'type':'noul','noul':v} for k,v in {'proposal_supported':.9,'role_supported':.1,'status_supported':.8}.items()},
            'usage':{'input_tokens':10,'output_tokens':3}})
    review = review_proposal(packet, proposal, ask, config)
    assert review['noul'] == .9
    assert review['dimension_nouls'] == {'role_supported':.1,'status_supported':.8}
    result = compare_assessments(packet, proposal, proposal, review)
    assert result['correctness'] == 'not_established' and not result['activation_allowed']
    assert 'inconsistent_attribution_status:openai' in result['review_reasons']
