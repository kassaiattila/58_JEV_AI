import pytest

from jav.matter_review import combine, run_pair


def verdict(relation='duplicate', linked=True):
    return {'relation': relation, 'linked': linked}


def evidence(relation='duplicate', linked=.99, contradiction=.01):
    return {'relation': relation, 'selected_probability': .99,
            'linked_probability': linked, 'contradiction_probability': contradiction}


def test_disagreement_and_contradiction_never_become_accepted_links():
    assert combine(verdict(), evidence())['hybrid_relation'] == 'duplicate'
    for row in [evidence('correction'), evidence(linked=.1), evidence(contradiction=.9)]:
        result = combine(verdict(), row)
        assert result['hybrid_relation'] == 'review'
        assert result['candidate_only'] and result['correctness'] == 'not_established'
    assert combine(verdict(linked=False), evidence())['hybrid_relation'] == 'review'


def test_real_burr_pause_resume_replay_and_identity(tmp_path):
    calls = []
    def gpt():
        calls.append('gpt')
        return verdict()
    def jev():
        calls.append('jev')
        return evidence()
    args = dict(directory=tmp_path, run_id='pair-1', packet={'a': 'one', 'b': 'two'},
                config={'version': 1}, gpt=gpt, jev=jev)
    assert 'gpt' in run_pair(**args, halt_after=['gpt'])
    finished = run_pair(**args)
    assert finished['result']['hybrid_relation'] == 'duplicate'
    assert calls == ['gpt', 'jev']
    assert run_pair(**args) == finished
    assert calls == ['gpt', 'jev']
    with pytest.raises(ValueError, match='identity'):
        run_pair(**(args | {'packet': {'a': 'changed', 'b': 'two'}}))


def test_started_call_without_saved_response_is_not_repeated(tmp_path):
    calls = []
    def fail():
        calls.append('attempt')
        raise OSError('uncertain external outcome')
    args = dict(directory=tmp_path, run_id='pair-2', packet={'a': 'one', 'b': 'two'},
                config={}, gpt=fail, jev=lambda: evidence())
    with pytest.raises(OSError):
        run_pair(**args)
    with pytest.raises(RuntimeError, match='unresolved'):
        run_pair(**args)
    assert calls == ['attempt']


def test_actual_pydantic_response_usage_and_raw_persistence(tmp_path):
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel
    from jav import store
    from jav.matter_review import MatterVerdict
    from jav.experiments.matter_trial import generate_gpt
    model = TestModel(custom_output_args={'linked': True, 'relation': 'duplicate',
        'missing': [], 'confidence': .9, 'rationale': 'Same invoice.'}, model_name='gpt-5.4-mini')
    agent = Agent(model, output_type=MatterVerdict)
    with store.use_store(tmp_path/'business.sqlite'):
        result = generate_gpt(agent, 'test pair', config={'openai_model': 'gpt-5.4-mini'},
                              run_id='response-1', config_hash='test')
        assert result['relation'] == 'duplicate'
        assert store.load_artifact('matter_gpt_raw', 'response-1')['output']['linked']
        ledger = store.ledger_for_run('response-1')
        assert len(ledger) == 1 and ledger[0]['input_tokens'] > 0
        assert ledger[0]['cost_usd'] is not None
