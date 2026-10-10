"""133 (backlog F-own-parties; DECISIONS 133): the own parties - who the buyer of an invoice and the holder of an
account is, proposed from the data and rearranged by a person at any time.

Made-up names, tax numbers and accounts only; no AI call.
"""

from __future__ import annotations

import pytest

from jav import parties, store

COMPANY_TAX = "12121216-2-42"  # a sample number on the data guard's allow list
CLUB_TAX = "13570008-1-13"  # a sample number on the data guard's allow list


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "p.sqlite"):
        yield


def _inv(name, tax=None, *, supplier="Example Supplier Kft.", supplier_tax="12345676-2-41", n=1, start=0):
    return [{"doc_id": f"{name}-{tax}-{start + i}", "name": name, "tax_id": tax, "supplier_name": supplier,
             "supplier_tax_id": supplier_tax} for i in range(n)]


def _by_name(result):
    return {s["name"]: s for s in result["suggestions"]}


def _keys(suggestion, kind):
    return sorted(i["key"] for i in suggestion["identities"] if i["kind"] == kind)


# --- the keys ------------------------------------------------------------------------------------------------------------


def test_a_name_variant_ignores_order_legal_forms_and_numbers():
    assert parties.name_key("Jane Example") == parties.name_key("EXAMPLE, Jane") == "example jane"
    assert parties.name_key("Example Trading Kft. 1141 Budapest") == "budapest example trading"
    assert parties.name_key("Kft. 12") is None and parties.name_key(None) is None
    assert parties.name_key("Examp1etrade Kft. HU12121216") == "examp1etrade"  # a misread letter stays, a number goes
    assert parties.tax_key("HU12121216") == parties.tax_key(COMPANY_TAX)


def test_a_known_variant_is_found_in_a_longer_name_despite_a_misread_letter():
    assert parties.contains("exampletrade", parties.name_key("Examp1etrade Kft. Main street"))
    assert parties.contains("example jane", parties.name_key("Jane Example, Exampletrade Kft."))
    assert not parties.contains("example jane", parties.name_key("Jane Sample"))
    assert not parties.contains("ab", "ab cd")  # a short single word decides nothing


# --- reading: which party a document belongs to ------------------------------------------------------------------------------


def test_the_tax_number_decides_before_the_name(db):
    company = parties.create("Exampletrade Kft.", identities=[("tax", parties.tax_key(COMPANY_TAX), COMPANY_TAX),
                                                              ("name", "exampletrade", "Exampletrade Kft.")], actor="t")
    person = parties.create("Jane Example", identities=[("name", "example jane", "Jane Example")], actor="t")
    r = parties.resolver()
    assert r.invoice("Jane Example", COMPANY_TAX) == (company["id"], "tax")  # the contact person of the company
    assert r.invoice("Example Jane", None) == (person["id"], "name")
    assert r.invoice("Exampletrode Kft. Main street 1", None) == (company["id"], "similar")
    assert r.invoice("Jane Example Exampletrade Kft.", None) == (None, "ambiguous")  # both variants are in it
    assert r.invoice("Somebody Else", None) == (None, None)


def test_a_dismissed_name_is_nobodys_and_a_dismissed_tax_number_leaves_the_name_to_decide(db):
    person = parties.create("Jane Example", identities=[("name", "example jane", "Jane Example")], actor="t")
    parties.assign("name", "transport ticket", "Transport Ticket", None, actor="t")
    parties.assign("tax", parties.tax_key(CLUB_TAX), CLUB_TAX, None, actor="t")
    r = parties.resolver()
    assert r.invoice("Transport Ticket", None) == (None, None)
    assert r.invoice("Jane Example", CLUB_TAX) == (person["id"], "name")


def test_an_account_belongs_to_the_party_it_was_given_to(db):
    person = parties.create("Jane Example", identities=[("account", "acct-1", "1111-2222")], actor="t")
    r = parties.resolver()
    assert r.account("acct-1") == person["id"] and r.account("acct-2") is None


# --- changing the parties ------------------------------------------------------------------------------------------------


