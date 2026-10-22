"""167 (review T-2): guards that carry a rule, tested where no test reached them.

- The approval checks the run, its items and their open to-dos again under its write lock (153). The check before the
  lock catches the same states, so these tests make the change between the two, as another person's action would.
- The reconciliation's currency guards: a line paying invoices of two other currencies together, a combined payment
  without a rate for every invoice, a line that cannot pay another currency at all.
- Its freeze guards: a pair decided in an approved run is neither rejected again nor revoked; and the refusals of a
  revocation, of an empty allocation, of reopening a statement that was never approved and of accepting no source.

Synthetic documents, made-up accounts and invented rates only; no AI call, no network.
"""

from __future__ import annotations

from datetime import date

import pytest

from jav import fx, parties, reconcile, store, work, work_runs
from jav import reconcile_package as rp
from jav import reconcile_statement as rs
from tests import test_reconcile_k2_129 as k2
from tests.test_approve_race_153 import _close_reasons
from tests.test_fx_130 import Service
from tests.test_reconcile_outgoing_148 import CLUB_TAX
from tests.test_reconcile_package_131 import OWN_KEY, _stmt
from tests.test_reconcile_package_131 import _line as _pkg_line
from tests.test_supersede_runs_151 import runs  # noqa: F401 - the shared fixture: one package, an older and a newer live run

# --- the approval's checks under its lock ----------------------------------------------------------------------------------


def _cancel(c, run_id: str, item: str) -> None:
    c.execute("UPDATE runs SET status='cancelled' WHERE run_id=?", (run_id,))


def _fail_item(c, run_id: str, item: str) -> None:
    c.execute("UPDATE run_items SET status='failed' WHERE run_id=? AND item_id=?", (run_id, item))


def _reopen_reason(c, run_id: str, item: str) -> None:
    c.execute("UPDATE review_reasons SET status='open' WHERE run_id=?", (work_runs.flow_run_id(run_id, item),))


MEANWHILE = {  # what changes between the check before the lock and the one under it, and the refusal it gets
    "the run is cancelled": (_cancel, "no longer ready for approval"),
    "an item fails": (_fail_item, "has an unfinished input item"),
    "a to-do of the run opens again": (_reopen_reason, "still has open review reasons"),
}


@pytest.mark.parametrize("meanwhile", [*MEANWHILE, None])
def test_the_approval_checks_the_run_again_under_its_lock(runs, monkeypatch, meanwhile):  # noqa: F811
    run_id, item = runs["newer"], runs["items"][0]
    with store.use_store(runs["db"]):
        _close_reasons(run_id)
        real_refresh, real_begin = work_runs.refresh_run_status, work._begin
        armed: list[str] = []

        def refresh(rid: str) -> str:
            status = real_refresh(rid)
            armed.append(rid)  # the approval's next transaction is the one under its lock
            return status

        def begin(c) -> None:
            real_begin(c)
            if armed and meanwhile is not None:
                armed.clear()
                MEANWHILE[meanwhile][0](c, run_id, item)

        monkeypatch.setattr(work_runs, "refresh_run_status", refresh)
        monkeypatch.setattr(work, "_begin", begin)
        if meanwhile is None:  # nothing changes: the stand-ins alone do not stop the approval
            assert work_runs.approve_run(run_id, actor="teszt.elek")["approval"] == "approved"
            return
        with pytest.raises(work.NotReady, match=MEANWHILE[meanwhile][1]):
            work_runs.approve_run(run_id, actor="teszt.elek")
        assert work_runs.get_run(run_id)["approval"] is None


# --- the reconciliation's currency and freeze guards -----------------------------------------------------------------------

RATES = {"2026-04-01": {"CHF": (1, "398,00"), "EUR": (1, "390,00")},
         "2026-04-20": {"CHF": (1, "405,00"), "EUR": (1, "392,00")}}
COMMON = {"supplier_name": "Sporting Club", "supplier_tax_id": CLUB_TAX, "buyer_name": "Northwind Trading Ltd.",
          "issue_date": "2026-04-01", "fulfillment_date": "2026-04-01", "due_date": "2026-05-01"}


def _club() -> str:
    return parties.create("Sporting Club", identities=[("tax", parties.tax_key(CLUB_TAX), CLUB_TAX),
                                                       ("name", "sporting club", "Sporting Club")], actor="t")["id"]


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        rp.clear_cache()
        yield
        rp.clear_cache()


