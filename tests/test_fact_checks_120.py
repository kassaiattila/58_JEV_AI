"""Synthetic regressions for silent content errors (120).

Template placeholders, conflicting quantity kinds, weak JEV support and one
party filling two roles must each open a to-do instead of passing as an
unremarkable machine result. All data is synthetic; Hungarian document
vocabulary is written with explicit codepoints.
"""
from decimal import Decimal

import pytest

from jav import fact_checks, flow_native, native_results, policy, store, typepack, validators
from jav.models import FlowState, InvoiceHU
from jav.runtime import calls
from native_fixtures_109 import runtime_source, synthetic_gpt

BIRTH_NAME = "[Sz\u00fclet\u00e9si n\u00e9v]"
DATE_MASK = "\u00e9\u00e9\u00e9\u00e9. hh. nn."
AUTHORITY = "Nemzeti Ad\u00f3- \u00e9s V\u00e1mhivatal"


def run_native(tmp_path, monkeypatch, *, value, prop="birth name", support=None):
    """Run the actual native graph with a scripted GPT answer and, optionally, a scripted JEV support."""
    if support is not None:
        from jav.adapters import jev
        from typesafe_sdk import SystemOneResponse

        class Client:
            def system_one(self, *, state, questions, model):
                return SystemOneResponse.model_validate({"model": model, "usage": {"input_tokens": 100},
                    "answers": {key: {"type": "noul", "noul": support} for key in questions}})

        original = jev.JevAdapter
        monkeypatch.setattr(jev, "JevAdapter", lambda **kw: original(client=Client(), model="jev-9.9.9", **kw))
    with store.use_store(tmp_path / "native.sqlite"):
        source, ref = runtime_source(tmp_path, monkeypatch, name="statement.txt", text=f"Statement: {value}\n")
        synthetic_gpt(monkeypatch, payload={"facts": [{"entity": "person", "property": prop, "value": value,
            "state": "stated", "citations": [{"occurrence_id": "o0", "element_id": "e0", "quote": value}]}], "gaps": []})
        budget = {"openai": Decimal("1"), **({"jev": Decimal("1")} if support is not None else {})}
        with calls.measurement("native-run", budget):
            _, _, state = flow_native.build_app(work_run_id="native-run", item_id="native-item",
                graph_id="native-graph", source_path=str(source), read_path=str(source),
                original_name="statement.txt", expected_sha256=ref.source_sha256, recipe_hash="a" * 16,
                jev=support is not None, use_cache=False).run(halt_after=flow_native.TERMINALS)
        fact = native_results.get_publication("native-run", "native-item").interpretation.facts[0]
    return fact, state.data


@pytest.mark.parametrize("value,expected", [
    (BIRTH_NAME, True), (DATE_MASK, True), ("........", True), ("____", True), ("{{customer_name}}", True),
    ("<Name of the company>", True), ("Budapest, " + BIRTH_NAME, True), ("yyyy-mm-dd", True),
    ("Kov\u00e1cs Anna", False), ("[x]", False), ("[1]", False), ("Info <info@example.com>", False),
    ("2025. 03. 31.", False), ("XXX. ker\u00fclet", False),
])
def test_template_placeholders_are_recognised(value, expected):
    assert (fact_checks.placeholder_issue(value) is not None) == expected


def test_unfilled_template_text_opens_a_to_do_instead_of_passing_as_a_stated_fact(tmp_path, monkeypatch):
    fact, state = run_native(tmp_path, monkeypatch, value=BIRTH_NAME)
    assert fact.grounding == "literal_match"
    assert any("placeholder" in reason for reason in fact.reasons)
    assert state.final_status == "needs_review"
    assert "native:fact:0:requires_review" in state.review_reasons


def test_an_ordinary_value_stays_without_a_to_do(tmp_path, monkeypatch):
    fact, state = run_native(tmp_path, monkeypatch, value="Kov\u00e1cs Anna")
    assert fact.reasons == () and state.final_status == "done"