def test_an_identity_moves_and_two_parties_merge(db):
    a = parties.create("Jane Example", identities=[("name", "example jane", "Jane Example")], actor="t")
    b = parties.create("Dr. Mary Sample", identities=[("name", "mary sample", "Dr. Mary Sample")], actor="t")
    parties.assign("name", "mary sample", "Dr. Mary Sample", a["id"], actor="t")
    assert parties.resolver().invoice("Mary Sample", None) == (a["id"], "name")
    parties.release("name", "mary sample", actor="t")
    assert parties.resolver().invoice("Mary Sample", None) == (None, None)
    parties.assign("name", "mary sample", "Dr. Mary Sample", b["id"], actor="t")
    parties.merge(b["id"], a["id"], actor="t")
    [only] = parties.parties()
    assert only["id"] == a["id"] and {i["key"] for i in only["identities"]} == {"example jane", "mary sample"}
    parties.rename(a["id"], "The Example household", actor="t")
    assert parties.get(a["id"])["name"] == "The Example household"


def test_a_party_in_use_is_not_deleted_and_a_merge_repoints_its_users(db):
    used: dict[str, str] = {}
    parties.register_reference("test", count=lambda c, pid: int(pid in used.values()),
                               repoint=lambda c, old, new: used.update({k: new for k, v in used.items() if v == old}))
    try:
        a = parties.create("A party", identities=[], actor="t")
        b = parties.create("B party", identities=[], actor="t")
        used["package"] = a["id"]
        with pytest.raises(parties.PartyError):
            parties.delete(a["id"], actor="t")
        parties.merge(a["id"], b["id"], actor="t")
        assert used["package"] == b["id"]
        with pytest.raises(KeyError):
            parties.get(a["id"])
    finally:
        parties.unregister_reference("test")


def test_names_are_required_and_unknown_parties_refused(db):
    with pytest.raises(parties.PartyError):
        parties.create("  ", identities=[], actor="t")
    with pytest.raises(KeyError):
        parties.assign("name", "example jane", "Jane Example", "party-000000000000", actor="t")
    with pytest.raises(parties.PartyError):
        parties.assign("colour", "x", "x", None, actor="t")


# --- the proposal from the data ------------------------------------------------------------------------------------------


def test_the_proposal_groups_by_tax_number_and_by_name(db):
    invoices = [
        *_inv("Exampletrade Kft.", COMPANY_TAX, n=5),
        *_inv("Exampletrade Informatikai Kft. Main street 1", COMPANY_TAX, n=2),
        *_inv("Examp1etrade Kft.", None, n=1),                 # a misread letter, no tax number
        *_inv("Jane Example", COMPANY_TAX, n=3),               # the company's contact person
        *_inv("Jane Example", None, n=2),                      # ... who also buys for herself
        *_inv("Example Jane", None, n=2),
        *_inv("Dr. Mary Sample", None, n=2), *_inv("Mary Sample", None, n=1),
        *_inv("Sporting Club", CLUB_TAX, n=2),
        *_inv("Lonely Name Bt.", None, n=1),                   # one invoice, like nothing else
        *_inv("City Transport", None, supplier="City Transport Zrt.", n=4),  # the supplier misread as the buyer
    ]
    accounts = [{"key": "acct-1", "label": "1111-2222", "holder_text": "Bank statement Example Jane 1141 Budapest"},
                {"key": "acct-2", "label": "3333-4444", "holder_text": "Bank statement page 1"}]
    result = parties.suggest(invoices, accounts)
    s = _by_name(result)
    assert set(s) == {"Exampletrade Kft.", "Jane Example", "Dr. Mary Sample", "Sporting Club"}
    company = s["Exampletrade Kft."]
    assert company["party_id"] is None and company["invoices"] == 11
    assert _keys(company, "tax") == [parties.tax_key(COMPANY_TAX)]
    assert _keys(company, "name") == ["examp1etrade", "exampletrade", "exampletrade informatikai main street"]
    assert _keys(s["Jane Example"], "name") == ["example jane"] and s["Jane Example"]["invoices"] == 4
    assert _keys(s["Jane Example"], "account") == ["acct-1"]
    assert _keys(s["Dr. Mary Sample"], "name") == ["dr mary sample", "mary sample"]
    unassigned = {(u["kind"], u["key"]) for u in result["unassigned"]}
    assert ("name", "lonely name") in unassigned and ("account", "acct-2") in unassigned
    assert not any(k == "city transport" for _kind, k in unassigned)  # not a buyer identity at all
    assert result["buyer_is_supplier"] == 4


