"""133 (backlog F-own-parties; DECISIONS 133): a reconciliation package is one own party's - its invoices first, the
other parties' ones behind a switch, the unassigned ones everywhere - and the parties' overview and suggestions from
the store's documents.

Synthetic documents, made-up names, tax numbers and accounts only; no AI call, no network.
"""

from __future__ import annotations

import pytest

from jav import parties, party_views, reconcile, reconcile_package as rp, store, work
from tests import test_api
from tests import test_reconcile_k2_129 as k2
from tests import test_reconcile_package_131 as p131

OWN_KEY = p131.OWN_KEY
HOME_TAX = "12121216-2-42"  # a sample number on the data guard's allow list
CLUB_TAX = "13570008-1-13"  # a sample number on the data guard's allow list


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _parties():
    home = parties.create("Example Home", identities=[("name", "jane example", "Jane Example"), ("account", OWN_KEY, k2.OWN)], actor="t")
    club = parties.create("Sporting Club", identities=[("tax", parties.tax_key(CLUB_TAX), CLUB_TAX)], actor="t")
    return home["id"], club["id"]


def _docs():
    mine = k2._save("mine", k2._invoice(buyer_name="Jane Example"))
    club = k2._save("club", k2._invoice(number="CLUB-77", amount="250.00", buyer_name="Sporting Club", buyer_tax_id=CLUB_TAX))
    nobody = k2._save("nobody", k2._invoice(number="NB-5", amount="40.00"))
    stmt = p131._stmt("stmt", p131._line(), p131._line(amount="250.00", memo="CLUB-77"))
    return mine, club, nobody, stmt


def test_a_package_shows_its_partys_invoices_and_the_unassigned_ones(db):
    home, club = _parties()
    mine, club_inv, nobody, stmt = _docs()
    wp_id = rp.create(name="Home", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="t", party_id=home)["workpackage_id"]
    ws = rp.workspace(wp_id)
    assert ws["scope"]["party"] == {"id": home, "name": "Example Home"}
    rows = {i["id"]: i for i in ws["invoices"]}
    assert (rows[mine]["own"], rows[mine]["party"]) == (True, {"id": home, "name": "Example Home", "how": "name"})
    assert (rows[nobody]["own"], rows[nobody]["party"]) == (True, None)
    assert (rows[club_inv]["own"], rows[club_inv]["party"]["name"]) == (False, "Sporting Club")
    first, second = p131._ids(stmt, p131._line(), p131._line(amount="250.00", memo="CLUB-77"))
    club_line = p131._line_row(ws, second)
    assert club_line["state"] == "open" and club_inv not in {c["invoice_id"] for c in club_line["candidates"]}
    assert club_line["other_candidates"] == [{"invoice_id": club_inv, "party": "Sporting Club"}]
    assert p131._line_row(ws, first)["state"] == "proposed"
    assert ws["counts"]["other_invoices"] == 1
    assert rp.accept_proposed(wp_id, actor="t") == 1  # the club's pair waits for a person
    assert p131._line_row(rp.workspace(wp_id), second)["state"] == "open"
    rp.allocate(wp_id, [{"invoice_doc_id": club_inv, "line_id": second}], note=None, actor="t")  # a person may pair it
    assert p131._line_row(rp.workspace(wp_id), second)["state"] == "allocated"


def test_a_package_without_a_party_takes_every_invoice_as_its_own(db):
    _parties()
    _mine, club_inv, _nobody, _stmt = _docs()
    ws = rp.workspace(p131._package())
    assert ws["scope"]["party"] is None and all(i["own"] for i in ws["invoices"])
    assert ws["counts"]["other_invoices"] == 0
    assert any(c["invoice_id"] == club_inv for ln in ws["lines"] for c in ln["candidates"])


