"""090 (backlog Q-check-field, the owner's trial of 2026-10-02): the to-do of a failed field check names its field, so
Review shows it at that field, the "to fix" filter finds the field, and the field's tick closes it. Before, the to-do
was `validator:<code>` only: it stood at the top of the page, and on 11 items of the trial run it was the only to-do
while every field looked fine. A check of the whole record (totals, line items, dates) keeps its code.

Synthetic data only.
"""

from jav import corrections, policy
from jav.models import CheckResult, FlowState, InvoiceHU
from jav.validators import run_checks


def _state(*checks: CheckResult) -> FlowState:
    return FlowState(source_path="x.pdf", case_id="c", arm="G", validation=list(checks))


def test_a_failed_field_check_names_its_field():
    [check] = run_checks(InvoiceHU(supplier_tax_id="12345"), ({"check": "tax_id", "field": "supplier_tax_id"},))
    assert not check.ok and check.code == "taxid.unrecognized"
    state = _state(check)
    policy.apply_validation_policy(state)
    assert state.review_reasons == ["validator:taxid.unrecognized:supplier_tax_id"]


def test_a_record_check_keeps_its_code():
    state = _state(CheckResult(name="vat_consistency", ok=False, code="totals.mismatch"))
    policy.apply_validation_policy(state)
    assert state.review_reasons == ["validator:totals.mismatch"]


def test_review_puts_the_field_check_at_its_field():
    fields = {"supplier_tax_id", "buyer_tax_id", "gross_total"}
    assert corrections.reason_field("validator:taxid.unrecognized:supplier_tax_id", fields) == "supplier_tax_id"
    assert corrections.reason_field("validator:totals.mismatch", fields) is None
