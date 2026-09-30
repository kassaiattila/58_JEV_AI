"""Regiszter-séma v2 (BACKLOG regiszter-séma): `what / not_for / examples / parent` az M1 és M3 regiszterben - offline.

- a Choice-kritérium strukturált JSON-objektum (`what`, `not_for`, `examples`), nem egyetlen mondat;
- minden típus / szándék egy szülő-családban van (`parents` blokk a JSON-ban), a kód a családot is összegzi a nyers
  valószínűségekből (szülő-címke alacsony confidence-nél - hívás nélkül);
- a régi golden-formátum (`description`, `few_shot`) helyett `what` / `examples`, a példák goldennel konzisztensek.
"""

from __future__ import annotations

import pytest

from jav import cfg, doc_types, intents, policy
from jav.registry import parent_summary


def test_doc_types_json_v2_shape():
    d = cfg.load("doc_types")
    assert d["meta"]["version"].startswith("2.")
    assert set(d["parents"]) >= {"invoice_like", "contract_like", "bank_like", "official_like", "other"}
    for t in d["types"]:
        assert {"key", "what", "not_for", "examples", "parent"} <= set(t), t["key"]
        assert "description" not in t  # egy forrás: a `what`
        assert t["parent"] in d["parents"], t["key"]
        assert len(t["what"]) > 40 and len(t["not_for"]) > 10 and isinstance(t["examples"], list) and t["examples"]
    assert d["unknown_parent"] in d["parents"]


def test_intents_json_v2_shape():
    d = cfg.load("intents")
    assert d["meta"]["version"].startswith("2.")
    for i in d["intents"]:
        assert {"key", "display_name", "what", "not_for", "examples", "parent"} <= set(i), i["key"]
        assert "description" not in i and "few_shot" not in i
        assert i["parent"] in d["parents"], i["key"]
    # a példák goldennel konzisztensek: a korábbi verbatim tárgysorok maradtak
    by = {i["key"]: i for i in d["intents"]}
    assert "Számlája érkezett" in by["szamlakuldes"]["examples"]
    assert by["other"]["examples"] == []


def test_choice_criteria_are_structured_objects():
    crit = doc_types.choice_criteria()
    assert set(crit) == set(doc_types.DOC_TYPE_KEYS)
    for key, v in crit.items():
        assert isinstance(v, dict) and set(v) == {"what", "not_for", "examples"}, key
    assert "Upwork" in crit["invoice_hu"]["not_for"] or "Upwork" in crit["invoice_hu"]["what"]  # a 2026-09-20-as policy megmaradt
    assert doc_types.BY_KEY["invoice_hu"].description == doc_types.BY_KEY["invoice_hu"].what  # kompatibilis név

    icrit = intents.choice_criteria()
    assert set(icrit) == set(intents.INTENT_KEYS)
    assert isinstance(icrit["szamlakuldes"], dict) and "Számlája érkezett" in icrit["szamlakuldes"]["examples"]
    assert icrit["other"]["examples"] == []
    assert intents.BY_KEY["szamlakuldes"].few_shot == tuple(icrit["szamlakuldes"]["examples"])  # kompatibilis név


def test_parent_maps_cover_every_key():
    assert set(doc_types.PARENT_OF) == set(doc_types.DOC_TYPE_KEYS)  # unknown is
    assert doc_types.PARENT_OF["invoice_hu"] == doc_types.PARENT_OF["invoice_foreign"] == "invoice_like"
    assert doc_types.PARENT_OF["utility_bill_hu"] == "invoice_like" and doc_types.PARENT_OF["contract"] == "contract_like"
    assert doc_types.PARENT_OF[doc_types.UNKNOWN] == "other"
    assert set(intents.PARENT_OF) == set(intents.INTENT_KEYS)
    assert intents.PARENT_OF["szamlakuldes"] == intents.PARENT_OF["fizetesi_visszaigazolas"]
    assert intents.PARENT_OF["system_notification"] == intents.PARENT_OF["social_network_notification"]
    assert intents.PARENT_OF["business_correspondence"] != intents.PARENT_OF["newsletter_marketing"]


def test_parent_summary_sums_family_probabilities():
    probs = {"invoice_hu": 0.45, "invoice_foreign": 0.40, "contract": 0.10, "unknown": 0.05}
    parent, p = parent_summary(probs, doc_types.PARENT_OF)
    assert parent == "invoice_like" and abs(p - 0.85) < 1e-9
    assert parent_summary({}, doc_types.PARENT_OF) == (None, 0.0)
    # a legvalószínűbb opció családja számít, nem a legnagyobb család
    parent2, p2 = parent_summary({"contract": 0.5, "invoice_hu": 0.3, "invoice_foreign": 0.2}, doc_types.PARENT_OF)
    assert parent2 == "contract_like" and abs(p2 - 0.5) < 1e-9


def test_policy_parent_fallback_band():
    b = policy.band("detect.doc_type")
    assert b["parent_min_prob"] == 0.85
    # bizonytalan típus, biztos család -> a szülő-címke használható
    assert policy.parent_fallback(0.45, "invoice_like", 0.9, "detect.doc_type") == "invoice_like"
    assert policy.parent_fallback(0.45, "invoice_like", 0.7, "detect.doc_type") is None  # a család sem biztos
    assert policy.parent_fallback(0.95, "invoice_like", 0.99, "detect.doc_type") is None  # a típus biztos: nem kell szülő


def test_detect_and_intent_results_carry_parent():
    from jav.detect import DetectResult
    from jav.intent import IntentResult
    from jav.models import JevCall

    call = JevCall(request_id="x", n_questions=1, state_chars=1)
    r = DetectResult(doc_type="invoice_hu", confidence=0.45, probabilities={"invoice_hu": 0.45, "invoice_foreign": 0.4, "contract": 0.15},
                     issuer_hu=0.5, language="hu", language_conf=0.9, call=call)
    assert r.parent == "invoice_like" and abs(r.parent_prob - 0.85) < 1e-9
    i = IntentResult(intent="szamlakuldes", confidence=0.5, probabilities={"szamlakuldes": 0.5, "fizetesi_visszaigazolas": 0.3, "other": 0.2}, call=call)
    assert i.parent == intents.PARENT_OF["szamlakuldes"] and abs(i.parent_prob - 0.8) < 1e-9


def test_eval_report_parent_section(tmp_path):
    import json

    from jav import eval_report as er

    rows = [
        {"case_id": "d1", "expected": "invoice_foreign", "got": "invoice_hu", "confidence": 0.45, "issuer_hu": 0.5, "language": "hu", "status": "done",
         "top3": {"invoice_hu": 0.45, "invoice_foreign": 0.40, "contract": 0.15}, "parent": "invoice_like", "parent_prob": 0.85},
        {"case_id": "d2", "expected": "contract", "got": "contract", "confidence": 0.99, "issuer_hu": 0.1, "language": "hu", "status": "done",
         "top3": {"contract": 1.0}, "parent": "contract_like", "parent_prob": 1.0},
    ]
    p = tmp_path / "20260101_000000_detect_golden.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    js = er.judgments_from_file(p)
    d1 = next(j for j in js if j.case_id == "d1" and j.kind == "choice")
    assert d1.parent == "invoice_like" and d1.parent_prob == 0.85 and d1.parent_correct is True  # a várt típus családja egyezik
    rows_ = er.parent_fallback_summary(js)
    r = next(r for r in rows_ if r["flow"] == "doc_detect")
    assert r["human"] == 1 and r["parent_usable"] == 1 and r["parent_correct"] == 1
    assert "## Szülő-címke" in er.report_markdown([p])
