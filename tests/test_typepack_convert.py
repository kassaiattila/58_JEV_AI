"""047 T1.1: converting the legacy type copies into full packs (on the hash-checked copies in the repo; no AI calls)."""

import json

import pytest

from jav import typepack
from jav.typepack_convert import LEGACY_DIR, PENDING, convert, guess_kind

OLD_MAP = json.loads((LEGACY_DIR.parent / "doc_types.json").read_text(encoding="utf-8"))["old_type_map"]
KEYS = sorted(p.name for p in LEGACY_DIR.iterdir() if p.is_dir())


def test_kind_heuristics():
    money = {"amount"}
    assert guess_kind("amount", {"type": ["string", "null"]}, money) == "money"
    assert guess_kind("closing_balance", {"type": ["string", "null"]}, set()) == "money"
    assert guess_kind("account_iban", {"type": ["string", "null"]}, set()) == "iban"
    assert guess_kind("tax_id", {"type": ["string", "null"]}, set()) == "tax_id"
    assert guess_kind("valid_until", {"type": ["string", "null"]}, set()) == "date"
    assert guess_kind("event_datetime", {"type": ["string", "null"]}, set()) == "text"
    assert guess_kind("holder_name", {"type": ["string", "null"]}, set()) == "name"
    assert guess_kind("event_name", {"type": ["string", "null"]}, set()) == "text"
    assert guess_kind("is_blank_form", {"type": "boolean"}, set()) == "boolean"
    assert guess_kind("transactions", {"type": "array"}, set()) == "list"


@pytest.mark.parametrize("key", KEYS)
def test_every_legacy_type_converts_and_loads(key):
    out = convert(key, old_type_map=OLD_MAP)
    pack = out["pack"]
    schema = json.loads(out["schema_src"].read_text(encoding="utf-8"))
    assert list(pack["fields"]) == list(schema["properties"])  # every legacy field, in the legacy order
    assert pack["parent"] == OLD_MAP[key] and pack["auto_detect"] is (key not in PENDING)
    assert set(out["callsite"]["field_specs"]) == {f for f, k in pack["fields"].items() if k != "list"}
    loaded = typepack.get(key)  # the (converted) pack in the repo loads and matches the converter
    assert dict(loaded.fields) == pack["fields"] and loaded.arms == ("G",)


def test_statement_keeps_transactions_rules_and_enums():
    pack = convert("statement_cib", old_type_map=OLD_MAP)["pack"]
    assert pack["list_fields"]["transactions"]["amount"] == "money"
    assert pack["list_fields"]["transactions"]["booking_date"] == "date"
    assert pack["enums"]["transactions[].direction"] == ["debit", "credit"]
    assert {v["check"] for v in pack["validators"]} >= {"running_balance_check", "closing_balance_check", "totals_consistency", "period_dates"}


@pytest.mark.parametrize("fixture", sorted(LEGACY_DIR.glob("*/fixtures/*.json")), ids=lambda p: p.parent.parent.name)
def test_converted_pack_agrees_with_legacy_fixture_verdict(fixture):
    """The expected verdict of the legacy (synthetic) test document = the new pack's normalisation + rules; no data is
    lost."""
    from jav.validators import run_all

    case = json.loads(fixture.read_text(encoding="utf-8"))
    pack = typepack.get(fixture.parent.parent.name)
    rec, reasons = pack.normalize(case["datapoints"])
    # 075: the domestic bank account check digits are checked now; the legacy rules did not, so a legacy synthetic
    # document whose only failure is that check keeps its legacy "valid" verdict (the fixture is a verbatim copy)
    failed = {r.code for r in run_all(rec, pack.validators) if not r.ok} - {"account.hu_checksum", "iban.hu_account_checksum"}
    assert (not failed) is case["expected_valid"] and reasons == []
    dp = rec.to_datapoints(pack.record_fields)
    assert [k for k, v in case["datapoints"].items() if v not in (None, [], "") and dp.get(k) in (None, [], "")] == []


def test_broken_statement_is_flagged():
    from jav.validators import run_all

    case = json.loads((LEGACY_DIR / "statement_cib" / "fixtures" / "synth_statement.json").read_text(encoding="utf-8"))
    case["datapoints"]["closing_balance"] = "999.00"
    pack = typepack.get("statement_cib")
    rec, _ = pack.normalize(case["datapoints"])
    assert "closing.mismatch" in {r.code for r in run_all(rec, pack.validators) if not r.ok}
