"""JEV framework round 1 / policy bands (BACKLOG 2) - offline.

Named band sets in `configs/policy.json` (`bands`), assigned per call site (`band_for`), precedence: the longest
dotted prefix -> `default`; a set is merged over `default`.
Noul: no / uncertain / yes (two-sided band); Choice: auto / uncertain / human (conf threshold + second-option gap).
The `uncertain` band is a review reason only if the set has `uncertain_review: true` (false by default: the band is
measurable, the route does not change - the decision is the owner's, based on the eval report's numbers).
"""

from __future__ import annotations

import pytest

from jav import cfg, policy
from jav.models import FieldPick, FlowState, JevVerdicts


def _state(arm: str = "S", **kw) -> FlowState:
    return FlowState(source_path="x.pdf", case_id="c", arm=arm, **kw)


def _pick(field: str, conf: float, probs: dict[str, float] | None = None, label: str | None = "v") -> FieldPick:
    probs = probs if probs is not None else {label or "v": conf, "none": round(1 - conf, 2)}
    return FieldPick(field=field, label=label, confidence=conf, probabilities=probs, n_options=len(probs), request_id="r")


def test_policy_json_v110_has_bands_and_no_legacy_thresholds():
    p = cfg.load("policy")
    assert p["meta"]["version"] >= "1.1.0"  # 1.1.0: bands; 1.2.0: parent_min_prob
    assert set(p["bands"]) >= {"default", "high_stakes", "verify_flag"}
    d = p["bands"]["default"]
    assert {"noul_no_max", "noul_yes_min", "choice_human_max_conf", "choice_second_min_gap", "uncertain_review"} <= set(d)
    assert d["noul_no_max"] < d["noul_yes_min"] and d["uncertain_review"] is False
    # 1.5.0: the required / high_stakes lists are in the type packs (configs/types/); policy = bands + email
    assert "invoice" not in p
    assert "low_confidence" not in p.get("detect", {}) and "intent_human_max_conf" not in p["email"]
    assert set(p["band_for"]) >= {"invoice.pick", "invoice.pick.high_stakes", "invoice.verify", "detect.doc_type", "email.intent", "email.signal"}


def test_band_precedence_longest_prefix_then_default():
    hs = policy.band("invoice.pick.high_stakes")
    # merged over default
    assert hs["choice_human_max_conf"] == 0.85 and hs["noul_yes_min"] == policy.band("default")["noul_yes_min"]
    assert policy.band("invoice.pick.high_stakes.gross_total")["choice_human_max_conf"] == 0.85  # longest prefix
    assert policy.band("invoice.pick.other") == policy.band("invoice.pick")
    assert policy.band("no.such.callsite") == policy.band("default")
    assert policy.band_name("invoice.pick.high_stakes.x") == "high_stakes" and policy.band_name("zzz") == "default"


def test_noul_band_is_two_sided():
    assert policy.noul_band(0.0, "invoice.verify") == "no"
    assert policy.noul_band(0.29, "invoice.verify") == "no"
    assert policy.noul_band(0.30, "invoice.verify") == "uncertain"
    assert policy.noul_band(0.69, "invoice.verify") == "uncertain"
    assert policy.noul_band(0.70, "invoice.verify") == "yes"  # the threshold is closed (>=); the old `> 0.7` was open
    assert policy.noul_band(1.0, "email.signal") == "yes"


def test_choice_band_conf_then_second_option_gap():
    assert policy.choice_band(0.59, {"a": 0.6, "b": 0.4}, "email.intent") == "human"
    assert policy.choice_band(0.90, {"a": 0.50, "b": 0.40, "c": 0.10}, "email.intent") == "uncertain"  # gap 0.10 < 0.20
    assert policy.choice_band(0.90, {"a": 0.90, "b": 0.10}, "email.intent") == "auto"
    assert policy.choice_band(0.90, None, "email.intent") == "auto"  # gap cannot be computed -> only conf decides
    assert policy.choice_band(0.90, {"a": 0.9}, "email.intent") == "auto"  # a single option
    assert policy.choice_band(0.80, {"a": 0.8, "b": 0.2}, "invoice.pick.high_stakes") == "human"  # below 0.85


