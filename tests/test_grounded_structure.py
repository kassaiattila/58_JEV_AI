"""Védett szerkezet és forrásállítás: a publikus működés ellenőrzése."""
from jav.models import LineLayout, CellLayout
from jav.grounded_claims import protected_boundaries
from types import SimpleNamespace
import hashlib
import pytest


@pytest.mark.parametrize("choice,confidence,status", [("supports",.95,"supported"),
    ("contradicts",.95,"contradicted"), ("says_nothing",.95,"unsupported"), ("supports",.5,"uncertain")])
def test_claim_semantics_use_context_and_keep_raw_answer(choice, confidence, status):
    from jav.grounded_claims import GroundedClaim, verify_claim
    text = "Old amount: 100 EUR, cancelled. Current amount: 120 EUR."
    claim = GroundedClaim(statement="The payable amount is 100 EUR", source_sha256=hashlib.sha256(text.encode()).hexdigest(),
                          start=12, end=19, quote="100 EUR")
    def ask(step, state, questions):
        assert state["context"] == text  # A szó szerint helyes idézet önmagában félrevezető.
        return SimpleNamespace(choices={"relation":SimpleNamespace(choice=choice,confidence=confidence)},
                               model_dump=lambda **kw: {"choice":choice,"confidence":confidence})
    config = {"max_context_chars":16000,"min_confidence":.8,"question":"Does the source support the claim?",
              "criteria":{"supports":"supports","contradicts":"contradicts","says_nothing":"not addressed"}}
    result = verify_claim(text, claim, config, ask)
    assert result["status"] == status
    assert result["response"] == {"choice":choice,"confidence":confidence}


def test_claim_with_modified_source_is_rejected_without_model():
    import hashlib
    from jav.grounded_claims import GroundedClaim, verify_claim

    claim = GroundedClaim(statement="The amount is 100 EUR", source_sha256=hashlib.sha256(b"100 EUR").hexdigest(),
                          start=0, end=7, quote="100 EUR")
    def forbidden(*args):
        raise AssertionError("Wrong source must not reach the model")
    result = verify_claim("200 EUR", claim, {}, forbidden)
    assert result["status"] == "source_mismatch" and result["response"] is None


@pytest.mark.parametrize("start,end,quote,limit,status", [(0,3,"bad",100,"invalid_quote"),
    (0,100,"amount: 100",100,"invalid_quote"),(0,10,"amount: 100",100,"invalid_quote"),
    (0,10,"amount: 100",2,"invalid_quote"),(0,11,"amount: 100",2,"context_limit")])
def test_invalid_or_over_budget_evidence_never_calls_model(start,end,quote,limit,status):
    from jav.grounded_claims import GroundedClaim, verify_claim
    text = "amount: 100"
    claim = GroundedClaim(statement="claim",source_sha256=hashlib.sha256(text.encode()).hexdigest(),start=start,end=end,quote=quote)
    def forbidden(*args):
        pytest.fail("invalid evidence reached provider")
    assert verify_claim(text,claim,{"max_context_chars":limit},forbidden)["status"] == status


def test_provider_failure_preserves_claim_and_never_supports_it():
    from jav.grounded_claims import GroundedClaim, verify_claim
    from jav.adapters.jev import JevUnavailableError
    text = "amount: 100"
    claim = GroundedClaim(statement="claim",source_sha256=hashlib.sha256(text.encode()).hexdigest(),start=0,end=len(text),quote=text)
    def broken(*args):
        raise JevUnavailableError("timeout")
    result = verify_claim(text,claim,{"max_context_chars":100,"question":"relation?","criteria":{"supports":"yes","contradicts":"no","says_nothing":"other"}},broken)
    assert result["status"] == "unavailable" and result["claim"] == claim.model_dump()


def test_unsorted_layout_rejected():
    with pytest.raises(ValueError):
        protected_boundaries([LineLayout(no=2,page=1,text="b"),LineLayout(no=1,page=1,text="a")],{})


def test_layout_and_config_protect_pages_headers_and_tabular_rows():
    rows = [LineLayout(no=1, page=1, text="Description"),
            LineLayout(no=2, page=1, text="Annual maintenance of"),
            LineLayout(no=3, page=1, text="the pump"),
            LineLayout(no=4, page=2, text="Second page"),
            LineLayout(no=5, page=2, text="Part A  10", cells=[CellLayout(text="Part A",x0=0,x1=20),CellLayout(text="10",x0=40,x1=50)]),
            LineLayout(no=6, page=2, text="Part B  20", cells=[CellLayout(text="Part B",x0=0,x1=20),CellLayout(text="20",x0=40,x1=50)])]
    result = protected_boundaries(rows, {"isolated_line_patterns":["^Description$"], "new_block_patterns":[], "protect_multi_cell_rows":True})
    assert result[1] == ["isolated_line"]
    assert 2 not in result
    assert "page_change" in result[3]
    assert "tabular_rows" in result[5]


def test_wrapped_left_cell_can_join_but_next_full_row_remains_protected():
    def row(no, cells, page=1):
        return LineLayout(no=no, page=page, text="   ".join(c.text for c in cells), cells=cells)
    cells = lambda values: [CellLayout(text=t, x0=a, x1=b) for t,a,b in values]
    rows = [row(1, cells([("Product with long",10,180),("2",240,250),("100",300,320)])),
            row(2, cells([("A1",10,25),("description",55,140)])),
            row(3, cells([("Other product",10,160),("1",240,250),("50",300,320)]))]
    config = {"isolated_line_patterns":[], "new_block_patterns":[], "protect_multi_cell_rows":True,
              "allow_left_cell_continuation":True}
    assert 1 not in protected_boundaries(rows, config)
    assert protected_boundaries(rows, config)[2] == ["tabular_rows"]
    rows[1] = rows[1].model_copy(update={"page":2})
    rows[2] = rows[2].model_copy(update={"page":2})
    assert "page_change" in protected_boundaries(rows, config)[1]


def test_continuation_exception_never_overrides_header_or_new_block():
    rows = [LineLayout(no=1,page=1,text="Product",cells=[CellLayout(text="Product",x0=0,x1=100),CellLayout(text="20",x0=200,x1=220)]),
            LineLayout(no=2,page=1,text="Note: separate",cells=[CellLayout(text="Note:",x0=0,x1=20),CellLayout(text="separate",x0=30,x1=80)])]
    config = {"isolated_line_patterns":[], "new_block_patterns":["^Note:"], "protect_multi_cell_rows":True,
              "allow_left_cell_continuation":True}
    assert protected_boundaries(rows, config)[1] == ["new_block"]
