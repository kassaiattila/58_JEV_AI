"""127: a measurement under a hard budget (`calls.measurement`) does not read the store's earlier documents.

The duplicate check (126) and the party-role history (121) read the store only in a worker run, so that a
measurement's result does not depend on what the store holds. Both keyed on "a budget scope is set", which a budgeted
measurement has too: in a separate measurement store, without the work tables, the duplicate check stopped every
invoice with `no such table: run_items` (found by the free pre-estimate of round B). 175 (plan 170 E3): one gate in
front of every check that reads the store (`jav/ai/checks.py` `store_readable`).
"""

from decimal import Decimal

from jav.ai import checks
from jav.core import store
from jav.domains import finance
from jav.ai.models import DocumentRecord
from jav.core import calls


def test_a_measurement_is_marked_as_one_and_a_worker_run_is_not(tmp_path):
    with store.use_store(tmp_path / "m.sqlite"):
        with calls.measurement("measure-x", {"jev": Decimal("0.01")}):
            assert calls.current().measurement is True
        with calls.use_run(budget_scope="run-x"):
            assert calls.current().measurement is False


def test_the_store_is_read_in_a_worker_run_only(tmp_path):
    with store.use_store(tmp_path / "m.sqlite"):
        assert not checks.store_readable()  # the command line
        with calls.measurement("measure-x", {"jev": Decimal("0.01")}):
            assert not checks.store_readable()
        with calls.use_run(budget_scope="run-x"):
            assert checks.store_readable()
    readers = [c.name for stage in checks.STAGES for c in checks.stage(stage) if c.reads_store]
    assert readers == ["party_orientation", "duplicate", "own_tax", "statement_overlap"]


def test_a_measurement_in_a_fresh_store_gets_no_duplicate_to_do_and_does_not_fail(tmp_path):
    record = DocumentRecord(invoice_number="INV-2026-001", supplier_tax_id="12121216-2-42", supplier_name="Minta Kft.",
                       gross_total=Decimal("1270"), issue_date="2026-01-05")
    with store.use_store(tmp_path / "fresh.sqlite"), calls.measurement("measure-x", {"jev": Decimal("0.01")}):
        assert checks.cross_document(checks.Subject("doc-1", "invoice_hu", record)) == []
        assert finance.duplicate_check is checks.get("duplicate").run  # 180: the finance domain's
