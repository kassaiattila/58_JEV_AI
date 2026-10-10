"""135 (plan 134 P2): the partner of a statement line on the pairing page - the lines of one counterparty name (without
its reference numbers) grouped, the needs-no-invoice reasons a person gave earlier for that partner's lines shown as a
suggestion (never applied by itself), and the marks of several lines undone in one step.

Synthetic lines and made-up accounts only; no AI call, no network.
"""

from __future__ import annotations

import pytest

from jav import reconcile_package as rp
from tests import test_api
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_package_131 import _ids, _line_row, _package, _stmt

env = test_api.env

SHOP_1 = k2._line(memo="", counterparty_name="EXAMPLESHOP*1234 BUDAPEST", counterparty_account=None, booking_date="2026-04-05")
SHOP_2 = k2._line(memo="", counterparty_name="EXAMPLESHOP*5678 BUDAPEST", counterparty_account=None, booking_date="2026-04-12",
                  amount="250.00")
CAFE = k2._line(memo="", counterparty_name="Example Cafe", counterparty_account=None, booking_date="2026-04-20", amount="30.00")
CHEQUE_1 = k2._line(memo="", counterparty_name="POSTACSEKK", counterparty_account=None, booking_date="2026-04-07", amount="40.00")
CHEQUE_2 = k2._line(memo="", counterparty_name="POSTACSEKK", counterparty_account=None, booking_date="2026-04-21", amount="45.00")
SHOP_MAY = k2._line(memo="", counterparty_name="EXAMPLESHOP*9012 BUDAPEST", counterparty_account=None, booking_date="2026-05-03")
LINES = (SHOP_1, SHOP_2, CAFE, CHEQUE_1, CHEQUE_2, SHOP_MAY)


@pytest.fixture
def db(tmp_path):
    from jav import store

    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _setup():
    stmt = _stmt("stmt", *LINES)
    return dict(zip(("shop_1", "shop_2", "cafe", "cheque_1", "cheque_2", "shop_may"), _ids(stmt, *LINES)))


def test_a_lines_partner_is_its_name_without_reference_numbers(db):
    ids = _setup()
    ws = rp.workspace(_package())
    assert _line_row(ws, ids["shop_1"])["partner"] == _line_row(ws, ids["shop_2"])["partner"] == "exampleshop budapest"
    assert _line_row(ws, ids["cafe"])["partner"] == "example cafe"
    assert all(ln["earlier_marks"] == [] for ln in ws["lines"])  # nothing decided yet


def test_a_partners_earlier_reason_is_shown_on_its_other_lines_and_in_the_next_package(db):
    ids = _setup()
    april = _package()
    rp.mark(april, [ids["shop_1"]], category="private", note=None, actor="t")
    ws = rp.workspace(april)
    assert _line_row(ws, ids["shop_2"])["earlier_marks"] == [{"category": "private", "lines": 1}]
    assert _line_row(ws, ids["shop_1"])["earlier_marks"] == []  # a line's own mark is not its history
    assert _line_row(ws, ids["cafe"])["earlier_marks"] == []
    assert _line_row(ws, ids["shop_2"])["state"] == "open"  # a suggestion only, never applied by itself
    may = _package(start="2026-05-01", end="2026-05-31", name="May")
    assert _line_row(rp.workspace(may), ids["shop_may"])["earlier_marks"] == [{"category": "private", "lines": 1}]


def test_the_most_frequent_earlier_reason_comes_first_and_a_revoked_one_does_not_count(db):
    ids = _setup()
    wp_id = _package()
    rp.mark(wp_id, [ids["shop_1"], ids["shop_2"]], category="private", note=None, actor="t")
    rp.mark(wp_id, [ids["cafe"]], category="fee", note=None, actor="t")  # another partner's reason
    may = _package(start="2026-05-01", end="2026-05-31", name="May")
    assert _line_row(rp.workspace(may), ids["shop_may"])["earlier_marks"] == [{"category": "private", "lines": 2}]
    [gift] = rp.mark(wp_id, [ids["shop_2"]], category="other", note="a gift", actor="t")  # replaces the line's earlier mark
    assert _line_row(rp.workspace(may), ids["shop_may"])["earlier_marks"] == [
        {"category": "other", "lines": 1}, {"category": "private", "lines": 1}]
    rp.revoke(wp_id, kind="mark", ref=str(gift["id"]), actor="t")
    assert _line_row(rp.workspace(may), ids["shop_may"])["earlier_marks"] == [{"category": "private", "lines": 1}]


def test_a_line_through_a_payment_app_teaches_nothing(db):
    ids = _setup()
    wp_id = _package()
    rp.mark(wp_id, [ids["cheque_1"]], category="private", note=None, actor="t")
    ws = rp.workspace(wp_id)
    assert _line_row(ws, ids["cheque_2"])["partner"] == "postacsekk"  # still grouped by its name
    assert _line_row(ws, ids["cheque_2"])["earlier_marks"] == []  # the app pays many suppliers


def test_the_marks_of_several_lines_are_undone_in_one_step(db):
    ids = _setup()
    wp_id = _package()
    rp.mark(wp_id, [ids["shop_1"], ids["shop_2"]], category="private", note=None, actor="t")
    with pytest.raises(rp.PackageError):
        rp.unmark(wp_id, [], actor="t")
    with pytest.raises(rp.PackageError):
        rp.unmark(wp_id, [ids["cafe"]], actor="t")  # none of them is marked
    assert rp.unmark(wp_id, [ids["shop_1"], ids["shop_2"], ids["cafe"]], actor="t") == 2
    ws = rp.workspace(wp_id)
    assert all(_line_row(ws, ids[k])["state"] == "open" for k in ("shop_1", "shop_2"))
    may = _package(start="2026-05-01", end="2026-05-31", name="May")
    with pytest.raises(rp.PackageError):
        rp.unmark(may, [ids["shop_1"]], actor="t")  # outside the package's scope


def test_the_service_undoes_the_marks_of_several_lines(env):
    from tests.test_api import HUMAN

    c = env["client"]
    ids = _setup()
    wp_id = _package()
    url = f"/api/workpackages/{wp_id}/reconcile"
    r = c.post(f"{url}/mark", headers=HUMAN, json={"line_ids": [ids["shop_1"], ids["shop_2"]], "category": "private"})
    assert r.status_code == 200, r.text
    assert _line_row(r.json(), ids["cafe"])["earlier_marks"] == []
    r = c.post(f"{url}/unmark", headers=HUMAN, json={"line_ids": [ids["shop_1"], ids["shop_2"]]})
    assert r.status_code == 200, r.text
    assert {_line_row(r.json(), ids[k])["state"] for k in ("shop_1", "shop_2")} == {"open"}
    assert c.post(f"{url}/unmark", headers=HUMAN, json={"line_ids": [ids["shop_1"]]}).status_code == 422
