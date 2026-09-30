"""BACKLOG 1: az ellenőrző-szonda mint nyers futás (sáv-összegzés, telefonszám-variáns) és a strukturált Noul-instrukció.

Offline: nincs Jev-hívás; a szonda összegzője és az elrontó függvény tiszta függvény, a kérdés-építő csak a JSON-t olvassa.
"""

from __future__ import annotations

import json

from jav import policy
from jav.evals import perturb_extraction, probe_summary
from jav.models import LineLayout


def _lines(*texts: str) -> list[LineLayout]:
    return [LineLayout(no=i, page=1, text=t) for i, t in enumerate(texts, 1)]


HEADER = {
    "supplier_name": "Teszt Kft.",
    "supplier_tax_id": "12345678-1-42",
    "buyer_name": "Vevő Zrt.",
    "buyer_tax_id": "87654321-2-13",
    "invoice_number": "INV-2026-001",
    "issue_date": "2026-01-05",
    "fulfillment_date": "2026-01-05",
    "due_date": "2026-01-15",
    "currency": "HUF",
    "net_total": "1000",
    "vat_total": "270",
    "gross_total": "1270",
    "payment_iban": None,
}


def test_perturb_variants_stable_set():
    """Az elrontás-készlet: tökéletes + 4 hiba; nettó := bruttó csak ha van áfa; telefon-variáns csak ha van telefonszám."""
    variants = perturb_extraction(HEADER, _lines("Teszt Kft.", "Adószám: 12345678-1-42"))
    assert set(variants) == {"perfect", "parties_swapped", "truncated_supplier", "invoice_number_emptied", "net_is_gross"}
    assert variants["perfect"] == HEADER
    assert variants["parties_swapped"]["supplier_name"] == "Vevő Zrt." and variants["parties_swapped"]["buyer_tax_id"] == "12345678-1-42"
    assert variants["truncated_supplier"]["supplier_name"] == "Teszt"
    assert variants["invoice_number_emptied"]["invoice_number"] is None
    assert variants["net_is_gross"]["net_total"] == "1270"
    no_vat = dict(HEADER, vat_total="0")
    assert "net_is_gross" not in perturb_extraction(no_vat, _lines("x"))


def test_perturb_adds_phone_variant_when_invoice_prints_a_phone_number():
    """A régi csapda (telefonszám adószámként, README): ha a számlán van telefonszám, az kerül a szállítói adószám helyére."""
    variants = perturb_extraction(HEADER, _lines("Teszt Kft.", "Tel.: +36 20 000 1234", "Adószám: 12345678-1-42"))
    assert "tax_id_is_phone" in variants
    assert variants["tax_id_is_phone"]["supplier_tax_id"] == "36200001234"
    assert variants["tax_id_is_phone"]["buyer_tax_id"] == HEADER["buyer_tax_id"]


def test_probe_summary_counts_bands_per_variant():
    """Kétoldali sáv a flagekre: variánsonként no / uncertain / yes darabszám, átlag, min, max; fals pozitív a tökéletesnél."""
    rows = [
        {"case_id": "a", "variant": "perfect", "target": "(none)", "p": 0.10, "false_positive": False},
        {"case_id": "b", "variant": "perfect", "target": "(none)", "p": 0.75, "false_positive": True},
        {"case_id": "a", "variant": "tax_id_is_phone", "target": "wrong_kind:supplier_tax_id", "p": 0.60, "false_positive": False},
        {"case_id": "b", "variant": "tax_id_is_phone", "target": "wrong_kind:supplier_tax_id", "p": 0.90, "false_positive": False},
    ]
    s = probe_summary(rows)
    assert s["perfect"]["n"] == 2 and s["perfect"]["false_positives"] == 1
    assert s["perfect"]["bands"] == {"no": 1, "uncertain": 0, "yes": 1}
    phone = s["tax_id_is_phone"]
    assert phone["bands"] == {"no": 0, "uncertain": 1, "yes": 1}
    assert phone["mean"] == 0.75 and phone["min"] == 0.60 and phone["max"] == 0.90
    # a sávok a policy `invoice.verify` hívási helyének küszöbeiből jönnek, nem a szondába írt számból
    assert policy.noul_band(0.60, "invoice.verify") == "uncertain"


def test_verify_config_is_structured():
    """v1.1.0: minden Noul `question` szöveget ad (sablon-helyőrző nélkül), a kód építi az objektumot."""
    from jav import cfg

    data = cfg.load("callsite:verify")
    assert tuple(int(x) for x in data["meta"]["version"].split(".")) >= (1, 1, 0)
    for name, q in data["nouls"].items():
        assert set(q) == {"question", "true", "false"}, name
        assert "{" not in q["question"] and "instructions" not in q, name


