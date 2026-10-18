"""174 (review 160, J-160-F): the reconciliation's remaining fixes after plan 170 L2, each pinned by the review's
item number. Synthetic data only."""

from __future__ import annotations

from jav import reconcile


def test_m10_a_numbers_whole_word_pattern_is_compiled_once() -> None:
    """M-10: a pairing compared every invoice number with every line in its window and compiled the number's pattern
    each time (`re` keeps 512): 54 % of 27 s for 1 500 invoices and 3 000 lines."""
    reconcile._whole_word.cache_clear()
    for _ in range(3):
        assert reconcile._number_in("INV-2026/001", "Payment INV 2026 001 thank you")
    assert not reconcile._number_in("INV-2026/001", "Payment INV-2025/001")
    info = reconcile._whole_word.cache_info()
    assert (info.misses, info.hits) == (1, 3)


def _candidate(invoice: str, *, combined: list[str] | None = None, multiple: bool = False, review: bool = False) -> dict:
    return {"invoice_id": invoice, "proposed": True, "multiple_candidates": multiple, "source_review_required": review,
            "combined": combined}


def test_m5_a_combined_payment_is_a_sure_pair_whole_or_not_at_all() -> None:
    """M-5: when one invoice of a combined payment (300 = 100 + 200) had another proposal too, the sure pairs held the
    other half alone; that pair left a rest on the line, needed a reason, and the whole bulk acceptance failed."""
    from jav import reconcile_package as rp

    group = ["inv-a", "inv-b"]
    lines = [
        {"id": "line-combined", "candidates": [_candidate("inv-a", combined=group), _candidate("inv-b", combined=group, multiple=True)]},
        {"id": "line-whole", "candidates": [_candidate("inv-c", combined=["inv-c", "inv-d"]), _candidate("inv-d", combined=["inv-c", "inv-d"])]},
        {"id": "line-single", "candidates": [_candidate("inv-e")]},
        {"id": "line-locked", "locked": True, "candidates": [_candidate("inv-f")]},
        {"id": "line-review", "candidates": [_candidate("inv-g", review=True)]},
    ]
    assert rp.sure_pairs(lines) == [{"invoice_doc_id": "inv-c", "line_id": "line-whole"},
                                    {"invoice_doc_id": "inv-d", "line_id": "line-whole"},
                                    {"invoice_doc_id": "inv-e", "line_id": "line-single"}]


def _line(lid: str, name: str | None, memo: str | None = None, day: str = "2026-04-10", amount: str = "100.00") -> dict:
    return {"id": lid, "booking_date": day, "amount": amount, "direction": "debit", "counterparty_name": name,
            "memo": memo, "description": "Transfer"}


def test_m6_repeated_lines_follow_their_partner_to_the_new_statement() -> None:
    """M-6: after a statement was replaced, the decisions of two lines of the same day, amount and direction moved to
    the new lines in their order, so ACME's decision could land on BETA's line."""
    from jav import statement_months as sm

    old = [_line("o1", "ACME Kft."), _line("o2", "BETA Zrt."), _line("o3", "Unique", day="2026-04-11")]
    new = [_line("n1", "BETA ZRT", "inv 22"), _line("n2", "ACME KFT", "inv 11"), _line("n3", "Unique", day="2026-04-11")]
    assert sm.match_lines(old, new, strict=True) == ({"o1": "n2", "o2": "n1", "o3": "n3"}, [])


def test_m6_identical_lines_keep_their_order_and_an_unclear_pair_is_left_to_a_person() -> None:
    from jav import statement_months as sm

    same = [_line("o1", "Card fee"), _line("o2", "Card fee")]
    assert sm.match_lines(same, [_line("n1", "Card fee"), _line("n2", "Card fee")], strict=True) == ({"o1": "n1", "o2": "n2"}, [])
    nameless = [_line("o1", None), _line("o2", None)]
    named = [_line("n1", "ACME Kft."), _line("n2", "BETA Zrt.")]
    assert sm.match_lines(nameless, named, strict=True) == ({}, ["o1", "o2"])  # which decision was whose: a person decides
    assert sm.match_lines(nameless, named) == ({"o1": "n1", "o2": "n2"}, [])  # the same lines all the same (144, 154)


