"""231 (stage F, F2; the owner's decisions of 2026-10-29: the full move into a data file): the candidate finder's
patterns, limits and profiles are data.

Until now the S path's candidate finder held its patterns (labels, legal forms, money and date shapes, OCR
tolerances) as constants in the code, and two places compared a profile's name. They moved into
`configs/candidate_profiles.json` unchanged: every pattern's text and flags, the limits and the strip characters are
pinned here as they were on `c7a1e5f6` (before the move), and two switches of the profile replace the name
comparisons. A new profile is data alone. The S path's requests and the candidates on synthetic documents are pinned in
tests/test_select_keys_231.py. No model call.
"""

from __future__ import annotations

import hashlib
import json
import re

from jav.ai import candidates, typepack
from jav.ai.jev_verify import site_for
from jav.core import cfg
from jav.core.config import PROJECT_ROOT
from jav.documents.layout import LineLayout

# every moved pattern's text and flags, the limits and the strip characters, as on `c7a1e5f6`
MOVED_DIGEST = "a98090c9b96395f7"
NAMES = [
    "ADDRESS_INTL_RE", "ADDRESS_LABEL_UTILITY_RE", "ADDRESS_RE", "ADDRESS_STOP_INTL_RE", "AMOUNT_TOKEN_RE", "CURRENCY_HINT_RE",
    "IBAN_GROUP_RE", "IBAN_INTL_RE", "INVOICE_LABEL_INTL_RE", "INVOICE_LABEL_RE", "INVOICE_LABEL_UTILITY_RE",
    "INVOICE_TITLE_RE", "INVOICE_TOKEN_RE", "LABEL_ONLY_INTL_RE", "LABEL_ONLY_RE", "LABEL_ONLY_UTILITY_RE",
    "LEGAL_FORM_INTL_RE", "LEGAL_FORM_RE", "LEGAL_FORM_UTILITY_RE", "MONEY_INTL_RE", "MONEY_RE", "NAME_STOP_RE",
    "NAME_TRAILING_ID_RE", "PARTIAL_HU_IBAN_RE", "PARTY_LABEL_INTL_RE", "PARTY_LABEL_RE", "PARTY_LABEL_UTILITY_RE",
    "PAYMENT_METHOD_LINE_RE", "PERCENT_AFTER_RE", "QUANTITY_LINE_RE", "QUANTITY_RE", "REVERSE_CHARGE_RE",
    "TAXID_CONTIGUOUS_RE", "TAXID_EU_INTL_RE", "TAXID_EU_RE", "TAXID_FORMATTED_RE", "TAXID_LABEL_HU_RE",
    "TAXID_LABEL_INTL_RE", "TAXID_LABEL_TOKEN_RE", "TAXID_OCR_RE", "TOTAL_LINE_RE", "_ADDRESS_TAIL_RE", "_ANY_LEGAL_FORM_RE",
    "_GREETING_RE", "_INCOMPLETE_LEGAL_FORM_RE", "_LEADING_ARTICLE_RE", "_NAME_GOES_ON_RE", "_NAME_TAIL_SEPARATOR_RE",
    "_PAREN_WRAP_RE",
]


def _moved() -> dict[str, object]:
    out: dict[str, object] = {name: [getattr(candidates, name).pattern, getattr(candidates, name).flags] for name in NAMES}
    out["IBAN_RES"] = [rx.pattern for rx in candidates.IBAN_RES]
    out["currency:base"] = {code: rx.pattern for code, rx in candidates.CURRENCY_TOKENS.items()}
    out["currency:intl"] = {code: rx.pattern for code, rx in candidates.CURRENCY_TOKENS_INTL.items()}
    out["limits"] = {"max_name_fallback": candidates.MAX_NAME_FALLBACK, "context_max_chars": candidates.CONTEXT_MAX_CHARS,
                     "max_quantity_options": candidates.MAX_QUANTITY_OPTIONS, "text_value_max": candidates.TEXT_VALUE_MAX}
    out["text_strip"] = candidates._TEXT_STRIP
    return out


def test_every_pattern_and_limit_is_the_one_the_code_had():
    digest = hashlib.sha256(json.dumps(_moved(), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    assert digest[:16] == MOVED_DIGEST


def test_the_code_compiles_no_pattern_of_its_own():
    """A new pattern goes into the rule file: the module compiles only the one it derives from every profile."""
    source = (PROJECT_ROOT / "jav/ai/candidates.py").read_text(encoding="utf-8")
    assert re.findall(r"^(_?[A-Z][A-Z0-9_]*) = re\.compile", source, re.M) == ["_ANY_LEGAL_FORM_RE"]


def test_every_pattern_has_a_note_and_every_profile_names_known_patterns():
    data = cfg.load("candidate_profiles")
    assert all(spec["note"] for spec in data["patterns"].values())
    for name, spec in data["profiles"].items():
        named = [spec[k] for k in ("legal_form", "party_label", "label_only", "invoice_label", "money", "address_label",
                                   "taxid_label") if spec[k] is not None] + spec["extra_iban"] + spec["extra_taxid"]
        assert set(named) <= set(data["patterns"]), name
        assert spec["currency_tokens"] in data["currency_tokens"], name
    assert {typepack.get(k).candidate_profile for k in typepack.keys()} <= set(candidates.PROFILES)


def test_two_switches_of_the_profile_replace_its_name():
    assert [p.name for p in candidates.PROFILES.values() if p.name_fallback_combined] == ["hu"]
    assert {p.name: p.evidence_intl for p in candidates.PROFILES.values()} == {"hu": False, "intl": True, "utility": True}
    assert site_for("invoice_hu").intl is False and site_for("viz_szamla").intl is True
    assert "candidate_profiles" in site_for("invoice_hu").hash_names


def test_a_new_profile_is_data_alone():
    spec = {**cfg.load("candidate_profiles")["profiles"]["hu"], "max_money_options": 2, "name_fallback_combined": False}
    profile = candidates._profile("sample", spec)
    lines = [LineLayout(no=i, page=1, text=t) for i, t in enumerate(["Nettó összesen: 1 000 Ft", "Áfa: 270 Ft",
                                                                     "Bruttó összesen: 1 270 Ft"], 1)]
    assert len(candidates.find_all(lines, profile)["money"]) == 2
    assert len(candidates.find_all(lines, "hu")["money"]) == 3
