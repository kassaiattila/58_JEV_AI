"""M1 - dokumentum-kategorizálás Jevvel: egy kérés, három ítélet. A kérdéskészlet a `configs/callsites/detect.json`-ból.

- Choice `doc_type` a regisztrált típusok fölött (+ `unknown`), confidence = a régi logprob-margin helyett;
- Noul `issuer_is_hungarian` (a régi szabály: a KIÁLLÍTÓ honossága dönt invoice_hu / invoice_foreign közt);
- Choice `language` (hu / en / de / other) - olcsó, hasznos routing-jel.

State: fájlnév, oldalszám, az első ~40 és utolsó ~8 sor (fejléc + lábléc: Számlázz.hu, NAV Online Számlázó,
bank-brand), kód-oldali feature-ök (magyar adószám / EU-áfaszám jelenléte, pénznemek, IBAN, dátum-/összeg-szám)
és a régi detect.json anchor-találatok típusonként. Az anchorok feature-ök, a döntés a Jevé.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from typesafe_sdk import Choice, Noul

from jav import cfg
from jav.adapters.jev import JevAdapter
from jav.doc_types import PARENT_OF, UNKNOWN, anchor_hits, choice_criteria
from jav.models import DATE_NUMERIC_RE, DATE_TEXT_RE, JevCall
from jav.pdf import PdfText
from jav.registry import parent_summary

_CFG = cfg.load("callsite:detect")
CONFIG_HASH = cfg.config_hash("callsite:detect", "doc_types")  # a kérdések + a regiszter együtt
HEAD_LINES: int = _CFG["state"]["head_lines"]
TAIL_LINES: int = _CFG["state"]["tail_lines"]
MAX_LINE_CHARS: int = _CFG["state"]["max_line_chars"]

_HU_TAXID = re.compile(r"\b\d{8}-\d-\d{2}\b")
_EU_VAT = re.compile(r"\b(?:IE|DE|AT|NL|PL|CZ|SK|GB|FR|IT|ES|LU|BE|SE|DK|FI|RO|BG|HR|SI|LT|LV|EE|MT|CY|GR|PT)\s?[0-9A-Z]{8,12}\b")
_HU_EU_VAT = re.compile(r"\bHU\d{8}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[0-9A-Z]{4}){3,7}\b")
_CURRENCIES = {
    "HUF": re.compile(r"(?i)\bHUF\b|\bFt\b|\bforint\b"),
    "EUR": re.compile(r"(?i)\bEUR\b|€"),
    "USD": re.compile(r"(?i)\bUSD\b|\$"),
    "GBP": re.compile(r"(?i)\bGBP\b|£"),
    "PLN": re.compile(r"(?i)\bPLN\b|\bzł"),
}


class DetectResult(BaseModel):
    doc_type: str
    confidence: float
    probabilities: dict[str, float] = Field(default_factory=dict)
    issuer_hu: float
    language: str
    language_conf: float
    anchor_hits: dict[str, dict[str, int]] = Field(default_factory=dict)
    parent: str | None = None  # a legvalószínűbb típus családja (regiszter v2), kódban összegezve
    parent_prob: float = 0.0  # a család összesített valószínűsége - szülő-címke alacsony confidence-nél (policy dönt)
    call: JevCall

    @model_validator(mode="after")
    def _fill_parent(self) -> "DetectResult":
        if self.parent is None and self.probabilities:
            self.parent, self.parent_prob = parent_summary(self.probabilities, PARENT_OF)
        return self


def _clip(lines: list[str]) -> list[str]:
    return [ln[:MAX_LINE_CHARS] for ln in lines]


def build_state(pdf: PdfText, path: str | Path) -> dict:
    lines = pdf.lines
    head = _clip(lines[:HEAD_LINES])
    tail = _clip(lines[-TAIL_LINES:]) if len(lines) > HEAD_LINES + TAIL_LINES else []
    text = pdf.text
    features = {
        "hungarian_tax_ids": len(set(_HU_TAXID.findall(text))),
        "hu_eu_vat_ids": len(set(_HU_EU_VAT.findall(text))),
        "foreign_eu_vat_ids": len({m for m in _EU_VAT.findall(text) if not m.startswith("HU")}),
        "ibans": len(set(_IBAN.findall(text))),
        "currencies": [c for c, rx in _CURRENCIES.items() if rx.search(text)],
        "dates": len(DATE_NUMERIC_RE.findall(text)) + len(DATE_TEXT_RE.findall(text)),
        "lines": len(lines),
        "page_count": pdf.page_count,
    }
    return {
        "filename": Path(path).name,
        "features": features,
        "anchor_hits": anchor_hits(text),
        "head_lines": [f"L{i:02d}: {ln}" for i, ln in enumerate(head, 1)],
        "tail_lines": [f"L{len(lines) - len(tail) + i:02d}: {ln}" for i, ln in enumerate(tail, 1)] if tail else [],
    }


def build_questions() -> dict[str, Choice | Noul]:
    """A JSON kérdéskészlet -> SDK-objektumok; a `registry:doc_types` kritérium a regiszterből jön."""
    out: dict[str, Choice | Noul] = {}
    for key, q in _CFG["questions"].items():
        crit = q["criteria"]
        if crit == "registry:doc_types":
            crit = choice_criteria()
        if q["kind"] == "choice":
            out[key] = Choice(instructions=q["instructions"], criteria=crit)
        else:
            out[key] = Noul(instructions=q["instructions"], criteria=crit)
    return out


def detect(jev: JevAdapter, pdf: PdfText, path: str | Path, *, run_id: str = "adhoc", use_cache: bool = True) -> DetectResult:
    state = build_state(pdf, path)
    result = jev.ask("detect", state, build_questions(), run_id=run_id, use_cache=use_cache, config_hash=CONFIG_HASH)
    r = result.response
    dt, lang = r.choices["doc_type"], r.choices["language"]
    return DetectResult(
        doc_type=dt.choice if dt.choice else UNKNOWN,
        confidence=float(dt.confidence),
        probabilities={k: round(float(v), 4) for k, v in dict(dt.probabilities).items()},
        issuer_hu=float(r.nouls["issuer_is_hungarian"].noul),
        language=lang.choice,
        language_conf=float(lang.confidence),
        anchor_hits=state["anchor_hits"],
        call=result.call,
    )