def test_m7_a_folders_monthly_exports_of_one_account_are_all_kept_and_their_ids_stay(tmp_path) -> None:
    """M-7: a folder of one account's monthly exports kept the first month only ("already in another file"), because
    an account's key held no period. The statement file still holds the key without the period, so the id of a
    statement read before stays the same."""
    import json

    from jav import statement_table as st
    from tests import test_statement_table_136 as t136

    folder = tmp_path / "exports"
    folder.mkdir()
    jan = t136._workbook(folder, name="statement_2026-01-01_2026-03-31_hu.xlsx")
    t136._workbook(folder, name="statement_2026-04-01_2026-06-30_hu.xlsx")
    reading = st.read(folder)
    huf = [a for a in reading.accounts if (a.title, a.currency, a.occurrence) == ("Személyes számla", "HUF", 1)]
    assert sorted(a.statement["period_start"] for a in huf) == ["2026-01-01", "2026-04-01"]
    assert not [s for s in reading.skipped if "already in another file" in s["reason"]]
    alone = next(a for a in st.read(jan).accounts if (a.title, a.currency, a.occurrence) == ("Személyes számla", "HUF", 1))
    first = next(a for a in huf if a.statement["period_start"] == "2026-01-01")
    assert st.derived_id(reading, first) == st.derived_id(st.read(jan), alone)
    assert json.loads(st.derived_bytes(reading, first))["account"]["key"] == t136.IBAN_HUF.replace(" ", "") + ":HUF"


def test_m8_a_very_long_cell_is_never_taken_for_an_account_title() -> None:
    """M-8: the account-title pattern ran in quadratic time on a long cell of spaces (16 000 characters 0.63 s; a
    131 000-character CSV cell about 40 s in the service's process). A title is short; a longer cell is no title."""
    import time

    from jav import statement_table as st

    profile = next(p for p in st._conf()["profiles"] if p["name"] == "revolut_consolidated_hu")
    started = time.perf_counter()
    blocks = st._blocks([["a" + " " * 131_000 + "b"], ["Személyes számla (HUF)"]], profile)
    assert time.perf_counter() - started < 0.5
    assert [(b.name, b.currency) for b in blocks] == [("Személyes számla", "HUF")]


def _rows_of(start: str, first: str, step: str, days: int, currency: str = "EUR") -> list:
    from datetime import date, timedelta
    from decimal import Decimal

    day, rate, out = date.fromisoformat(start), Decimal(first), []
    for _ in range(days):
        out.append((day, currency, 1, rate))
        day, rate = day + timedelta(days=1), (rate * (1 + Decimal(step))).quantize(Decimal("0.01"))
    return out


def test_m11_a_drift_built_from_allowed_daily_steps_is_refused() -> None:
    """M-11: each day was checked against the day before only, so 9 % a day within one response took 400 Ft/EUR to
    947 Ft/EUR. Each rate is also checked against the first known one (the stored day before, else the response's
    first day): within the daily limit times the square root of the days since."""
    from datetime import date
    from decimal import Decimal

    import pytest

    from jav import fx

    drift = _rows_of("2026-04-01", "400.00", "0.09", 11)
    assert drift[-1][3] > Decimal("940")
    with pytest.raises(fx.FxRefusedError, match="since"):
        fx.plausible(drift, start=date(2026, 4, 1), end=date(2026, 4, 30), currencies={"EUR"}, previous={})
    stored = {"EUR": (date(2026, 3, 31), Decimal("400.00"))}
    with pytest.raises(fx.FxRefusedError, match="since"):
        fx.plausible(_rows_of("2026-04-01", "430.00", "0.09", 4), start=date(2026, 4, 1), end=date(2026, 4, 30),
                     currencies={"EUR"}, previous=stored)
    fx.plausible(_rows_of("2026-04-01", "400.00", "0.01", 14), start=date(2026, 4, 1), end=date(2026, 4, 30),
                 currencies={"EUR"}, previous=stored)  # a real fortnight's move passes