def test_build_questions_structured_instructions():
    """Az instrukció objektum (sde_cascade minta): field_spec {name, meaning}, extracted_field nyersen, printed_on, question, glossary."""
    from jav.jev_verify import FIELD_SPECS, build_questions
    from jav.jev_select import GLOSSARY
    from jav.models import InvoiceLLM

    llm = InvoiceLLM(supplier_name="Teszt Kft.", supplier_tax_id="12345678-1-42", net_total="1000")
    evidence = {"supplier_name": ["L01: Teszt Kft."], "supplier_tax_id": ["L02: Adószám: 12345678-1-42"]}
    q = build_questions(llm, evidence)
    ot = q["supplier_name__off_target"].instructions
    assert isinstance(ot, dict) and set(ot) == {"glossary", "field_spec", "extracted_field", "printed_on", "question"}
    assert ot["field_spec"] == {"name": "supplier_name", "meaning": FIELD_SPECS["supplier_name"]}
    assert ot["extracted_field"] == "Teszt Kft." and ot["printed_on"] == ["L01: Teszt Kft."]  # nyers érték, nem repr
    assert ot["glossary"] == GLOSSARY and "`printed_on`" in ot["question"]
    assert q["supplier_name__off_target"].criteria == {"true": "the value belongs to another field; it is wrongly placed here",
                                                       "false": "the value is the correct value for this field"}
    wk = q["supplier_tax_id__wrong_kind"].instructions
    assert wk["extracted_field"] == "12345678-1-42" and wk["field_spec"]["name"] == "supplier_tax_id"
    assert "net_total__off_target" not in q  # nincs evidencia -> unsupported, a Jevet nem kérdezzük
    aw = q["buyer_name__absence_wrong"].instructions
    assert set(aw) == {"glossary", "field_spec", "extracted_field", "question"} and aw["extracted_field"] is None
    ps = q["parties_swapped"].instructions
    assert set(ps) == {"glossary", "question"} and "SWAPPED" in ps["question"]
    assert all(isinstance(x.instructions, dict) for x in q.values())


def test_eval_report_reads_probe_rows_with_truth(tmp_path):
    """A szonda nyers futása az eval-riportba: hibás variánsnál a várt flag igazsága `igen`, a tökéletesnél a golden-mezők flagjei `nem`."""
    from jav.eval_report import flow_of, judgments_from_file

    rows = [
        {"case_id": "a", "variant": "perfect", "target": "(none)", "p": 0.1, "perfect_fields": ["supplier_name", "net_total"],
         "flags": {"supplier_name": {"off_target": 0.1, "incomplete": 0.05}, "supplier_address": {"absence_wrong": 0.8}},
         "doc_flags": {"parties_swapped": 0.1, "line_items_missing_rows": 0.9}},
        {"case_id": "a", "variant": "tax_id_is_phone", "target": "wrong_kind:supplier_tax_id", "p": 0.6, "perfect_fields": ["supplier_tax_id"],
         "flags": {"supplier_tax_id": {"off_target": 0.2, "wrong_kind": 0.6}}, "doc_flags": {"parties_swapped": 0.1}},
    ]
    path = tmp_path / "20260920_000000_verifier_probe.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert flow_of(path) == "invoice_verify_probe"
    js = judgments_from_file(path)
    truth = {(j.case_id, j.field, j.question): (j.expected, j.correct) for j in js}
    assert truth[("a/perfect", "supplier_name", "off_target")] == ("no", True)
    assert truth[("a/perfect", "supplier_address", "absence_wrong")] == (None, None)  # a golden nem fedi -> nincs igazság
    assert truth[("a/perfect", None, "parties_swapped")] == ("no", True)
    assert truth[("a/perfect", None, "line_items_missing_rows")] == (None, None)
    assert truth[("a/tax_id_is_phone", "supplier_tax_id", "wrong_kind")] == ("yes", True)  # 0,60 >= 0,5 címke: igen
    assert truth[("a/tax_id_is_phone", "supplier_tax_id", "off_target")] == (None, None)
    assert all(j.callsite == "invoice.verify" and j.kind == "noul" for j in js)
    assert all(j.run_no == 1 for j in js)  # a variánsok külön esetek, nem ugyanannak az esetnek az ismételt futásai
