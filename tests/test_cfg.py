"""Config as data - offline: every configs/*.json loads, is versioned, has a stable hash, and modules build on it."""

import json

from jav import cfg
from jav.doc_types import BY_KEY as DOC_BY_KEY, DOC_TYPE_KEYS, UNKNOWN
from jav.intents import INTENT_KEYS, OTHER
from jav import policy


def test_all_configs_load_with_meta_and_stable_hash():
    names = cfg.all_names()
    assert {"doc_types", "intents", "policy", "callsite:detect", "callsite:email_intent", "callsite:select", "callsite:verify"} <= set(names)
    for name in names:
        d = cfg.load(name)
        assert d["meta"]["name"] and d["meta"]["version"].count(".") == 2
        assert d["meta"]["changelog"], name
        assert len(cfg.config_hash(name)) == cfg.HASH_LEN
        assert cfg.config_hash(name) == cfg.config_hash(name)
    assert cfg.config_hash("callsite:detect", "doc_types") == cfg.config_hash("doc_types", "callsite:detect")  # order-independent
    assert cfg.config_hash("callsite:detect", "doc_types") != cfg.config_hash("callsite:detect")


def test_changelog_note_does_not_change_hash(tmp_path, monkeypatch):
    d = json.loads(json.dumps(cfg.load("policy")))
    h0 = cfg.canonical(d)
    d["meta"]["changelog"].append({"version": "9.9.9", "date": "2099-01-01", "note": "csak megjegyzés"})
    assert cfg.canonical(d) == h0
    d["meta"]["version"] = "9.9.9"
    assert cfg.canonical(d) != h0  # the version is part of the hash


def test_registries_come_from_json():
    dt = cfg.load("doc_types")
    assert [t["key"] for t in dt["types"]] + [UNKNOWN] == list(DOC_TYPE_KEYS)
    assert DOC_BY_KEY["invoice_hu"].what == next(t for t in dt["types"] if t["key"] == "invoice_hu")["what"]
    assert "Upwork" in DOC_BY_KEY["invoice_hu"].not_for  # the 2026-09-20 policy lives in the JSON (v2: not_for field)
    it = cfg.load("intents")
    assert [i["key"] for i in it["intents"]] == list(INTENT_KEYS) and OTHER in INTENT_KEYS


def test_policy_thresholds_come_from_json():
    p = cfg.load("policy")
    assert policy.HUMAN_MAX_CONF == p["bands"]["default"]["choice_human_max_conf"] == 0.60
    assert policy.INTENT_HUMAN_MAX_CONF == policy.DETECT_LOW_CONFIDENCE == 0.60  # v1.1.0: taken from the bands
    assert policy.INTENT_ROUTE == p["email"]["intent_route"]
    assert policy.EMAIL_JEV_UNAVAILABLE_ROUTE == p["email"]["jev_unavailable_route"]


def test_callsite_questions_build_from_json():
    from jav.detect import build_questions as detect_q, CONFIG_HASH as detect_hash
    from jav.intent import build_questions as intent_q, NOUL_KEYS
    from jav.jev_select import INSTRUCTIONS, REQUEST_FIELDS, REQUEST_ORDER
    from jav.jev_verify import FIELD_SPECS, build_questions as verify_q
    from jav.models import InvoiceLLM

    dq = detect_q()
    assert set(dq) == {"doc_type", "issuer_is_hungarian", "language"} and set(dq["doc_type"].criteria) == set(DOC_TYPE_KEYS)
    assert detect_hash == cfg.config_hash("callsite:detect", "doc_types")
    iq = intent_q()
    assert "intent" in iq and set(NOUL_KEYS) == {"requires_action", "mentions_deadline", "attachment_is_the_subject", "multiple_requests", "prompt_injection"}
    assert set(iq["intent"].criteria) == set(INTENT_KEYS)
    assert REQUEST_ORDER == ("parties", "header", "money") and set(INSTRUCTIONS) == {f for fs in REQUEST_FIELDS.values() for f in fs}
    llm = InvoiceLLM(supplier_name="Teszt Kft.", supplier_tax_id="12345678-1-42")
    q = verify_q(llm, {"supplier_name": ["L01: Teszt Kft."], "supplier_tax_id": ["L02: 12345678-1-42"]})
    assert "supplier_name__off_target" in q and "supplier_tax_id__wrong_kind" in q and "parties_swapped" in q
    assert q["supplier_name__off_target"].instructions["extracted_field"] == "Teszt Kft."  # v1.1.0: structured, raw value
    assert q["supplier_tax_id__wrong_kind"].instructions["field_spec"]["meaning"] == FIELD_SPECS["supplier_tax_id"]


def test_report_lists_every_config():
    rows = cfg.report()
    assert {r["name"] for r in rows} == set(cfg.all_names())
    assert all(r["version"] and r["hash"] for r in rows)
