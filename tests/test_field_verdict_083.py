"""✓ and ✗ next to each field in Review (083).

The owner asked for a tick and a cross right next to each field's value instead of resolving to-dos at the top of the
panel. A save can now confirm fields (`confirm`): the new correction version records the confirmed value of each such
field (a person checked it), and the run's own open to-dos on those fields are resolved in the same request. A
confirmation lasts while the field's value stays the same. Each to-do carries the field it is about (`field`), so the
UI can show it at the field. Synthetic documents and a fake JEV, no paid calls.
"""

from jav import store, work
from jav.runtime import worker
from tests import test_api
from tests.test_api import HUMAN, _ready_wp, _start

env = test_api.env


def _item(env, reasons):
    """A processed invoice item with the given to-dos raised in its own run (and nothing else from the test)."""
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    item_id = wp["items"][0]["item_id"]
    store.review_enqueue(subject_kind="document", subject_id=item_id, run_id=work.flow_run_id(run_id, item_id),
                         reasons=reasons, producer="test083")
    return c, run_id, item_id, f"/api/runs/{run_id}/items/{item_id}"


def _open(body):
    return sorted(r["reason"] for r in body["open_reasons"])


def test_the_to_dos_carry_their_field(env):
    c, run_id, item_id, url = _item(env, ["pick:low_conf:invoice_number:0.52", "money:separator_ambiguous:vat_total:'0.00'",
                                          "parties:same_tax_id", "line_items[3].gross_amount:unparseable:'null'"])
    by_reason = {r["reason"]: r["field"] for r in c.get(url).json()["open_reasons"]}
    assert by_reason["pick:low_conf:invoice_number:0.52"] == "invoice_number"
    assert by_reason["money:separator_ambiguous:vat_total:'0.00'"] == "vat_total"
    assert by_reason["parties:same_tax_id"] is None  # about the document, not one field
    assert by_reason["line_items[3].gross_amount:unparseable:'null'"] is None  # a line item, not a simple field


def test_confirming_a_field_records_it_and_closes_its_own_to_dos(env):
    c, run_id, item_id, url = _item(env, ["pick:low_conf:invoice_number:0.52", "jev:unsupported:invoice_number",
                                          "pick:low_conf:payment_iban:0.40", "parties:same_tax_id"])
    machine = c.get(url).json()["effective"]["invoice_number"]
    r = c.post(f"{url}/correction", headers=HUMAN, json={"fields": {}, "expected_revision": 0, "confirm": ["invoice_number"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["correction"]["revision"] == 1 and body["correction"]["confirmed"] == {"invoice_number": machine}
    assert body["effective"]["invoice_number"] == machine  # nothing was changed, only confirmed
    remaining = _open(body)
    assert "pick:low_conf:payment_iban:0.40" in remaining and "parties:same_tax_id" in remaining
    assert not [x for x in remaining if ":invoice_number" in x]
    with store.connect() as conn:
        closed = conn.execute("SELECT actor, resolution FROM review_reasons WHERE reason='jev:unsupported:invoice_number'").fetchone()
    assert closed["actor"] == "teszt.elek" and '"verdict": "confirmed"' in closed["resolution"] and '"field": "invoice_number"' in closed["resolution"]


def test_confirming_a_typed_value_corrects_and_confirms_it(env):
    c, run_id, item_id, url = _item(env, ["pick:low_conf:invoice_number:0.52"])
    body = c.post(f"{url}/correction", headers=HUMAN, json={"fields": {"invoice_number": "UJ-1"}, "expected_revision": 0,
                                                               "confirm": ["invoice_number"]}).json()
    assert body["effective"]["invoice_number"] == "UJ-1" and body["correction"]["confirmed"] == {"invoice_number": "UJ-1"}
    assert not [x for x in _open(body) if ":invoice_number" in x]


def test_an_empty_confirmed_value_means_the_value_is_not_on_the_document(env):
    c, run_id, item_id, url = _item(env, ["pick:absent_but_chosen:payment_iban:0.10"])
    body = c.post(f"{url}/correction", headers=HUMAN, json={"fields": {"payment_iban": None}, "expected_revision": 0,
                                                               "confirm": ["payment_iban"]}).json()
    assert body["effective"]["payment_iban"] is None and body["correction"]["confirmed"] == {"payment_iban": None}
    assert not [x for x in _open(body) if ":payment_iban" in x]


def test_a_confirmation_lasts_until_the_value_changes(env):
    c, run_id, item_id, url = _item(env, [])
    first = c.post(f"{url}/correction", headers=HUMAN, json={"fields": {}, "expected_revision": 0,
                                                                "confirm": ["invoice_number", "supplier_name"]}).json()
    assert set(first["correction"]["confirmed"]) == {"invoice_number", "supplier_name"}
    # a later save (the bulk save, without confirming) changes the supplier's name: that confirmation goes, the other stays
    second = c.post(f"{url}/correction", headers=HUMAN, json={"fields": {"supplier_name": "Other Ltd."}, "expected_revision": 1}).json()
    assert set(second["correction"]["confirmed"]) == {"invoice_number"}


def test_an_earlier_runs_to_do_on_the_same_field_is_closed_too_and_other_earlier_ones_stay(env):
    """The owner's decision (083): a person has now checked the field, so an earlier run's to-do on the same field of
    the same document is settled too; the resolution names the run where the field was checked."""
    c, run_id, item_id, url = _item(env, ["pick:low_conf:invoice_number:0.52"])
    store.review_enqueue(subject_kind="document", subject_id=item_id, run_id="golden-083",
                         reasons=["pick:low_conf:invoice_number:0.47", "pick:low_conf:payment_iban:0.40", "parties:same_name"], producer="old083")
    body = c.post(f"{url}/correction", headers=HUMAN, json={"fields": {}, "expected_revision": 0, "confirm": ["invoice_number"]}).json()
    assert not [r for r in body["open_reasons"] if r["field"] == "invoice_number"]
    assert sorted(r["reason"] for r in body["earlier_open_reasons"]) == ["parties:same_name", "pick:low_conf:payment_iban:0.40"]
    with store.connect() as conn:
        closed = conn.execute("SELECT resolution FROM review_reasons WHERE reason='pick:low_conf:invoice_number:0.47'").fetchone()
    assert f'"run_id": "{run_id}"' in closed["resolution"]


def test_only_simple_fields_of_the_pack_can_be_confirmed(env):
    c, run_id, item_id, url = _item(env, [])
    for bad in (["nincs_ilyen_mezo"], ["line_items"]):
        r = c.post(f"{url}/correction", headers=HUMAN, json={"fields": {}, "expected_revision": 0, "confirm": bad})
        assert r.status_code == 422, bad
    assert c.get(url).json()["correction"]["revision"] == 0
