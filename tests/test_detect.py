"""M1 detect - offline: type registry, anchor features, state building, legacy label mapping."""

from jav.detect import build_questions, build_state
from jav.doc_types import BY_KEY, DOC_TYPE_KEYS, OLD_TYPE_MAP, UNKNOWN, anchor_hits, choice_criteria
from jav.models import CellLayout, LineLayout
from jav.pdf import PdfText


def _pdf(lines: list[str]) -> PdfText:
    layout = [LineLayout(no=i, page=1, text=t, cells=[CellLayout(text=t, x0=30, x1=300)]) for i, t in enumerate(lines, 1)]
    return PdfText(path="x.pdf", text="\n".join(lines), lines=lines, layout=layout, page_count=1, has_text_layer=True)


def test_registry_consistent():
    assert UNKNOWN in DOC_TYPE_KEYS and "invoice_hu" in BY_KEY
    crit = choice_criteria()
    assert set(crit) == set(DOC_TYPE_KEYS)
    # every type has a substantive description and boundary (v2)
    assert all(len(v["what"]) > 40 and v["not_for"] for v in crit.values())
    assert set(OLD_TYPE_MAP.values()) <= set(DOC_TYPE_KEYS)


def test_anchor_hits_are_features_per_type():
    hits = anchor_hits("SZÁMLA Sorszám: PRB-2022-7 Adószám: 13570008-1-13 Fizetési határidő: 2022.02.25. Áfa")
    assert hits["invoice_hu"]["required_any"] >= 2 and hits["invoice_hu"]["supporting"] >= 2
    assert "invoice_hu" in hits and hits.get("utility_bill_hu") is None
    hits = anchor_hits("MVM Next villamos energia elszámoló számla mérőállás kWh felhasználási hely")
    assert hits["utility_bill_hu"]["required_any"] >= 3
    hits = anchor_hits("Invoice Upwork Global Inc. VAT reverse charge EUR")
    assert hits["invoice_foreign"]["required_any"] >= 1 and hits["invoice_hu"].get("excluders", 0) >= 1


def test_build_state_features():
    lines = ["SZÁMLA", "Adószám: 13570008-1-13", "Közösségi adószám: HU13570008", "IBAN: HU50 1000 0001 2000 0002 0000 0000",
             "Fizetési határidő: 2022.02.25.", "Összesen: 1 000 000 Ft"] + [f"sor {i}" for i in range(60)]
    st = build_state(_pdf(lines), "C:/x/2023/PRB-2022-7.pdf")
    assert st["filename"] == "PRB-2022-7.pdf"
    f = st["features"]
    assert f["hungarian_tax_ids"] == 1 and f["hu_eu_vat_ids"] == 1 and f["foreign_eu_vat_ids"] == 0
    assert f["ibans"] == 1 and f["currencies"] == ["HUF"] and f["dates"] == 1
    assert len(st["head_lines"]) == 40 and len(st["tail_lines"]) == 8
    assert st["head_lines"][0].startswith("L01: ")


def test_questions_shape():
    q = build_questions()
    assert set(q) == {"doc_type", "issuer_is_hungarian", "language"}
    assert set(q["doc_type"].criteria) == set(DOC_TYPE_KEYS)
