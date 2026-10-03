"""Semantic proposals cannot invent evidence or silently omit source bytes."""
import pytest
import os

from jav.readers.interpretation import ProposedExtraction, ground, score, source_view
from jav.readers.pipeline import read_files

pytest.importorskip("docx", reason="Native reader dependencies await integration")
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object reader boundary")


@pytest.fixture
def delivery(tmp_path):
    source = tmp_path / "order.txt"
    source.write_text("Order code: 0007\nQuantity: 3", encoding="utf-8")
    return read_files([source])


def proposal(value="0007", occurrence="o0", quote="Order code: 0007"):
    return ProposedExtraction.model_validate_json(__import__("json").dumps({"facts": [{
        "entity": "order", "property": "code", "value": value, "state": "stated",
        "citations": [{"occurrence_id": occurrence, "element_id": "e0", "quote": quote}]}]}))


def test_verbatim_grounding_preserves_leading_zero(delivery):
    result = ground(delivery, proposal(), provider="offline", model="synthetic", execution="synthetic_test")
    assert result.facts[0].grounding == "literal_match"
    assert result.review_status == "not_reviewed"
    assert result.correctness == "not_established"
    assert score(result, [("order", "code", "0007")])["recall"] == 1


@pytest.mark.parametrize("changes", [{"value": "9999"}, {"occurrence": "other"}, {"quote": "Invented quote 0007"}])
def test_unbound_or_invented_evidence_is_rejected(delivery, changes):
    result = ground(delivery, proposal(**changes), provider="offline", model="synthetic", execution="synthetic_test")
    assert result.facts[0].grounding == "rejected"
    assert score(result, [("order", "code", "0007")])["false_negative"] == 1


def test_transfer_limit_stops_before_a_provider_call(delivery):
    with pytest.raises(ValueError, match="no content was sent"):
        source_view(delivery, max_bytes=20)


def test_matching_quote_does_not_prove_business_role(delivery):
    result = ground(delivery, proposal(), provider="offline", model="synthetic", execution="synthetic_test")
    metrics = score(result, [("different-entity", "code", "0007")])
    assert metrics["false_positive"] == 1
    assert metrics["false_negative"] == 1