def test_the_scopes_party_is_checked_changed_and_shown_with_the_accounts(db):
    home, club = _parties()
    _docs()
    with pytest.raises(rp.PackageError):
        rp.create(name="X", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="t", party_id="party-000000000000")
    wp_id = rp.create(name="Home", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="t", party_id=home)["workpackage_id"]
    rp.set_scope(wp_id, accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", expected_revision=1, actor="t", party_id=club)
    assert rp.scope(wp_id)["party"]["name"] == "Sporting Club"
    [acct] = rp.accounts()
    assert acct["party"] == {"id": home, "name": "Example Home"}


def test_a_party_a_package_uses_is_kept_and_a_merge_moves_the_package(db):
    home, club = _parties()
    _docs()
    wp_id = rp.create(name="Club", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="t", party_id=club)["workpackage_id"]
    with pytest.raises(parties.PartyError):
        parties.delete(club, actor="t")
    parties.merge(club, home, actor="t")
    assert rp.scope(wp_id)["party"] == {"id": home, "name": "Example Home"}


def test_the_overview_counts_and_the_suggestions_are_accepted_as_they_stand(db):
    for n in range(3):
        k2._save(f"home-{n}", k2._invoice(number=f"H-{n}", buyer_name="Jane Example", issue_date=f"2026-0{n + 4}-01"))
    for n in range(2):
        k2._save(f"club-{n}", k2._invoice(number=f"C-{n}", buyer_name="Sporting Club", buyer_tax_id=CLUB_TAX))
    k2._save("ticket", k2._invoice(number="T-1", buyer_name="Example Supplier Kft."))  # the supplier misread as the buyer
    view = party_views.overview()
    assert view["parties"] == [] and view["invoices"] == 6 and view["buyer_is_supplier"] == 1
    names = {s["name"]: s for s in view["suggestions"]}
    assert set(names) == {"Jane Example", "Sporting Club"} and names["Jane Example"]["invoices"] == 3
    with pytest.raises(work.RevisionConflict):
        party_views.accept(["0000000000000000"], actor="t")
    party_views.accept([names["Jane Example"]["id"]], names={names["Jane Example"]["id"]: "Example Home"}, actor="t")
    view = party_views.overview()
    [home] = view["parties"]
    assert (home["name"], home["invoices"], home["first"], home["last"]) == ("Example Home", 3, "2026-04-01", "2026-06-01")
    assert home["identities"] == [{**home["identities"][0], "kind": "name", "key": "example jane", "invoices": 3}]
    assert [s["name"] for s in view["suggestions"]] == ["Sporting Club"]
    assert view["unclaimed_invoices"] == 3


def test_the_snapshot_reads_the_buyer_of_an_invoice_and_of_a_bill(db):
    k2._save("inv", k2._invoice(buyer_name="Jane Example", buyer_tax_id=HOME_TAX))
    k2._save("bill", k2._invoice(number="B-1", customer_name="Mary Sample"), doc_type="villamos_energia_szamla")
    got = {i["number"]: (i["buyer_name"], i["buyer_tax_id"]) for i in reconcile.snapshot()["invoices"]}
    assert got == {"INV-0001": ("Jane Example", HOME_TAX), "B-1": ("Mary Sample", None)}


# --- the service ---------------------------------------------------------------------------------------------------------

env = test_api.env


def test_the_service_accepts_the_suggestions_and_rearranges_the_parties(env):
    c, human = env["client"], test_api.HUMAN
    for n in range(2):
        k2._save(f"home-{n}", k2._invoice(number=f"H-{n}", buyer_name="Jane Example"))
        k2._save(f"club-{n}", k2._invoice(number=f"C-{n}", buyer_name="Sporting Club", buyer_tax_id=CLUB_TAX))
    ids = {s["name"]: s["id"] for s in c.get("/api/parties").json()["suggestions"]}
    assert set(ids) == {"Jane Example", "Sporting Club"}
    assert c.post("/api/parties/accept", json={"ids": list(ids.values())}).status_code == 422  # a person decides
    r = c.post("/api/parties/accept", headers=human, json={"ids": list(ids.values()), "names": {ids["Jane Example"]: "Example Home"}})
    assert r.status_code == 200, r.text
    by = {p["name"]: p for p in r.json()["parties"]}
    home, club = by["Example Home"]["id"], by["Sporting Club"]["id"]
    assert r.json()["suggestions"] == [] and by["Sporting Club"]["invoices"] == 2
    r = c.post("/api/parties/identities", headers=human,
               json={"kind": "name", "key": "club sporting", "label": "Sporting Club", "action": "assign", "party_id": home})
    assert {i["key"] for i in {p["name"]: p for p in r.json()["parties"]}["Example Home"]["identities"]} == {"example jane", "club sporting"}
    r = c.post("/api/parties/identities", headers=human, json={"kind": "name", "key": "example jane", "label": "Jane Example", "action": "dismiss"})
    assert [d["key"] for d in r.json()["dismissed"]] == ["example jane"]
    assert c.post("/api/parties/identities", headers=human, json={"kind": "name", "key": "x y", "label": "X Y", "action": "assign"}).status_code == 422
    r = c.post(f"/api/parties/{club}/merge", headers=human, json={"into": home})
    assert [p["name"] for p in r.json()["parties"]] == ["Example Home"]
    r = c.post(f"/api/parties/{home}/rename", headers=human, json={"name": "Household"})
    assert r.json()["parties"][0]["name"] == "Household"
    r = c.post("/api/parties", headers=human, json={"name": "New Party", "identities": [{"kind": "name", "key": "New Party", "label": "New Party"}]})
    assert r.status_code == 201 and {p["name"] for p in r.json()["parties"]} == {"Household", "New Party"}
    assert c.post(f"/api/parties/{home}/delete", headers=human, json={}).status_code == 200
    assert c.post("/api/parties/party-000000000000/delete", headers=human, json={}).status_code == 404