def test_uncertain_band_reviews_only_when_enabled(monkeypatch: pytest.MonkeyPatch):
    probs = {"a": 0.50, "b": 0.40, "c": 0.10}
    assert policy.choice_needs_review(0.9, probs, "email.intent") is False
    assert policy.choice_review_reason("intent", "x", 0.9, probs, "email.intent") is None
    assert policy.noul_review_reason("jev", "off_target:f", 0.5, "invoice.verify") is None

    monkeypatch.setitem(policy.BANDS["default"], "uncertain_review", True)
    assert policy.choice_needs_review(0.9, probs, "email.intent") is True
    assert policy.choice_review_reason("intent", "x", 0.9, probs, "email.intent") == "intent:second_option:x:0.10"
    assert policy.noul_review_reason("jev", "off_target:f", 0.5, "invoice.verify") == "jev:uncertain:off_target:f:0.50"


def test_apply_pick_policy_reasons_are_backward_compatible():
    st = _state(picks={
        "supplier_name": _pick("supplier_name", 0.99),
        "invoice_number": _pick("invoice_number", 0.55),  # < 0.6 -> low_conf
        "gross_total": _pick("gross_total", 0.75),  # high stakes, 0.6-0.85 -> high_stakes_conf
        # gap 0.05: uncertain, not a review by default
        "due_date": _pick("due_date", 0.90, {"2024-01-01": 0.5, "2024-02-01": 0.45, "none": 0.05}),
        "buyer_name": _pick("buyer_name", 0.9, {"none": 0.9, "X": 0.1}, label=None),  # mandatory field with none
    })
    policy.apply_pick_policy(st)
    assert st.needs_review
    assert "pick:low_conf:invoice_number:0.55" in st.review_reasons
    assert "pick:high_stakes_conf:gross_total:0.75" in st.review_reasons
    assert "pick:none:buyer_name" in st.review_reasons
    assert not any("due_date" in r for r in st.review_reasons)
    assert not any("supplier_name" in r for r in st.review_reasons)


def test_apply_verdict_policy_uses_noul_band():
    v = JevVerdicts(flags={"net_total": {"off_target": 0.70, "incomplete": 0.69}}, doc_flags={"parties_swapped": 0.71, "line_items_missing_rows": 0.2})
    st = _state("G", verdicts=v)
    policy.apply_verdict_policy(st)
    assert "jev:off_target:net_total:0.70" in st.review_reasons
    assert "jev:parties_swapped:0.71" in st.review_reasons
    assert not any("incomplete" in r or "line_items" in r for r in st.review_reasons)


def test_legacy_constants_derive_from_bands():
    assert policy.HUMAN_MAX_CONF == policy.band("invoice.pick")["choice_human_max_conf"] == 0.60
    assert policy.AUTO_MIN_CONF_HIGH_STAKES == policy.band("invoice.pick.high_stakes")["choice_human_max_conf"] == 0.85
    assert policy.REVIEW_FLAG_P == policy.band("invoice.verify")["noul_yes_min"] == 0.70
    assert policy.DETECT_LOW_CONFIDENCE == policy.band("detect.doc_type")["choice_human_max_conf"] == 0.60
    assert policy.INTENT_HUMAN_MAX_CONF == policy.band("email.intent")["choice_human_max_conf"] == 0.60


def test_email_next_flow_accepts_probabilities():
    assert policy.email_next_flow("szamlakuldes", 0.9, [], probabilities={"szamlakuldes": 0.9, "other": 0.1}) == "human:fetch_document"
    assert policy.email_next_flow("szamlakuldes", 0.5, []) == "human:low_confidence"


def test_high_stakes_field_outside_scored_fields_is_still_checked():
    """066 Á04: the Hungarian invoice's `amount_due` field is high-stakes but not among the scored fields; the band
    check used to skip it, so a very uncertain amount due was accepted without a to-do."""
    st = _state(doc_type="invoice_hu", picks={"amount_due": _pick("amount_due", 0.20)})
    policy.apply_pick_policy(st)
    assert st.needs_review
    assert any(r.startswith("pick:") and "amount_due" in r for r in st.review_reasons)


def test_every_high_stakes_field_of_an_s_pack_is_checked_by_the_pick_policy():
    from jav import typepack

    for key in typepack.keys():
        pack = typepack.get(key)
        if "S" in pack.arms:
            assert set(pack.high_stakes) <= policy.pick_policy_fields(pack), key
