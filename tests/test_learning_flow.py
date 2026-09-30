import pytest

from jav import store
from jav.document_learning import load_config


def services(tmp_path, monkeypatch):
    from pydantic_ai.models.test import TestModel
    from typesafe_sdk import SystemOneResponse
    from jav.adapters.jev import JevAdapter
    calls = []
    def live(*args, **kwargs):
        calls.append(1)
        return SystemOneResponse.model_validate({
            'model':'jev-1.13.0','usage':{'input_tokens':100,'output_tokens':10},
            'answers':{'relation':{'type':'choice','choice':'supports','confidence':.95,
                'probabilities':{'supports':.95,'contradicts':.03,'says_nothing':.02}}}}), .01
    monkeypatch.setattr(JevAdapter, '_live', live)
    text = 'Pump A reached 68 Celsius. Pump B reached 72 Celsius.'
    model = TestModel(custom_output_args={'points':[
        dict(name='temperature',role='temperature',raw_value=value,unit='Celsius',entity_id=entity,quote=quote)
        for entity,value,quote in [('Pump A','68','Pump A reached 68 Celsius.'),
                                   ('Pump B','72','Pump B reached 72 Celsius.')]]})
    adapter = JevAdapter(model='jev-1.13.0',cache_dir=tmp_path/'cache')
    return dict(text=text,directory=tmp_path,run_id='one',model=model,adapter=adapter,config=load_config()), calls


def test_pause_resume_and_terminal_resume_never_regenerate(tmp_path,monkeypatch):
    from jav.learning_runtime import run_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    first=run_learning(**kwargs,halt_after=['generate'])
    assert first['proposals']['points'][1]['raw_value']=='72'
    assert calls==[]
    final=run_learning(**kwargs)
    assert len(calls)==2 and final['result']['completeness']=='not_established'
    assert run_learning(**kwargs)==final and len(calls)==2
    with store.use_store(tmp_path/'business.sqlite'):
        assert len([r for r in store.ledger_for_run('one') if r['step']=='generic_propose'])==1
    with pytest.raises(ValueError,match='different content'):
        run_learning(**(kwargs|{'text':kwargs['text']+' changed'}))


def test_crash_after_saved_jev_response_reuses_own_transcript(tmp_path,monkeypatch):
    from jav.learning_runtime import run_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    def fault(event):
        if event=='after_exchange:0':
            raise RuntimeError('simulated crash')
    with pytest.raises(RuntimeError,match='simulated crash'):
        run_learning(**kwargs,fault=fault)
    assert len(calls)==1
    final=run_learning(**kwargs)
    assert len(calls)==2
    assert [p['verification']['status'] for p in final['result']['points']]==['supported']*2


def test_crash_after_generator_and_after_business_write_are_idempotent(tmp_path,monkeypatch):
    from jav.learning_runtime import run_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    for event in ['after_proposals','after_action:save']:
        def fault(actual):
            if actual==event:
                raise RuntimeError('simulated crash')
        with pytest.raises(RuntimeError,match='simulated crash'):
            run_learning(**kwargs,fault=fault)
    final=run_learning(**kwargs)
    assert len(calls)==2
    with store.use_store(tmp_path/'business.sqlite'):
        assert len(store.ledger_for_run('one'))==3
        assert store.load_artifact('generic_extraction','one')==final['result']


def test_unrecorded_external_response_cannot_be_silently_retried(tmp_path,monkeypatch):
    from jav.learning_runtime import run_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    def fault(event):
        if event=='before_exchange_save:0':
            raise RuntimeError('response lost')
    with pytest.raises(RuntimeError,match='response lost'):
        run_learning(**kwargs,fault=fault)
    with pytest.raises(RuntimeError,match='unresolved external call'):
        run_learning(**kwargs)
    assert len(calls)==1


def test_changed_config_and_model_cannot_resume_existing_run(tmp_path,monkeypatch):
    from jav.learning_runtime import run_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    run_learning(**kwargs,halt_after=['generate'])
    with pytest.raises(ValueError,match='different content'):
        run_learning(**(kwargs|{'config':kwargs['config']|{'max_points':1}}))
    kwargs['adapter'].model='jev-1.12.0'
    with pytest.raises(ValueError,match='different content'):
        run_learning(**kwargs)
    assert calls==[]


def test_worker_lock_blocks_parallel_calls_and_releases_after_exception(tmp_path,monkeypatch):
    import sqlite3
    from contextlib import closing
    from jav.learning_runtime import run_learning
    kwargs,calls=services(tmp_path,monkeypatch)
    with closing(sqlite3.connect(tmp_path/'worker.sqlite')) as lock:
        lock.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError,match='locked'):
            run_learning(**kwargs)
        assert calls==[]
    assert run_learning(**kwargs)['result']['points']
    assert len(calls)==2


def test_provider_outage_is_persisted_as_incomplete_not_retried_as_success(tmp_path,monkeypatch):
    from jav.learning_runtime import run_learning
    from jav.adapters.jev import JevUnavailableError
    kwargs,calls=services(tmp_path,monkeypatch)
    def unavailable(*args,**kwargs):
        calls.append(1)
        raise JevUnavailableError('timeout')
    monkeypatch.setattr(kwargs['adapter'],'ask',unavailable)
    def fault(event):
        if event=='after_action:verify':
            raise RuntimeError('simulated crash')
    with pytest.raises(RuntimeError,match='simulated crash'):
        run_learning(**kwargs,fault=fault)
    result=run_learning(**kwargs)['result']
    assert [p['verification']['status'] for p in result['points']]==['unavailable','not_checked']
    assert calls==[1]