def _package(*, invoices: dict[str, str], rates: bool = True, statement_currency: str = "HUF") -> dict:
    """Outgoing invoices of the club (number -> currency, 5000.00 each) and one incoming line naming them all."""
    if rates:
        with fx.use_transport(Service(RATES)):
            fx.fetch(date(2026, 4, 1), date(2026, 4, 20), ["CHF", "EUR"])
    club = _club()
    ids = {number: k2._save(number, k2._invoice(number=number, amount="5000.00", currency=currency, **COMMON),
                            doc_type="invoice_out") for number, currency in invoices.items()}
    line = _pkg_line(memo=" ".join(invoices), amount="4000000.00", direction="credit", day="2026-04-20",
                     counterparty_name="Northwind Trading")
    if statement_currency == "HUF":
        _stmt("stmt", line)
    else:
        k2._save("stmt", {**k2._statement(line), "account_no": k2.OWN, "currency": statement_currency},
                 doc_type="statement_cib", validation=k2.VERIFIED)
    wp = rp.create(name="April", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30",
                   actor="reviewer", party_id=club)["workpackage_id"]
    (line_row,) = rp.workspace(wp)["lines"]
    return {"wp": wp, "invoices": ids, "line": line_row["id"]}


def _pairs(pkg: dict) -> list[dict]:
    return [{"invoice_doc_id": doc, "line_id": pkg["line"]} for doc in pkg["invoices"].values()]


@pytest.mark.parametrize("invoices, rates, statement_currency, message", [
    ({"OUT-1": "CHF", "OUT-2": "EUR"}, True, "HUF", "only from a bank account, in one currency"),
    ({"OUT-1": "CHF", "OUT-2": "CHF"}, False, "HUF", "needs an exchange rate for every invoice"),
    ({"OUT-1": "CHF"}, True, "EUR", "cannot pay an invoice of another currency"),
], ids=["two other currencies", "no rate", "a euro line for a franc invoice"])
def test_an_allocation_across_currencies_is_refused_where_it_cannot_be_converted(db, invoices, rates,
                                                                                 statement_currency, message):
    pkg = _package(invoices=invoices, rates=rates, statement_currency=statement_currency)
    with pytest.raises(rp.PackageError, match=message):
        rp.allocate(pkg["wp"], _pairs(pkg), note="a reason", actor="reviewer")
    assert rp.workspace(pkg["wp"])["lines"][0]["allocations"] == []


def test_two_franc_invoices_with_their_rates_are_allocated_together(db):
    """The control of the cases above: the same step with one other currency and its rates goes through."""
    pkg = _package(invoices={"OUT-1": "CHF", "OUT-2": "CHF"})
    assert len(rp.allocate(pkg["wp"], _pairs(pkg), note="a reason", actor="reviewer")) == 2


def _decided_in_an_approved_run(pkg: dict) -> str:
    """A 'not this one' decision on the pair recorded in an approved run (as the run-based review recorded it)."""
    k2._run(k2.RUN, [], approved=True)
    doc = pkg["invoices"]["OUT-1"]
    key = reconcile.pair_key(doc, pkg["line"])
    with store.connect() as c:
        c.execute("INSERT INTO reconcile_decisions(pair_key, invoice_doc_id, statement_doc_id, line_id, decision, run_id,"
                  " actor, decided_at) VALUES (?,?,?,?,?,?,?,?)",
                  (key, doc, k2._id("stmt"), pkg["line"], "not_this", k2.RUN, "t", "2026-04-21T10:00:00+00:00"))
    rp.clear_cache()
    return key


def test_a_pair_decided_in_an_approved_run_is_frozen(db):
    pkg = _package(invoices={"OUT-1": "CHF"})
    key = _decided_in_an_approved_run(pkg)
    with pytest.raises(work.RevisionConflict, match="frozen"):
        rp.reject(pkg["wp"], pkg["invoices"]["OUT-1"], pkg["line"], note="not this one", actor="reviewer")
    with pytest.raises(work.RevisionConflict, match="frozen"):
        rp.revoke(pkg["wp"], kind="decision", ref=key, actor="reviewer")
    with store.connect() as c:
        row = c.execute("SELECT run_id, actor FROM reconcile_decisions WHERE pair_key=?", (key,)).fetchone()
    assert (row["run_id"], row["actor"]) == (k2.RUN, "t")  # neither the rejection nor the revocation wrote over it


@pytest.mark.parametrize("call, error, message", [
    (lambda pkg: rp.allocate(pkg["wp"], [], note=None, actor="r"), rp.PackageError, "no pair to allocate"),
    (lambda pkg: rp.revoke(pkg["wp"], kind="everything", ref="1", actor="r"), rp.PackageError, "unknown kind"),
    (lambda pkg: rp.revoke(pkg["wp"], kind="decision", ref="no-such-pair", actor="r"), KeyError, "no-such-pair"),
    (lambda pkg: rp.revoke(pkg["wp"], kind="allocation", ref="999", actor="r"), KeyError, "999"),
    (lambda pkg: rs.reopen(pkg["wp"], note="a reason", actor="r"), rp.PackageError, "no approved statement to reopen"),
    (lambda pkg: rs.accept_sources(pkg["wp"], [], actor="r"), rp.PackageError, "no document to accept"),
], ids=["empty allocation", "unknown revocation", "unknown decision", "unknown allocation", "reopen unapproved",
        "accept nothing"])
def test_a_reconciliation_step_without_its_object_is_refused(db, call, error, message):
    pkg = _package(invoices={"OUT-1": "CHF"})
    with pytest.raises(error, match=message):
        call(pkg)
