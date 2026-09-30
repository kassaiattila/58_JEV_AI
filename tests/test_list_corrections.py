"""Tételes listák javítása (048 T1-lista): a teljes lista cseréje verzióval, cellánkénti kód-ellenőrzés, és a csomag
ellenőrzései a javított adaton (pl. a kivonat futó egyenlege).

Mesterséges adat: a számla-futás eredményét egy kitalált CIB-kivonatra cseréljük az adattárban (fizetős hívás nélkül).
"""

import json

from jav import store
from jav.runtime import worker
from tests import test_api
from tests.test_api import HUMAN, _ready_wp, _start

env = test_api.env  # a szolgáltatás-tesztek pytest-fixture-je (mesterséges PDF-ek, hamis JEV)

OPENING = "1000.00"
TXS = [
    {"booking_date": "2026-08-03", "value_date": "2026-08-03", "direction": "credit", "amount": "200", "running_balance": "1200",
     "description": "Jóváírás", "counterparty_name": None, "counterparty_account": None, "memo": None},
    # hibás kinyerés: 500 a helyes 50 helyett, ezért a futó egyenleg itt megszakad
    {"booking_date": "2026-08-04", "value_date": "2026-08-04", "direction": "debit", "amount": "500", "running_balance": "1150",
     "description": "Jutalék", "counterparty_name": None, "counterparty_account": None, "memo": None},
]


def _statement_item(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    item_id = wp["items"][0]["item_id"]
    dp = {"statement_type": "bank_account", "account_no": "10700000-00000000", "account_iban": None, "period_start": "2026-08-01",
          "period_end": "2026-08-31", "currency": "HUF", "opening_balance": OPENING, "closing_balance": "1150",
          "total_debit": None, "total_credit": None, "transactions": TXS, "line_items": []}
    with store.connect() as conn:
        flow_run = conn.execute("SELECT flow_run_id FROM run_items WHERE run_id=? AND item_id=?", (run_id, item_id)).fetchone()[0]
        conn.execute("UPDATE datapoints SET doc_type='statement_cib', datapoints=?, provenance=NULL WHERE run_id=? AND doc_id=?",
                     (json.dumps(dp), flow_run, item_id))
    return c, f"/api/runs/{run_id}/items/{item_id}"


def _check(body, name):
    return next(ch for ch in body["checks"] if ch["name"] == name)


def test_list_schema_and_checks_on_machine_data(env):
    c, url = _statement_item(env)
    body = c.get(url).json()
    lst = body["lists"]["transactions"]
    assert [col["name"] for col in lst["columns"]][:5] == ["booking_date", "value_date", "direction", "amount", "running_balance"]
    assert {col["name"]: col["kind"] for col in lst["columns"]}["amount"] == "money"
    assert next(col for col in lst["columns"] if col["name"] == "direction")["options"] == ["debit", "credit"]
    bad = _check(body, "running_balance_check")
    assert not bad["ok"] and bad["code"] == "balance.discontinuity" and bad["rows"] == {"transactions": [2]}


def test_list_correction_replaces_the_whole_list_and_rechecks(env):
    c, url = _statement_item(env)
    fixed = [dict(TXS[0]), {**TXS[1], "amount": "50"}]
    r = c.post(url + "/correction", headers=HUMAN, json={"fields": {"transactions": fixed}, "expected_revision": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["effective"]["transactions"][1]["amount"] == "50"
    assert body["extraction"]["datapoints"]["transactions"][1]["amount"] == "500"  # a gépi adat megmarad
    assert _check(body, "running_balance_check")["ok"] and _check(body, "closing_balance_check")["ok"]
    assert body["provenance"]["transactions"]["corrected"] is True

    # sor törlése / hozzáadása: a teljes lista a mentés tárgya
    r = c.post(url + "/correction", headers=HUMAN, json={"fields": {"transactions": fixed[:1]}, "expected_revision": 1})
    assert r.status_code == 200 and len(r.json()["effective"]["transactions"]) == 1
    # a lista visszaállítása a gépi értékre: kimarad a javításhalmazból
    r = c.post(url + "/correction", headers=HUMAN, json={"fields": {}, "expected_revision": 2})
    assert r.json()["effective"]["transactions"][1]["amount"] == "500"


def test_list_cells_are_checked_by_kind(env):
    c, url = _statement_item(env)
    bads = [
        [{**TXS[0], "amount": "sok"}],                 # pénz
        [{**TXS[0], "booking_date": "2026.08.03"}],    # dátum
        [{**TXS[0], "direction": "fel"}],              # felsorolt érték
        [{**TXS[0], "nincs_ilyen": "x"}],              # ismeretlen oszlop
        "nem lista",
        [["nem", "sor"]],
    ]
    for bad in bads:
        r = c.post(url + "/correction", headers=HUMAN, json={"fields": {"transactions": bad}, "expected_revision": 0})
        assert r.status_code == 422, bad
    scalar_as_list = c.post(url + "/correction", headers=HUMAN, json={"fields": {"opening_balance": ["1"]}, "expected_revision": 0})
    assert scalar_as_list.status_code == 422


def test_simple_list_and_row_list_columns():
    import pytest

    from jav import corrections, typepack

    minutes = typepack.get("meeting_minutes")
    assert corrections.list_columns(minutes, "attendees") == [{"name": "*", "kind": "text"}]
    corrections._check_list(minutes, "attendees", ["Minta Anna", None])
    with pytest.raises(ValueError):
        corrections._check_list(minutes, "attendees", [{"name": "Minta Anna"}])
    with pytest.raises(ValueError):
        corrections._check_list(minutes, "resolutions", [{"number": "1/2026", "votes_for": "sok"}])
    # a gépi sorokban előforduló, a leírásban nem szereplő tétel-mező is oszlop (szövegként)
    out = typepack.get("invoice_out")
    cols = corrections.list_columns(out, "line_items", [{"description": "x", "unit": "db"}])
    assert cols[-1] == {"name": "unit", "kind": "text"}
