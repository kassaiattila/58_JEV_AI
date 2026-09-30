"""OCR chain + utility round (BACKLOG 7 + 1) - offline, without the API and tesseract.

- OCR: tesseract TSV word boxes, converted to points, give a layout through the same line / cell builder as the text
  layer; the cache hits on the second call; the quality signals are raw, and the policy's `ocr` thresholds produce the
  review reasons;
- both graphs (invoice, doc_detect) contain the `ocr_pdf` step and the contract lint passes (test_contract);
- type packs: the six utility packs inherit the base pack (fields, validators, schema), `keys()` does not list the base
  pack, and the G-path model contains the base + child fields;
- candidate finders: labelled text candidate (in the same cell / the next cell / below), quantity candidates from lines
  with units, OCR-tolerant tax number and date, trimming of company names embedded in sentences, the Hungarian profile's
  behaviour unchanged;
- S-path call site: asks only for the pack's fields, the closed extra question only for a pack field, the option
  context trimmed;
- golden: OCR-tolerant second score; adapter: the server's error type in the review reasons.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from typesafe_sdk import Choice, Noul

from jav import candidates as cand, evals, ocr, pdf as pdfmod, policy, typepack
from jav.models import Candidate, CellLayout, LineLayout

UTILITY_TYPES = ("villamos_energia_szamla", "foldgaz_szamla", "viz_szamla", "mohu_szamla", "vizmuvek_szamla", "csatorna_szamla")


def _line(no: int, *cells: tuple[str, float]) -> LineLayout:
    return LineLayout(no=no, page=1, text="   ".join(t for t, _ in cells), cells=[CellLayout(text=t, x0=x, x1=x + 6 * len(t)) for t, x in cells])


# --- OCR ----------------------------------------------------------------------------------------

_TSV_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def _tsv(words: list[tuple[str, int, int, int, int, float]]) -> str:
    rows = [_TSV_HEADER, "1\t1\t0\t0\t0\t0\t0\t0\t2480\t3508\t-1\t"]
    for i, (text, left, top, w, h, conf) in enumerate(words, 1):
        rows.append(f"5\t1\t1\t1\t1\t{i}\t{left}\t{top}\t{w}\t{h}\t{conf}\t{text}")
    return "\n".join(rows) + "\n"


def test_parse_tsv_converts_pixels_to_points_and_drops_empty_words():
    tsv = _tsv([("Számla", 300, 600, 250, 40, 96.5), ("sorszáma:", 570, 600, 300, 40, 91.0), ("", 900, 600, 10, 40, -1.0), ("800012345678", 900, 602, 500, 40, 88.0)])
    words, confs = ocr.parse_tsv(tsv, dpi=300)
    assert [w["text"] for w in words] == ["Számla", "sorszáma:", "800012345678"]
    assert words[0]["x0"] == pytest.approx(300 * 72 / 300) and words[0]["top"] == pytest.approx(144.0)
    assert confs == [96.5, 91.0, 88.0]


def test_build_layout_from_ocr_words_groups_lines_and_cells_with_scan_tolerance():
    tsv = _tsv([
        ("Szolgáltató", 200, 1000, 300, 40, 95), ("neve:", 520, 1004, 150, 40, 95), ("MVM", 700, 1002, 120, 40, 95), ("Next", 840, 1001, 120, 40, 95),
        ("Dr.", 1900, 1010, 80, 40, 90), ("Minta-Kovács", 2000, 1008, 350, 40, 90),  # same line, other column (large gap)
        ("Adószáma:", 200, 1080, 250, 40, 95), ("26903570-2-44", 480, 1082, 400, 40, 95),
    ])
    words, _ = ocr.parse_tsv(tsv)
    layout = pdfmod.build_layout([words], y_tol=ocr._y_tolerance([words]))
    assert [ln.text for ln in layout] == ["Szolgáltató neve: MVM Next   Dr. Minta-Kovács", "Adószáma: 26903570-2-44"]
    assert [c.text for c in layout[0].cells] == ["Szolgáltató neve: MVM Next", "Dr. Minta-Kovács"]
    assert layout[0].page == 1 and layout[1].no == 2


def test_ocr_pdf_uses_fake_engine_and_disk_cache(tmp_path, monkeypatch):
    pdf_file = tmp_path / "scan.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake")
    tsv = _tsv([(w, 200 + 200 * i, 1000, 180, 40, 90 if i % 2 else 55) for i, w in enumerate(
        "Villamos energia elszámoló számla Számla sorszáma: 800012345678 Adószáma: 26903570-2-44 Fizetendő összeg: 54.732 Ft 2025.10.01".split()
    )])
    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "ocr_cache")
    monkeypatch.setattr(ocr, "engine", lambda want=None: "native")
    monkeypatch.setattr(ocr, "engine_version", lambda eng: "tesseract vTEST")
    monkeypatch.setattr(ocr, "render_pages", lambda path, out_dir, **kw: [out_dir / "p-1.png"])
    calls = []
    monkeypatch.setattr(ocr, "_run_tesseract", lambda png, out_base, psm=None, eng="native": (calls.append(png), tsv)[1])
    first = ocr.ocr_pdf(pdf_file, page_count=1)
    assert first.text_source == "ocr" and first.has_text_layer is False and first.page_count == 1
    assert first.ocr["cached"] is False and first.ocr["engine"] == "native" and first.ocr["words"] == 14
    assert 0.6 < first.ocr["mean_conf"] < 0.8 and first.ocr["low_conf_ratio"] == pytest.approx(0.5)
    assert "800012345678" in first.text and len(calls) == 1
    second = ocr.ocr_pdf(pdf_file, page_count=1)
    assert second.ocr["cached"] is True and second.text == first.text and len(calls) == 1  # did not run again
    assert len(list((tmp_path / "ocr_cache").glob("*.json"))) == 1


def test_read_document_falls_back_to_ocr_only_without_text_layer(monkeypatch):
    seen = []

    def fake_ocr(path, page_count=None):
        seen.append(path)
        return pdfmod.PdfText(path=str(path), text="x", text_source="ocr", ocr={"mean_conf": 0.9})

    monkeypatch.setattr(pdfmod, "read_pdf", lambda p: pdfmod.PdfText(path=str(p), text="", has_text_layer=False, page_count=2))
    monkeypatch.setattr(ocr, "ocr_pdf", fake_ocr)
    assert pdfmod.read_document("x.pdf").text_source == "ocr" and seen == ["x.pdf"]
    monkeypatch.setattr(pdfmod, "read_pdf", lambda p: pdfmod.PdfText(path=str(p), text="valódi szöveg", has_text_layer=True, text_source="pdf"))
    assert pdfmod.read_document("y.pdf").text_source == "pdf" and seen == ["x.pdf"]  # no OCR when there is a text layer


def test_policy_ocr_review_reasons_thresholds():
    assert policy.ocr_review_reasons(0.9, 0.1) == []
    assert policy.ocr_review_reasons(0.5, 0.1) == ["ocr:low_confidence:0.50"]
    assert policy.ocr_review_reasons(0.9, 0.5) == ["ocr:low_conf_words:0.50"]
    assert policy.ocr_review_reasons(None, None) == []


def test_flows_contain_ocr_step():
    from jav import flow, flow_detect

    assert "ocr_pdf" in {s for s, _ in flow.CONTRACT["steps"]} and "ocr_pdf" in {s for s, _ in flow_detect.CONTRACT["steps"]}
    assert ("load_pdf", "ocr_pdf") in {(e[0], e[1]) for e in flow.CONTRACT["edges"]}
    assert ("ocr_pdf", "needs_ocr") in {(e[0], e[1]) for e in flow_detect.CONTRACT["edges"]}


# --- type packs -------------------------------------------------------------------------------------


def test_utility_packs_extend_base():
    base_fields = ["supplier_name", "supplier_tax_id", "supplier_address", "supplier_bank_account", "customer_name"]
    for key in UTILITY_TYPES:
        p = typepack.get(key)
        assert p.extends == "utility_bill_hu" and list(p.fields)[:5] == base_fields
        assert p.select_callsite == "select_utility" and p.verify_callsite == "verify_utility" and p.candidate_profile == "utility"
        assert ("invoice_number", "amount_due") == p.required[:2]
        assert [v["check"] for v in p.validators][:3] == ["date_order", "hu_tax_id", "format"] and any(v["check"] == "vat_consistency" for v in p.validators)
        assert set(p.informational_fields) >= {"supplier_address", "supplier_bank_account", "customer_id", "customer_code"}
        assert all(p.fields[f] == "text" for f in p.text_labels)
        assert p.schema_files == ("utility_bill_hu_schema.json", p.schema_file)
    v = typepack.get("villamos_energia_szamla")
    assert v.required == ("invoice_number", "amount_due", "consumption_kwh") and v.fields["consumption_kwh"] == "number"
    assert "_base/utility_bill_hu" not in typepack.keys() and set(UTILITY_TYPES) <= set(typepack.keys())
    assert v.config_hash != typepack.get("foldgaz_szamla").config_hash


def test_utility_llm_model_has_base_and_child_fields():
    m = typepack.get("foldgaz_szamla").llm_model()
    names = list(m.model_fields)
    assert names[:2] == ["supplier_name", "supplier_tax_id"] and "consumption_mj" in names and names[-1] == "line_items"
    out = m(supplier_name="MVM Next Energiakereskedelmi Zrt.", consumption_m3="1967.17", line_items=[{"description": "Gázdíj", "quantity": 12.0}])
    assert out.consumption_m3 == "1967.17" and out.line_items[0].description == "Gázdíj"
    with pytest.raises(Exception):
        m(nem_letezo="x")


def test_candidate_kind_number_is_quantity():
    assert typepack.CANDIDATE_KIND_OF["number"] == "quantity"


# --- candidate finders ---------------------------------------------------------------------------------


def test_labelled_text_same_cell_next_cell_and_below():
    lines = [
        _line(1, ("Árszabás: ESZ \"A1\" Lakosság", 20)),
        _line(2, ("Fizetési mód:", 20), ("elektronikus", 145), ("A szolgáltatás megnevezése:", 351)),
        _line(3, ("Hulladékgazdálkodási közszolgáltatás", 351)),
        _line(4, ("Mérési pont azonosító:", 20), ("HU000210F11-E600000012345-1000001", 200)),
    ]
    tariff = cand.find_labelled_text(lines, "tariff", ("[áa]rszab[áa]s",))
    assert [c.label for c in tariff] == ['ESZ "A1" Lakosság']
    svc = cand.find_labelled_text(lines, "service_description", ("a\\s*szolg[áa]ltat[áa]s\\s*megnevez[ée]se",))
    assert [c.label for c in svc] == ["Hulladékgazdálkodási közszolgáltatás"]  # below; "közszolgáltatás" is not a label
    pod = cand.find_labelled_text(lines, "metering_point_id", ("m[ée]r[ée]si\\s*pont\\s*azonos[íi]t[óo]",))
    assert [c.label for c in pod] == ["HU000210F11-E600000012345-1000001"]
    assert tariff[0].kind == "text" and svc[0].line_no == 3


def test_find_all_with_text_labels_and_quantities():
    lines = [
        _line(1, ("Fogyasztás összesen: \"A1\" 882 kWh", 20), ("Elosztói engedélyes: ELMŰ Hálózati Kft", 400)),
        _line(2, ("9900000001   2025.08.01-2025,08.31   12.345   13.227   Leol   882   1   882", 20)),
        _line(3, ("Nettó számlaérték összesen   43.096", 20)),
        _line(4, ("Adószáma: 2690357 0-2-44", 20)),
        _line(5, ("Számla összesen:   21 238   5 734   26 972", 20)),
    ]
    out = cand.find_all(lines, "utility", text_labels={"tariff": ("[áa]rszab[áa]s",)})
    q = {c.label for c in out["quantity"]}
    assert {"882", "12345", "13227"} <= q and "5734" not in q  # only from lines with units / meter lines (and their neighbours)
    assert {"43096", "21238", "5734", "26972"} <= {c.label for c in out["money"]}  # the table's numbers stay money candidates
    assert [c.label for c in out["tax_id"]] == ["26903570-2-44"]  # OCR space in the labelled line
    assert {"2025-08-01", "2025-08-31"} <= {c.label for c in out["date"]}  # OCR date with a comma
    assert "ELMŰ Hálózati Kft" in {c.label for c in out["name"]}  # OCR-tolerant half label trimmed off
    assert out["text:tariff"] == []


def test_utility_names_cut_sentences_and_parentheses_and_keep_person_fallback():
    lines = [_line(i, (t, 20)) for i, t in enumerate([
        "(MVM Next Energiakereskedelmi Zrt.)",
        "A Díjbeszedő Holding Zrt. honlapján bankkártyával (www.dbrt.hu).",
        "az MVM Next Energiakereskedelmi Zrt. villanyszámlák",
        "MINTA-KOVÁCS ÉVA DR",
    ] * 20, 1)]
    names = {c.label for c in cand.find_names(lines, cand.UTILITY)}
    assert "MVM Next Energiakereskedelmi Zrt." in names and "Díjbeszedő Holding Zrt." in names
    assert "MINTA-KOVÁCS ÉVA DR" in names  # the private-person fallback is not crowded out by the many company names
    assert not any(n.startswith("(") or n.startswith("az ") for n in names)


def test_invoice_number_lookahead_two_lines_only_long_tokens():
    lines = [_line(1, ("Terhelési összesítő száma", 20)), _line(2, ("Részletek a hátoldalon", 20)), _line(3, ("600012345   27", 20)), _line(4, ("Számla összesen 21 238", 20))]
    work = [ln.text for ln in lines]
    labels = {c.label for c in cand.find_invoice_numbers(lines, work, cand.UTILITY)}
    assert "600012345" in labels and "27" not in labels  # two lines further down, only identifier-length tokens
    assert "21 238" in work[3]  # the short token outside the look-ahead range was not masked


def test_hu_profile_unchanged_by_utility_additions():
    lines = [
        _line(1, ("SZÁMLA", 20), ("Sorszám: E0006", 300)),
        _line(2, ("BestIxCom Kft.", 20), ("Adószám: 28642099-2-42", 300)),
        _line(3, ("Fizetendő összesen: 127 000 Ft", 20)),
    ]
    out = cand.find_all(lines, "hu")
    assert "E0006" in {c.label for c in out["invoice_number"]} and "127000" in {c.label for c in out["money"]}
    assert out["quantity"] == [] and cand.HU.max_money_options == cand.MAX_OPTIONS and cand.HU.invoice_lookahead == 1


# --- S-path call site -----------------------------------------------------------------------------------


class FakeJev:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []

    def ask(self, request_id, state, questions, *, run_id, use_cache, config_hash):
        from types import SimpleNamespace

        self.requests.append((request_id, questions))
        choices = {q: SimpleNamespace(choice=next(iter(v.criteria)), confidence=0.9, probabilities={next(iter(v.criteria)): 0.9}) for q, v in questions.items() if isinstance(v, Choice)}
        nouls = {q: SimpleNamespace(noul=0.8) for q, v in questions.items() if isinstance(v, Noul)}
        return SimpleNamespace(response=SimpleNamespace(choices=choices, nouls=nouls, model="jev-test"), call=SimpleNamespace(request_id=request_id, n_questions=len(questions), state_chars=0, cached=False, cost_usd=0.0, model_dump=lambda: {}), cached=False, cache_key="k")


def test_select_utility_asks_only_pack_fields_and_closed_extras():
    from jav.jev_select import site_for

    lines = [
        _line(1, ("Szolgáltató neve: MOHU MOL Hulladékgazdálkodási Zrt.", 20), ("Adószáma: 32197530-2-44", 400)),
        _line(2, ("Számla sorszáma: MH01234567", 20), ("Számla kelte: 2026.05.26.", 400)),
        _line(3, ("Fizetési mód:", 20), ("elektronikus", 145), ("A szolgáltatás megnevezése:", 351)),
        _line(4, ("Hulladékgazdálkodási közszolgáltatás", 351)),
        _line(5, ("Fizetendő összeg   3 266", 20)),
    ]
    mohu = typepack.get("mohu_szamla")
    site = site_for("mohu_szamla")
    assert site.option_context_max == 170 and site.request_order == ("utility_parties", "utility_header", "utility_money", "utility_meter")
    cands = cand.find_all(lines, mohu.candidate_profile, text_labels=mohu.text_labels)
    jev = FakeJev()
    picks, calls = site.select_fields(jev, lines, cands, run_id="t")
    asked = {rid: set(q) for rid, q in jev.requests}
    assert "reading_method" not in asked.get("utility_meter", set()) and "payment_method" in asked["utility_header"] and "currency" in asked["utility_money"]
    assert "service_description" in asked["utility_meter"] and "consumption_kwh" not in asked.get("utility_meter", set())  # not a pack field
    assert not any(f in picks for f in ("consumption_kwh", "distribution_licensee", "tariff"))
    inv, reasons = site.picks_to_invoice(picks, cands)
    assert inv.extra["service_description"] == "Hulladékgazdálkodási közszolgáltatás" and inv.payment_method == "Postai számlabefizetési megbízás"
    assert inv.amount_due == Decimal("3266") and reasons == []
    desc = site.build_choice("supplier_name", cands["name"]).criteria
    assert all(len(v) <= 170 + 60 for v in desc.values() if v)  # the context is trimmed


def test_select_utility_number_field_from_quantity_candidates():
    from jav.jev_select import site_for

    lines = [_line(1, ("Fogyasztás összesen: 882 kWh", 20)), _line(2, ("Bruttó számlaérték összesen 54.732", 20))]
    v = typepack.get("villamos_energia_szamla")
    cands = cand.find_all(lines, v.candidate_profile, text_labels=v.text_labels)
    picks, _ = site_for("villamos_energia_szamla").select_fields(FakeJev(), lines, cands, run_id="t")
    assert picks["consumption_kwh"].label == "882" and picks["consumption_kwh"].n_options >= 1
    inv, _ = site_for("villamos_energia_szamla").picks_to_invoice(picks, cands)
    assert inv.extra["consumption_kwh"] == Decimal("882")


def test_verify_utility_inherits_and_number_evidence():
    from jav.jev_verify import find_evidence, site_for

    site = site_for("foldgaz_szamla")
    assert site.request_id == "verify_utility" and "off_target" in site.nouls and "consumption_mj" in site.field_specs
    lines = [_line(1, ("Elszámolt hőmennyiség: 67 421 MJ", 20))]
    assert find_evidence("consumption_mj", "67421", lines, kind="number")


def test_evidence_reads_the_raw_value_like_the_record_does():
    # 054: GPT's raw value is "1.153" (Hungarian thousands separator); the record reads it as 1153, and the evidence
    # search must do the same
    from jav.jev_verify import find_evidence

    lines = [_line(1, ("Fogyasztás összesen: 1.153 kWh", 20))]
    assert find_evidence("consumption_kwh", "1.153", lines, kind="number")
    assert find_evidence("consumption_kwh", "1153", lines, kind="number")
    assert not find_evidence("consumption_kwh", "1154", lines, kind="number")
    # the line that also matches digit for digit comes first (the ordinal "1." does not beat the factor "1.0000")
    lines = [_line(1, ("1. sz. eredeti példány", 20)), _line(2, ("Korrekciós tényező 1.0000", 20))]
    assert find_evidence("correction_factor", "1,0000", lines, kind="number")[0].startswith("L02")


def test_evidence_tolerates_ocr_confusions_in_text():
    # 054: OCR read "A1" as "Al"; GPT correctly gave "A1" from the image
    from jav.jev_verify import find_evidence

    lines = [_line(1, ('Árszabás: ESZ "Al" Lakosság', 20))]
    assert find_evidence("tariff", 'ESZ "A1" Lakosság', lines, kind="text")
    assert not find_evidence("tariff", 'ESZ "A2" Lakosság', lines, kind="text")


# --- golden / adapter ------------------------------------------------------------------------------------


def test_lenient_equality_folds_ocr_accents_only_for_text_kinds():
    assert evals.field_equal_lenient("supplier_name", "MOHU MOL Hulladékgazdalkodasi Zrt.", "MOHU MOL Hulladékgazdálkodási Zrt.", "name")
    assert evals.field_equal_lenient("customer_address", "1234 MINTAVAROS FO UT 1.", "1234 Mintaváros Fő út 1.", "address")
    assert not evals.field_equal_lenient("vat_total", "515", "5152", "money")
    assert not evals.field_equal("supplier_name", "MOHU MOL Hulladékgazdalkodasi Zrt.", "MOHU MOL Hulladékgazdálkodási Zrt.", "name")


def test_error_slug_includes_server_error_type():
    from jav.adapters.jev import _error_slugs

    class Err(Exception):
        status = 400
        body = {"detail": {"error_type": "max_tokens_exceeded"}}

    reason, ledger, _ = _error_slugs(Err())
    assert reason == "Err:400:max_tokens_exceeded" and ledger == reason


# --- Azure DI engine + escalation (handoff 013 §8) ------------------------------------------------------


def test_azure_evidence_words_convert_inches_to_points_and_percent_confidence():
    evidence = {"model_id": "prebuilt-read", "api_version": "2024-11-30", "pages": [{"unit": "inch", "words": [
        {"content": "Fizetési", "polygon": [0.5, 1.0, 1.2, 1.0, 1.2, 1.15, 0.5, 1.15], "confidence": 0.99},
        {"content": "határidő:", "polygon": [1.25, 1.0, 2.0, 1.0, 2.0, 1.15, 1.25, 1.15], "confidence": 0.98},
        {"content": "", "polygon": [2.1, 1.0, 2.2, 1.0, 2.2, 1.1, 2.1, 1.1], "confidence": 0.5},
        {"content": "2025.10.01", "polygon": [2.3, 1.01, 3.1, 1.01, 3.1, 1.15, 2.3, 1.15], "confidence": 0.97},
    ]}]}
    pages, confs, meta = ocr.azure_evidence_words(evidence)
    assert [w["text"] for w in pages[0]] == ["Fizetési", "határidő:", "2025.10.01"] and confs == [99.0, 98.0, 97.0]
    assert pages[0][0]["x0"] == pytest.approx(36.0) and pages[0][0]["top"] == pytest.approx(72.0) and meta["model_id"] == "prebuilt-read"
    layout = pdfmod.build_layout(pages, y_tol=ocr._y_tolerance(pages))
    assert len(layout) == 1 and layout[0].text.startswith("Fizetési határidő:") and layout[0].text.endswith("2025.10.01")  # one line, gap = cell boundary


def test_engine_selection_never_auto_picks_azure(monkeypatch):
    monkeypatch.delenv(ocr.ENGINE_ENV, raising=False)
    ocr.engine.cache_clear()
    monkeypatch.setattr(ocr, "native_exe", lambda: "tesseract.exe")
    assert ocr.engine() == "native" and ocr.engine("azure_di") == "azure_di"
    monkeypatch.setenv(ocr.ENGINE_ENV, "azure_di")
    ocr.engine.cache_clear()
    assert ocr.engine() == "azure_di"
    ocr.engine.cache_clear()


def test_ocr_escalation_switches_to_better_engine_only_when_weak(monkeypatch):
    monkeypatch.delenv(ocr.ENGINE_ENV, raising=False)
    monkeypatch.setitem(ocr.ESCALATION, "enabled", True)
    monkeypatch.setitem(ocr.ESCALATION, "engine", "azure_di")
    calls = []

    def fake_ocr(path, page_count=None, use_cache=True, psm=None, engine_name=None):
        calls.append(engine_name)
        conf = 0.99 if engine_name == "azure_di" else 0.8
        return pdfmod.PdfText(path=str(path), text="x", text_source="ocr", ocr={"engine": engine_name or "native", "mean_conf": conf, "low_conf_ratio": 0.15 if conf < 0.9 else 0.0})

    monkeypatch.setattr(ocr, "ocr_pdf", fake_ocr)
    pdf, escalated = ocr.ocr_with_escalation("weak.pdf")
    assert escalated and pdf.ocr["engine"] == "azure_di" and pdf.ocr["escalated_from"] == "native" and calls == [None, "azure_di"]
    calls.clear()
    monkeypatch.setattr(ocr, "ocr_pdf", lambda path, **kw: pdfmod.PdfText(path=str(path), text="x", text_source="ocr", ocr={"engine": "native", "mean_conf": 0.95, "low_conf_ratio": 0.02}))
    pdf, escalated = ocr.ocr_with_escalation("good.pdf")
    assert not escalated and pdf.ocr["engine"] == "native"
    monkeypatch.setitem(ocr.ESCALATION, "enabled", False)
    monkeypatch.setattr(ocr, "ocr_pdf", fake_ocr)
    pdf, escalated = ocr.ocr_with_escalation("weak.pdf")
    assert not escalated and calls == [None]


def test_policy_ocr_should_escalate_thresholds():
    assert policy.ocr_should_escalate(0.85, 0.05) and policy.ocr_should_escalate(0.95, 0.2)
    assert not policy.ocr_should_escalate(0.95, 0.05) and not policy.ocr_should_escalate(None, None)


# --- request-size budget: candidate trimming in document order + retry on a token error (handoff 015) ------------


def _many_names(n_far: int, wanted_line: int) -> list[Candidate]:
    """n_far names with a legal form from the end of the document (at the start of the candidate list, as in the
    `find_names` bucket), and one private person's name from the top block at the END of the list (fallback names go
    into the bucket after the names with a legal form)."""
    far = [Candidate(kind="name", label=f"Cég {i} Zrt.", raw=f"Cég {i} Zrt.", line_no=150 + i, context=f"L{150 + i}: Cég {i} Zrt.") for i in range(n_far)]
    return far + [Candidate(kind="name", label="MINTA-KOVÁCS ÉVA DR", raw="MINTA-KOVÁCS ÉVA DR", line_no=wanted_line, context=f"L{wanted_line}: ügyfél")]


def test_fit_budget_cap_keeps_document_order_so_top_block_names_survive():
    from jav.jev_select import site_for

    site = site_for("viz_szamla")
    lines = [_line(i, (f"sor {i}", 20)) for i in range(1, 260)]
    cands = {"name": _many_names(90, wanted_line=9)}
    questions = {"customer_name": site.build_choice("customer_name", cands["name"])}
    state = {"document": "x", "lines": [ln.model_dump() for ln in lines]}
    site.request_char_budget = 1  # forced trimming down to the tightest level
    _, trimmed = site._fit_budget("utility_parties", state, questions, lines, cands, ["customer_name"])
    crit = trimmed["customer_name"].criteria
    assert "MINTA-KOVÁCS ÉVA DR" in crit and len(crit) <= 41  # the top block's name stays within the cap of 40 (document order)


def test_select_retries_once_with_tighter_budget_on_max_tokens_error():
    from jav.adapters.jev import JevUnavailableError
    from jav.jev_select import site_for

    class TokenLimitJev(FakeJev):
        def __init__(self, fail_times: int) -> None:
            super().__init__()
            self.fail_times = fail_times
            self.sizes: list[int] = []

        def ask(self, request_id, state, questions, **kw):
            self.sizes.append(len(json.dumps(state, ensure_ascii=False)) + sum(len(json.dumps(dict(q.criteria))) for q in questions.values() if isinstance(q, Choice)))
            if self.fail_times > 0:
                self.fail_times -= 1
                raise JevUnavailableError("TypeSafeBadRequestError:400:max_tokens_exceeded")
            return super().ask(request_id, state, questions, **kw)

    site = site_for("viz_szamla")
    lines = [_line(i, (f"sor {i} Cég {i} Zrt.", 20)) for i in range(1, 260)]
    cands = {"name": _many_names(90, wanted_line=9)}
    site.request_char_budget = 10_000_000  # the first request is not trimmed, yet the server gives a token error
    jev = TokenLimitJev(fail_times=1)
    picks, calls = site.select_fields(jev, lines, cands, run_id="t")
    assert len(jev.sizes) >= 2 and jev.sizes[1] < jev.sizes[0]  # retried once, with a tighter request
    assert picks["customer_name"].label is not None and len(calls) >= 1
    # another error (or a second token error) is not retried: the exception reaches the flow (jev_unavailable reviews)
    with pytest.raises(JevUnavailableError):
        site.select_fields(TokenLimitJev(fail_times=2), lines, cands, run_id="t")


def test_verify_fits_budget_by_keeping_only_evidence_lines_and_retries_once():
    from jav.adapters.jev import JevUnavailableError
    from jav.jev_verify import site_for

    class RecordingJev(FakeJev):
        def __init__(self, fail_times: int = 0) -> None:
            super().__init__()
            self.fail_times = fail_times
            self.states: list[dict] = []

        def ask(self, request_id, state, questions, **kw):
            self.states.append(state)
            if self.fail_times > 0:
                self.fail_times -= 1
                raise JevUnavailableError("TypeSafeBadRequestError:400:max_tokens_exceeded")
            return super().ask(request_id, state, questions, **kw)

    site = site_for("mohu_szamla")
    lines = [_line(i, (f"tájékoztató szöveg {i} " * 8, 20)) for i in range(1, 200)]
    lines[1] = _line(2, ("Szolgáltató neve: MOHU MOL Hulladékgazdálkodási Zrt.", 20), ("Adószáma: 32197530-2-44", 400))
    lines[150] = _line(151, ("Fizetendő összeg   3 266", 20))
    llm = {"supplier_name": "MOHU MOL Hulladékgazdálkodási Zrt.", "supplier_tax_id": "32197530-2-44", "amount_due": "3266"}
    # no budget: the whole document is sent
    site.request_char_budget = None
    jev = RecordingJev()
    site.verify(jev, lines, llm, run_id="t")
    assert len(jev.states[0]["source_lines"]) == len(lines)
    # budget below the full text: only the evidence lines (± 1) remain; the questions and glossary are unchanged
    site.request_char_budget = site._size(jev.states[0], {}) - 1000
    jev = RecordingJev()
    verdicts, _ = site.verify(jev, lines, llm, run_id="t")
    kept = jev.states[0]["source_lines"]
    assert 0 < len(kept) < 12 and any(s.startswith("L02:") for s in kept) and any(s.startswith("L151:") for s in kept)
    assert "glossary" in jev.states[0] and verdicts.flags
    # if even the evidence lines do not fit: the lines are dropped, the questions (with printed_on evidence) are sent
    site.request_char_budget = 1
    jev = RecordingJev()
    site.verify(jev, lines, llm, run_id="t")
    assert "source_lines" not in jev.states[0] and "glossary" in jev.states[0]
    # generous budget, but the server gives a token error: one retry with a tighter request
    site.request_char_budget = 10_000_000
    jev = RecordingJev(fail_times=1)
    site.verify(jev, lines, llm, run_id="t")
    assert len(jev.states) == 2 and len(jev.states[1]["source_lines"]) < len(jev.states[0]["source_lines"])
    with pytest.raises(JevUnavailableError):
        site.verify(RecordingJev(fail_times=2), lines, llm, run_id="t")