def _csv_export(path, *, total: bool):
    from tests import test_statement_table_136 as t136

    rows = [["Személyes számla (HUF)"], ["Tranzakciókivonat"], t136.HEADER, *t136.HUF_LINES]
    rows += [t136._total(t136.HUF_LINES)] if total else []
    path.write_text("\n".join(t136._as_csv(r) if len(r) > 1 else r[0] for r in rows) + "\n", encoding="utf-8")
    return path


def test_m12_balances_taken_from_the_lines_without_a_total_cannot_vouch_for_the_first_and_last_lines(tmp_path) -> None:
    """M-12: an export printing neither balances nor a total row got its opening and closing balance from its own
    lines, so the closing check always held, and the coverage counted as checked even with its first or last line
    missing. Such a statement says so (`balances` `lines`); a total row still vouches for the lines."""
    import json

    from jav import statement_table as st

    bare = st.read(_csv_export(tmp_path / "bare.csv", total=False)).accounts[0]
    totalled_reading = st.read(_csv_export(tmp_path / "totalled.csv", total=True))
    totalled = totalled_reading.accounts[0]
    assert (bare.balances, totalled.balances) == ("lines", "export")
    assert "balances" not in json.loads(st.derived_bytes(totalled_reading, totalled))  # its file and id as before


def test_m12_such_a_statement_is_a_to_do_and_not_checked_coverage(tmp_path) -> None:
    import json

    from jav import reconcile, store, work
    from tests.test_flow_statement_table_136 import _run_all

    with store.use_store(tmp_path / "s.sqlite"):
        export = _csv_export(tmp_path / "bare.csv", total=False)
        wp = work.create_workpackage(name="Statements", source_kind="manual", source_ref=None)
        wp = work.add_statement_tables(wp["id"], export, ["Személyes számla (HUF)#1"], expected_revision=wp["revision"])
        run_id = _run_all(wp["id"])
        item = work.get_run(run_id)["items"][0]
        reasons = {r["reason"] for r in work.item_reasons(run_id, item["item_id"])["run"]}
        assert "statement_table:balance_from_lines" in reasons
        assert not any(r.startswith("validator:closing.") for r in reasons)
        with store.connect() as c:
            validation = c.execute("SELECT validation FROM datapoints").fetchone()[0]
        assert reconcile.verified(json.loads(validation)) is False


def test_m13_an_approval_that_lands_just_before_a_scope_change_stops_it(tmp_path, monkeypatch) -> None:
    """M-13: the scope change checked for an approved version before its write transaction, so an approval made in
    between was overwritten by the new scope. The check now runs inside the transaction."""
    import pytest

    from jav import reconcile_package as rp, store
    from tests.test_reconcile_package_131 import OWN_KEY, _line, _package, _stmt

    with store.use_store(tmp_path / "r.sqlite"):
        _stmt("stmt", _line())
        wp_id = _package()
        real = store.begin_immediate

        def approval_first(c):  # another person's approval commits just before this write begins
            with store.connect() as other:
                other.execute("INSERT INTO reconcile_versions(workpackage_id, version, content, fingerprint, line_ids,"
                              " approved_by, approved_at) VALUES (?, 1, '{}', 'x', '[]', 'Approver', '2026-10-18T10:00:00+00:00')",
                              (wp_id,))
            monkeypatch.setattr(store, "begin_immediate", real)
            real(c)

        monkeypatch.setattr(store, "begin_immediate", approval_first)
        with pytest.raises(rp.Locked):
            rp.set_scope(wp_id, accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-05-31",
                         expected_revision=1, actor="t")
        assert rp.scope(wp_id)["revision"] == 1
