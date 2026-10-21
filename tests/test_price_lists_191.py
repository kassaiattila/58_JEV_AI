"""191 (plan F-quote-package B2, DECISIONS 191): price lists - the upload's check, the versions, the rules set apart.

The owner's decisions of 2026-10-21: the price list is uploaded as an Excel (or CSV) file and kept in versions; the
rules that change a price (a volume discount) are set on the settings page, not in the file. Claude's judgement: a
change of the rules, the currency or the VAT rate makes a new draft version with the same items, so a version never
changes and a quote names exactly one. The price lists here are the invented seller's (`configs/golden_quotes.json`)
or made-up workbooks built in the test. No AI call, no network.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from openpyxl import Workbook

from jav import price_lists, quote_golden, store


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "t191.sqlite"):
        yield


def _bytes(rows: list[list[object]], *, title: str = "Prices", before: list[list[object]] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for row in (before or []) + rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HEAD = ["Item code", "Name", "Unit", "Unit price (EUR)", "Category"]


def _invented(tmp_path) -> bytes:
    return quote_golden.write_price_list(tmp_path / "invented.xlsx").read_bytes()


def _codes(check: dict) -> list[str]:
    return [p["code"] for p in check["problems"]]


# --- the check -------------------------------------------------------------------------------------------------------


def test_the_invented_price_list_reads_to_its_items(tmp_path):
    golden = quote_golden.load().price_list
    check, items = price_lists.read(_invented(tmp_path), "invented.xlsx")
    assert check["ok"] and check["problems"] == []
    assert [(i.sku, i.name, i.unit, i.unit_price, i.category) for i in items] == [
        (i.sku, i.name, i.unit, i.unit_price, i.category) for i in golden.items]
    assert check["items"] == 24 and check["categories"] == ["hardware", "licence", "service"]


def test_english_headers_under_a_title_row_and_a_price_written_as_text():
    content = _bytes([HEAD, ["A-1", "Laptop", "pc", 1200, "hardware"], ["A-2", "Support", "hour", "1 250,50", None],
                      [None, None, None, None, None]], before=[["Price list 2026"], []])
    check, items = price_lists.read(content, "prices.xlsx")
    assert check["ok"], check
    assert check["columns"]["unit_price"] == "Unit price (EUR)"
    assert [(i.sku, i.unit_price, i.category) for i in items] == [("A-1", Decimal("1200"), "hardware"),
                                                                   ("A-2", Decimal("1250.5"), None)]


def test_a_missing_column_refuses_the_file_and_names_it():
    check, items = price_lists.read(_bytes([["Item code", "Name", "Unit price"], ["A-1", "Laptop", 1200]]), "p.xlsx")
    assert not check["ok"] and items == []
    assert check["problems"] == [{"code": "missing_column", "where": "", "detail": "unit"}]


def test_each_bad_row_is_named_with_its_row():
    content = _bytes([HEAD, ["A-1", "Laptop", "pc", 1200, "hardware"], ["A-1", "Laptop again", "pc", 1100, "hardware"],
                      [None, "No code", "pc", 10, "hardware"], ["A-3", "Odd", "pc", "abc", "hardware"],
                      ["A-4", "Minus", "pc", -5, "hardware"], ["A-5", "Two ways", "pc", "28.5", "hardware"],
                      ["A-6", None, "pc", 3, "hardware"], ["A-7", "No price", "pc", None, "hardware"]])
    check, _items = price_lists.read(content, "p.xlsx")
    assert not check["ok"]
    assert [(p["code"], p["where"]) for p in check["problems"]] == [
        ("duplicate_sku", "Prices!3"), ("sku_missing", "Prices!4"), ("price_not_number", "Prices!5"),
        ("price_negative", "Prices!6"), ("price_ambiguous", "Prices!7"), ("name_missing", "Prices!8"),
        ("price_missing", "Prices!9")]


def test_a_file_without_items_or_that_cannot_be_read_is_refused():
    assert _codes(price_lists.read(_bytes([HEAD]), "p.xlsx")[0]) == ["no_items"]
    assert _codes(price_lists.read(b"not a workbook", "p.xlsx")[0]) == ["unreadable"]
    assert _codes(price_lists.read(b"A;B", "p.pdf")[0]) == ["not_a_table"]


def test_a_csv_price_list_is_read_as_well():
    content = "Item code;Name;Unit;Unit price;Category\nA-1;Laptop;pc;1200;hardware\n".encode("utf-8")
    check, items = price_lists.read(content, "prices.csv")
    assert check["ok"], check
    assert [(i.sku, i.unit_price) for i in items] == [("A-1", Decimal("1200"))]


# --- the store and the versions -------------------------------------------------------------------------------------


def test_an_upload_is_a_draft_then_active_and_a_new_upload_supersedes_it(db, tmp_path):
    first = price_lists.add("Seller 2026", "invented.xlsx", _invented(tmp_path), actor="anna")
    assert (first["version"], first["state"], first["currency"], first["vat_percent"]) == (1, "draft", "HUF", "27")
    assert first["items"] == 24 and first["discounts"] == []
    pl = first["price_list"]
    assert price_lists.activate(pl, 1, actor="anna")["state"] == "active"
    second = price_lists.add("Seller 2026", "invented.xlsx", _invented(tmp_path), actor="anna", price_list=pl)
    assert second["version"] == 2 and second["state"] == "draft"
    assert second["fingerprint"] == first["fingerprint"]  # the same items, rules, currency and VAT rate
    price_lists.activate(pl, 2, actor="anna")
    states = {v["version"]: v["state"] for v in price_lists.listing()[0]["versions"]}
    assert states == {1: "superseded", 2: "active"}
    assert price_lists.active(pl).version == 2
    price_lists.retire(pl, actor="anna")
    assert price_lists.active(pl) is None


def test_a_refused_upload_stores_nothing(db):
    with pytest.raises(price_lists.PriceListRefused) as refused:
        price_lists.add("Bad", "p.xlsx", _bytes([HEAD]), actor="anna")
    assert _codes(refused.value.check) == ["no_items"]
    assert price_lists.listing() == []


def test_the_rules_make_a_new_draft_with_the_same_items(db, tmp_path):
    pl = price_lists.add("Seller 2026", "invented.xlsx", _invented(tmp_path), actor="anna")["price_list"]
    price_lists.activate(pl, 1, actor="anna")
    rules = [{"category": "hardware", "min_quantity": "10", "percent": "5"}]
    changed = price_lists.change_settings(pl, 1, discounts=rules, currency="HUF", vat_percent="27", actor="bela")
    assert (changed["version"], changed["state"], changed["change"], changed["based_on"]) == (2, "draft", "settings", 1)
    assert changed["discounts"] == [{"category": "hardware", "min_quantity": "10", "percent": "5"}]
    assert changed["fingerprint"] != price_lists.get(pl, 1)["fingerprint"]
    v2 = price_lists.version(pl, 2)
    assert v2.items == price_lists.version(pl, 1).items
    assert v2.discounts == (price_lists.Discount(category="hardware", min_quantity=Decimal("10"), percent=Decimal("5")),)
    assert price_lists.content(pl, 2) == price_lists.content(pl, 1)  # the file it was read from
    assert price_lists.active(pl).version == 1  # a draft until a person makes it active


@pytest.mark.parametrize("rule, code", [
    ({"category": "food", "min_quantity": "10", "percent": "5"}, "unknown_category"),
    ({"category": "hardware", "min_quantity": "0", "percent": "5"}, "quantity_not_positive"),
    ({"category": "hardware", "min_quantity": "10", "percent": "100"}, "percent_out_of_range"),
    ({"category": "hardware", "min_quantity": "10", "percent": "five"}, "not_a_number"),
])
def test_a_wrong_rule_is_refused(db, tmp_path, rule, code):
    pl = price_lists.add("Seller 2026", "invented.xlsx", _invented(tmp_path), actor="anna")["price_list"]
    with pytest.raises(price_lists.PriceListRefused) as refused:
        price_lists.change_settings(pl, 1, discounts=[rule], currency="HUF", vat_percent="27", actor="anna")
    assert _codes(refused.value.check) == [code]
    assert len(price_lists.listing()[0]["versions"]) == 1


def test_the_same_rule_twice_a_bad_currency_or_vat_rate_or_no_change_is_refused(db, tmp_path):
    pl = price_lists.add("Seller 2026", "invented.xlsx", _invented(tmp_path), actor="anna")["price_list"]
    rule = {"category": "hardware", "min_quantity": "10", "percent": "5"}
    with pytest.raises(price_lists.PriceListRefused) as refused:
        price_lists.change_settings(pl, 1, discounts=[rule, rule], currency="huf", vat_percent="127", actor="anna")
    assert _codes(refused.value.check) == ["duplicate_rule", "currency", "vat_percent"]
    with pytest.raises(price_lists.PriceListStateError):
        price_lists.change_settings(pl, 1, discounts=[], currency="HUF", vat_percent="27", actor="anna")


def test_a_new_upload_keeps_the_rules_whose_category_it_still_has(db, tmp_path):
    first = _bytes([HEAD, ["A-1", "Laptop", "pc", 1200, "hardware"], ["A-2", "Support", "hour", 50, "service"]])
    pl = price_lists.add("Ours", "p.xlsx", first, actor="anna", currency="EUR", vat_percent="20")["price_list"]
    rules = [{"category": "hardware", "min_quantity": "10", "percent": "5"},
             {"category": "service", "min_quantity": "100", "percent": "2,5"}]
    price_lists.change_settings(pl, 1, discounts=rules, currency="EUR", vat_percent="20", actor="anna")
    later = price_lists.add("Ours", "p.xlsx", _bytes([HEAD, ["A-1", "Laptop", "pc", 1250, "hardware"]]), actor="anna",
                            price_list=pl)
    assert (later["version"], later["currency"], later["vat_percent"]) == (3, "EUR", "20")
    assert later["discounts"] == [{"category": "hardware", "min_quantity": "10", "percent": "5"}]
    assert later["check"]["warnings"] == [{"code": "rule_dropped", "where": "", "detail": "service"}]


def test_the_service_uploads_changes_activates_and_hands_back_the_file(tmp_path):
    from fastapi.testclient import TestClient

    from jav.api import create_app

    path = quote_golden.write_price_list(tmp_path / "invented.xlsx")
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(_bytes([HEAD]))
    human = {"X-Actor": "anna"}
    with TestClient(create_app(store_path=tmp_path / "t191.sqlite"), base_url="http://127.0.0.1:8930") as c:
        listed = c.get("/api/price-lists").json()
        assert listed["price_lists"] == [] and listed["currency"] == "HUF" and listed["vat_percent"] == "27"
        refused = c.post("/api/price-lists", headers=human, json={"name": "Bad", "path": str(bad)})
        assert refused.status_code == 422 and refused.json()["error"] == "price_list_refused"
        assert [p["code"] for p in refused.json()["check"]["problems"]] == ["no_items"]
        made = c.post("/api/price-lists", headers=human, json={"name": "Seller 2026", "path": str(path)})
        assert made.status_code == 201
        pl = made.json()["price_list"]
        one = c.get(f"/api/price-lists/{pl}/versions/1").json()
        assert len(one["item_rows"]) == 24 and one["categories"] == ["hardware", "licence", "service"]
        rules = {"discounts": [{"category": "hardware", "min_quantity": "10", "percent": "5"}], "currency": "HUF",
                 "vat_percent": "27"}
        changed = c.post(f"/api/price-lists/{pl}/versions/1/settings", headers=human, json=rules)
        assert changed.status_code == 201 and changed.json()["version"] == 2
        same = c.post(f"/api/price-lists/{pl}/versions/2/settings", headers=human, json=rules)
        assert same.status_code == 409 and same.json()["error"] == "price_list_state"
        assert c.post(f"/api/price-lists/{pl}/versions/2/activate", headers=human, json={}).json()["state"] == "active"
        assert c.post(f"/api/price-lists/{pl}/retire", headers=human, json={}).json()["state"] == "retired"
        assert c.get(f"/api/price-lists/{pl}/versions/9").status_code == 404
        got = c.get(f"/api/price-lists/{pl}/versions/2/file")
        assert got.status_code == 200 and got.content == path.read_bytes()


def test_an_unknown_list_or_version_and_the_states_that_do_not_allow_it(db, tmp_path):
    with pytest.raises(price_lists.PriceListNotFound):
        price_lists.get("pl-0000000000", 1)
    pl = price_lists.add("Seller 2026", "invented.xlsx", _invented(tmp_path), actor="anna")["price_list"]
    with pytest.raises(price_lists.PriceListStateError):
        price_lists.retire(pl, actor="anna")  # no active version yet
    price_lists.activate(pl, 1, actor="anna")
    with pytest.raises(price_lists.PriceListStateError):
        price_lists.activate(pl, 1, actor="anna")  # already active