def test_tax_numbers_under_one_name_are_one_party_and_its_name_without_a_tax_number_joins_it(db):
    other_tax = "21357912-1-13"  # a sample number: a second one printed under the company's name
    invoices = [*_inv("Exampletrade Kft.", COMPANY_TAX, n=6), *_inv("Exampletrade Kft.", other_tax, n=2),
                *_inv("Jane Example", COMPANY_TAX, n=2), *_inv("Jane Example", None, n=2),
                *_inv("Sporting Club", CLUB_TAX, n=3), *_inv("Sporting Club", None, n=1)]
    s = _by_name(parties.suggest(invoices, []))
    assert set(s) == {"Exampletrade Kft.", "Jane Example", "Sporting Club"}
    assert _keys(s["Exampletrade Kft."], "tax") == sorted([parties.tax_key(COMPANY_TAX), parties.tax_key(other_tax)])
    assert s["Exampletrade Kft."]["invoices"] == 10
    assert _keys(s["Sporting Club"], "name") == ["club sporting"] and s["Sporting Club"]["invoices"] == 4
    assert s["Jane Example"]["invoices"] == 2  # the contact person printed with the company's number stays apart


def test_a_new_tax_number_under_a_known_name_goes_to_its_party(db):
    company = parties.create("Exampletrade Kft.", identities=[("tax", parties.tax_key(COMPANY_TAX), COMPANY_TAX),
                                                              ("name", "exampletrade", "Exampletrade Kft.")], actor="t")
    [only] = parties.suggest(_inv("Exampletrade Kft.", "21357912-1-13", n=2), [])["suggestions"]
    assert only["party_id"] == company["id"] and _keys(only, "tax") == [parties.tax_key("21357912-1-13")]


def test_the_proposal_builds_on_the_parties_already_there(db):
    company = parties.create("Exampletrade Kft.", identities=[("tax", parties.tax_key(COMPANY_TAX), COMPANY_TAX),
                                                              ("name", "exampletrade", "Exampletrade Kft.")], actor="t")
    parties.assign("name", "lonely name", "Lonely Name Bt.", None, actor="t")
    invoices = [*_inv("Exampletrade Kft.", COMPANY_TAX, n=3), *_inv("Exampletrade Kft. Main street 1", None, n=1),
                *_inv("Lonely Name Bt.", None, n=3)]
    result = parties.suggest(invoices, [])
    [only] = result["suggestions"]
    assert only["party_id"] == company["id"] and only["name"] == "Exampletrade Kft."
    assert [(i["kind"], i["key"]) for i in only["identities"]] == [("name", "exampletrade main street")]
    assert result["unassigned"] == []  # the dismissed name stays dismissed
    parties.apply(only, actor="t")
    assert parties.suggest(invoices, [])["suggestions"] == []
    assert parties.resolver().invoice("Exampletrade Kft. Main street 1", None) == (company["id"], "name")


def test_a_suggestion_is_identified_by_what_it_holds(db):
    invoices = [*_inv("Jane Example", None, n=2)]
    first = parties.suggest(invoices, [])["suggestions"][0]["id"]
    assert parties.suggest(list(reversed(invoices)), [])["suggestions"][0]["id"] == first
    assert parties.suggest([*invoices, *_inv("Example Jane", None, n=1)], [])["suggestions"][0]["id"] == first  # one variant
    assert parties.suggest([*invoices, *_inv("Jane Example Budapest", None, n=1)], [])["suggestions"][0]["id"] != first