@pytest.mark.parametrize("prop,unit,value,expected", [
    ("hours", None, "2 million HUF/month", "Currency value conflicts with a time quantity; check the property and unit"),
    ("hourly rate", None, "2 million HUF/month", None),
    ("\u00f3rasz\u00e1m", None, "2 milli\u00f3 Ft/h\u00f3nap", "Currency value conflicts with a time quantity; check the property and unit"),
    ("VAT amount", None, "27%", "Percentage value conflicts with a money quantity; check the property and unit"),
    ("VAT rate", None, "27%", None),
    ("\u00c1FA kulcs", None, "27%", None),
    ("\u00e1fa \u00f6sszege", None, "27%", "Percentage value conflicts with a money quantity; check the property and unit"),
    ("issue date", None, "120 000 HUF", "Currency value conflicts with a date quantity; check the property and unit"),
    ("due date", None, "2025-03-31", None),
    ("total amount", None, "2025.03.31.", "Date value conflicts with a money quantity; check the property and unit"),
    ("contract term", "duration", "2025-01-01 \u2013 2025-12-31", None),
    ("napid\u00edj", None, "105000 Ft", None),
    ("work", "hours", "8 \u00f3ra", None),
    ("fee", None, "8 hours", "Time value conflicts with a money quantity; check the property and unit"),
    ("name", None, "120 000 HUF", None),
    ("reference", None, "A-2025/03", None),
])
def test_quantity_kind_conflicts_are_general(prop, unit, value, expected):
    assert fact_checks.quantity_issue(value, prop, unit) == expected


@pytest.mark.parametrize("support,expected", [(0.15, "native:fact:0:unsupported:0.15"), (0.5, None), (0.9, None)])
def test_a_jev_no_band_answer_opens_a_to_do_with_the_existing_band(tmp_path, monkeypatch, support, expected):
    fact, state = run_native(tmp_path, monkeypatch, value="Kov\u00e1cs Anna", prop="name", support=support)
    assert fact.semantic_support == support
    assert policy.band("native.support")["uncertain_review"] is False  # no new threshold: the default band applies
    if expected:
        assert expected in state.review_reasons and state.final_status == "needs_review"
    else:
        assert state.review_reasons == [] and state.final_status == "done"


def nav(**extra):
    return InvoiceHU(extra={"document_title": "Igazol\u00e1s", "taxpayer_name": "Minta Anna", **extra})


@pytest.mark.parametrize("employer,same", [
    (AUTHORITY + " Kiemelt Ad\u00f3z\u00f3k Igazgat\u00f3s\u00e1ga", True),
    (AUTHORITY, True),
    ("Minta Gy\u00e1rt\u00f3 Kft.", False),
    ("Ad\u00f3tan\u00e1csad\u00f3 Kft.", False),
    (None, False),
])
def test_an_authority_cannot_silently_stand_as_the_employer(employer, same):
    checks = validators.run_checks(nav(authority=AUTHORITY, employer_name=employer),
                                   typepack.get("nav_certificate").validators)
    party = [c for c in checks if c.name == "distinct_parties:employer_name"]
    assert bool(party and not party[0].ok) == same
    if same:
        assert party[0].code == "parties.same_entity" and "Minta" not in (party[0].detail or "")


# Made-up numbers from the data guard's allow list.
@pytest.mark.parametrize("supplier,buyer,same", [
    ("12121216-2-42", "HU12121216", True),
    ("13570008-1-13", "HU13570008", True),
    ("12345676-2-41", "13570008-1-13", False),
    ("DE123456789", "GB123456789", False),
    ("DE123456789", "de 123 456 789", True),
])
def test_one_tax_number_cannot_belong_to_both_parties(supplier, buyer, same):
    checks = validators.run_checks(InvoiceHU(supplier_tax_id=supplier, buyer_tax_id=buyer),
                                   [{"check": "distinct_parties", "fields": ["supplier_tax_id", "buyer_tax_id"]}])
    assert (not checks[0].ok) == same


@pytest.mark.parametrize("key", ["invoice_hu", "invoice_foreign", "invoice_out"])
def test_invoice_packs_check_both_parties_on_both_paths(key):
    pairs = [v["fields"] for v in typepack.get(key).validators if v["check"] == "distinct_parties"]
    assert ["supplier_tax_id", "buyer_tax_id"] in pairs and ["supplier_name", "buyer_name"] in pairs


def test_the_party_check_becomes_a_field_to_do():
    state = FlowState(source_path="synthetic.pdf", case_id="synthetic", arm="G", doc_type="nav_certificate")
    state.validation = validators.run_checks(nav(authority=AUTHORITY, employer_name=AUTHORITY),
                                             typepack.get("nav_certificate").validators)
    policy.apply_validation_policy(state)
    assert "validator:parties.same_entity:employer_name" in state.review_reasons
