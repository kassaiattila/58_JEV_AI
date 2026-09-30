import hashlib
from types import SimpleNamespace

from jav import store
import pytest


def answer(choice="supports", confidence=.95):
    return SimpleNamespace(choices={"relation":SimpleNamespace(choice=choice, confidence=confidence)},
                           model_dump=lambda **kw: {"choice":choice,"confidence":confidence})


def test_unknown_type_can_retain_verified_point_and_persist_without_claiming_completeness(tmp_path):
    from jav.document_learning import ProposalBatch, check_proposals, save_result, load_result, load_config
    text = "Bearing temperature: 68 Celsius"
    proposals = ProposalBatch(source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        points=[dict(name="bearing_temperature",role="bearing temperature",raw_value="68",unit="Celsius",quote=text)])
    def ask(step, state, questions):
        assert "68" in state["claim"] and "bearing temperature" in state["claim"]
        return answer()
    result = check_proposals(text, proposals, ask, load_config())
    assert result.type_status == "unknown"
    assert result.completeness == "not_established"
    assert result.points[0].verification["status"] == "supported"
    assert result.points[0].proposal.raw_value == "68"
    assert result.points[0].start == 0 and result.points[0].end == len(text)
    with store.use_store(tmp_path / "business.sqlite"):
        save_result("unknown-1",result)
        assert load_result("unknown-1") == result


def test_pydantic_proposer_returns_new_fields_and_keeps_repeated_entities_without_network(tmp_path):
    from pydantic_ai.models.test import TestModel
    from jav.document_learning import propose, load_config
    text = "Pump A: 68 Celsius\nPump B: 72 Celsius"
    points = [dict(name="temperature",role="temperature",raw_value=value,unit="Celsius",entity_id=entity,quote=quote)
              for entity,value,quote in [("Pump A","68","Pump A: 68 Celsius"),("Pump B","72","Pump B: 72 Celsius")]]
    model = TestModel(custom_output_args={"doc_kind_guess":"maintenance_note","points":points})
    with store.use_store(tmp_path/'business.sqlite'):
        batch = propose(text,model=model,config=load_config(),run_id='proposer-1')
        assert len(store.ledger_for_run('proposer-1'))==1
        assert store.ledger_for_run('proposer-1')[0]['provider']=='test'
    assert batch.source_sha256 == hashlib.sha256(text.encode()).hexdigest()
    assert batch.doc_kind_guess == "maintenance_note"
    assert [p.entity_id for p in batch.points] == ["Pump A","Pump B"]
    assert model.last_model_request_parameters.output_tools


def test_invalid_and_ambiguous_quotes_never_reach_jev_and_wrong_values_are_not_accepted():
    from jav.document_learning import ProposalBatch,check_proposals,load_config,digest
    text = "Value: 10\nValue: 10\nOwner: Alice"
    points = [dict(name="value",role="value",raw_value="10",quote="Value: 10"),
              dict(name="owner",role="owner",raw_value="Bob",quote="Owner: Bob"),
              dict(name="owner",role="owner",raw_value="Bob",quote="Owner: Alice")]
    calls = []
    def ask(step,state,questions):
        calls.append(state)
        assert 'Bob' in state['claim'] and state['quote']=='Owner: Alice'
        return answer("contradicts")
    result = check_proposals(text,ProposalBatch(source_sha256=digest(text),points=points),ask,load_config())
    assert [p.verification['status'] for p in result.points] == ['ambiguous_quote','invalid_quote','contradicted']
    assert len(calls)==1


def test_stale_source_and_limits_fail_before_calls_and_artifacts_cannot_be_overwritten(tmp_path):
    from jav.document_learning import ProposalBatch,check_proposals,load_config,digest
    def forbidden(*args):
        pytest.fail('invalid input reached provider')
    with pytest.raises(ValueError,match='source mismatch'):
        check_proposals('new',ProposalBatch(source_sha256=digest('old'),points=[]),forbidden,load_config())
    with pytest.raises(ValueError,match='context limit'):
        check_proposals('x'*16001,ProposalBatch(source_sha256=digest('x'*16001),points=[]),forbidden,load_config())
    with store.use_store(tmp_path/'business.sqlite'):
        store.save_artifact('test','one',{'value':1})
        store.save_artifact('test','one',{'value':1})
        with pytest.raises(ValueError,match='different content'):
            store.save_artifact('test','one',{'value':2})
        assert store.load_artifact('test','one')=={'value':1}


def test_provider_failure_stops_remaining_checks_without_claiming_success():
    from jav.document_learning import ProposalBatch,check_proposals,load_config,digest
    from jav.adapters.jev import JevUnavailableError
    text='Owner: Alice'
    point=dict(name='owner',role='owner',raw_value='Alice',quote=text)
    calls=[]
    def ask(*args):
        calls.append(1)
        raise JevUnavailableError('timeout')
    result=check_proposals(text,ProposalBatch(source_sha256=digest(text),points=[point,point]),ask,load_config())
    assert [p.verification['status'] for p in result.points]==['unavailable','not_checked']
    assert len(calls)==1


def test_labelled_text_without_known_type_produces_exact_proposals_and_reports_capacity_limit():
    from jav.document_learning import propose_labels,load_config
    text='Report\nTemperature: 68 Celsius\nTemperature: 72 Celsius\n'
    config=load_config() | {'max_points':1}
    batch=propose_labels(text,config)
    assert batch.doc_kind_guess is None
    assert len(batch.points)==1 and batch.omitted_candidates==1
    point=batch.points[0]
    assert point.role=='Temperature' and point.raw_value=='68 Celsius'
    assert text[point.start:point.start+len(point.quote)]==point.quote


def test_snapshot_model_cost_uses_explicit_requested_price_and_passes_token_cap(tmp_path):
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.usage import RequestUsage
    from jav.document_learning import propose,load_config
    def provider(messages, info):
        assert info.model_settings['max_tokens']==1500
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,{'points':[]})],
            model_name='gpt-5.4-mini-2026-03-17',usage=RequestUsage(input_tokens=100,output_tokens=10))
    # The external provider boundary returns the actual snapshot, as live OpenAI does.
    class OpenAIStub(FunctionModel):
        async def request(self,*args,**kwargs):
            response=await super().request(*args,**kwargs)
            response.model_name='gpt-5.4-mini-2026-03-17'
            return response
        @property
        def system(self):
            return 'openai'
    model=OpenAIStub(provider,model_name='gpt-5.4-mini')
    with store.use_store(tmp_path/'business.sqlite'):
        result=propose('a source',model=model,config=load_config()|{'proposal_model_settings':{'max_tokens':1500}})
        assert result.generation['cost_usd']==.000120
        assert store.ledger_for_run('adhoc')[0]['model']=='gpt-5.4-mini-2026-03-17'
