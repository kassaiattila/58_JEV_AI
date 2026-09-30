"""Source location (045 K3b, B2): on a synthetic word layer and in one full run, without AI calls."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jav import grounding, source_layer, store
from tests.pdfgen import INVOICE_LINES, write_text_pdf


def layer_of(rows: list[list[tuple[str, float]]], *, page_w: float = 600, page_h: float = 800):
    """(word, x0) pairs per line; space 4 pt, character width 6 pt, line height 12 pt, line pitch 20 pt."""
    words = []
    for n, row in enumerate(rows, 1):
        top = 40 + 20 * (n - 1)
        for text, x0 in row:
            words.append({"text": text, "x0": x0, "x1": x0 + 6 * len(text), "top": top, "bottom": top + 12, "line_no": n})
    return source_layer.build("d" * 64, [words], [(page_w, page_h)], text_source="pdf", engine="test")


def test_locate_raw_on_the_picked_line_is_exact():
    layer = layer_of([[("Szamlaszam:", 20), ("MINTA-1", 110)], [("Brutto:", 20), ("12", 110), ("700", 128), ("Ft", 152)]])
    words = grounding.locate_raw(layer, 2, "12 700")
    assert [w.text for w in words] == ["12", "700"]
    r = grounding.region(words)
    assert r["page"] == 1 and r["quote"] == "12 700" and len(r["boxes"]) == 1
    assert r["bbox"][0] == pytest.approx(110 / 600, abs=1e-4) and r["bbox"][1] == pytest.approx(60 / 800, abs=1e-4)
    glued = layer_of([[("Adoszam:13570008-1-13", 20)]])
    assert [w.text for w in grounding.locate_raw(glued, 1, "13570008-1-13")] == ["Adoszam:13570008-1-13"]
    assert grounding.locate_raw(layer, 1, "NINCS") is None


def test_repeated_value_is_decided_by_its_label():
    layer = layer_of([
        [("Netto", 20), ("osszeg:", 60), ("12", 200), ("700", 218)],
        [("Brutto", 20), ("osszeg:", 64), ("12", 200), ("700", 218)],
        [("Tetel", 20), ("12", 200), ("700", 218)],
    ])
    gross = grounding.locate_value(layer, "money", "12700", field="gross_total")
    assert gross["status"] == "located" and gross["page"] == 1 and gross["word_ids"] == [6, 7]
    no_field = grounding.locate_value(layer, "money", "12700")
    # 053 (decision of 2026-09-28): even without a field, the first location gets a box, the rest are alternatives
    assert no_field["status"] == "located" and no_field["multiple"] == 3 and len(no_field["alternatives"]) == 2


def test_other_fields_label_rejects_the_only_hit():
    layer = layer_of([[("Teljesites", 20), ("datuma:", 90), ("2026.09.01.", 200)]])
    r = grounding.locate_value(layer, "date", "2026-09-01", field="issue_date")
    assert r["status"] == "context_rejected" and r["alternatives"][0]["quote"] == "2026.09.01."
    assert grounding.locate_value(layer, "date", "2026-09-01", field="fulfillment_date")["status"] == "located"


def test_part_of_a_bigger_number_is_not_a_match():
    layer = layer_of([[("Osszesen:", 20), ("12", 200), ("700", 218), ("Ft", 242)]])
    assert grounding.locate_value(layer, "money", "700", field="gross_total")["status"] == "not_found"


def test_name_wrapped_to_two_lines_is_found():
    layer = layer_of([[("Elado:", 20), ("Minta", 80), ("Kereskedelmi", 116)], [("Korlatolt", 80), ("Kft.", 140)]])
    r = grounding.locate_value(layer, "name", "Minta Kereskedelmi Korlatolt Kft.", field="supplier_name")
    assert r["status"] == "located" and len(r["boxes"]) == 2 and r["quote"] == "Minta Kereskedelmi Korlatolt Kft."


def test_picks_give_location_and_ranked_alternatives():
    layer = layer_of([[("Brutto:", 20), ("12", 110), ("700", 128)], [("Netto:", 20), ("10", 110), ("000", 128)]])
    cands = {"money": [SimpleNamespace(label="12700", raw="12 700", line_no=1),
                       SimpleNamespace(label="10000", raw="10 000", line_no=2)]}
    pick = SimpleNamespace(label="12700", raw="12 700", line_no=1, probabilities={"12700": 0.9, "10000": 0.08, "none": 0.02},
                           present_p=0.99)
    out = grounding.ground_picks(layer, fields={"gross_total": "money"}, values={"gross_total": "12700"},
                                 picks={"gross_total": pick}, candidates=cands, confidence={"gross_total": 0.9})
    g = out["gross_total"]
    assert g["status"] == "located" and g["method"] == "pick" and g["confidence"] == 0.9
    assert [(a["value"], a["p"], a["quote"]) for a in g["alternatives"]] == [("10000", 0.08, "10 000")]
    none = grounding.ground_picks(layer, fields={"due_date": "date"}, values={}, picks={}, candidates={}, confidence={})
    assert none["due_date"]["status"] == "no_value"
    assert grounding.ground_picks(None, fields={"x": "text"}, values={}, picks={}, candidates={},
                                  confidence={})["x"]["status"] == "no_layer"


def test_manual_selection_is_validated():
    layer = layer_of([[("Szamlaszam:", 20), ("MINTA-1/A", 110)]])
    r = grounding.manual(layer, [1])
    assert r["method"] == "manual" and r["quote"] == "MINTA-1/A"
    with pytest.raises(ValueError):
        grounding.manual(layer, [99])
    with pytest.raises(ValueError):
        grounding.manual(None, [0])


def test_flow_run_saves_provenance(tmp_path: Path):
    from jav import work
    from jav.adapters import jev as jev_mod
    from jav.runtime import worker
    from tests.test_runtime_worker import FakeClient

    folder = tmp_path / "be"
    folder.mkdir()
    write_text_pdf(folder / "a.pdf", INVOICE_LINES)
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        wp = work.create_from_folder(folder, name="x")
        work.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "S"}, expected_revision=0, actor="t")
        r = work.readiness(wp["id"])
        work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")
        worker.run_worker(once=True)
        with store.connect() as c:
            row = c.execute("SELECT datapoints, provenance FROM datapoints").fetchone()
    prov = json.loads(row["provenance"])
    dps = json.loads(row["datapoints"])
    located = {f: p for f, p in prov.items() if p["status"] == "located"}
    assert located, prov
    for f, p in located.items():  # the box text carries the extracted value
        assert p["method"] in ("pick", "search") and 0 <= p["bbox"][0] < p["bbox"][2] <= 1 and p["quote"]
        assert dps.get(f) is not None


def test_two_column_name_on_two_lines_is_found():
    """Supplier and buyer names side by side, each wrapped onto two lines (a real invoice layout)."""
    layer = layer_of([
        [("MINTAKER", 30), ("KERESKEDELMI", 90), ("ES", 170), ("BESTIXCOM", 330), ("INFORMATIKAI", 400)],
        [("SZOLGALTATO", 30), ("BETETI", 102), ("TARSASAG", 144), ("TANACSADO", 330), ("KFT.", 390)],
    ])
    r = grounding.locate_value(layer, "name", "MINTAKER KERESKEDELMI ES SZOLGALTATO BETETI TARSASAG", field="supplier_name")
    assert r["status"] == "located" and r["quote"] == "MINTAKER KERESKEDELMI ES SZOLGALTATO BETETI TARSASAG"
    b = grounding.locate_value(layer, "name", "BESTIXCOM INFORMATIKAI TANACSADO KFT.", field="buyer_name")
    assert b["status"] == "located" and len(b["boxes"]) == 2


def test_picked_raw_wrapped_to_the_next_line_is_located():
    """A printed text span wrapped across lines (NAV template IBAN): the first part on the picked line, the rest below
    it in the same column, possibly after a label."""
    layer = layer_of([
        [("Szamlaszam:", 20), ("12100028-46813574-00000000", 110)],
        [("HU82", 110), ("1210", 140), ("0028", 170), ("4681", 200), ("3574", 230), ("0000", 260)],
        [("IBAN:", 20), ("0000", 110)],
    ])
    words = grounding.locate_raw(layer, 2, "HU82 1210 0028 4681 3574 0000 0000")
    assert [w.text for w in words] == ["HU82", "1210", "0028", "4681", "3574", "0000", "0000"]
    assert [w.line_no for w in words][-1] == 3 and len(grounding.region(words)["boxes"]) == 2
    far = layer_of([[("HU82", 110), ("1210", 140)], [("0028", 400)]])  # continuation in another column: not the same
    assert grounding.locate_raw(far, 1, "HU82 1210 0028") is None


def test_unlocatable_pick_gets_an_approximate_frame_on_its_line():
    """If the picked candidate cannot be found either verbatim or by search, the line picked by the model gets an
    approximate box: so the field to be reviewed is still not left without a location."""
    layer = layer_of([[("Fizetendo:", 20), ("12", 110), ("7OO", 128)], [("Netto:", 20), ("10", 110), ("000", 128)]])
    pick = SimpleNamespace(label="12700", raw="12 700", line_no=1, probabilities={"12700": 0.55}, present_p=0.9)
    out = grounding.ground_picks(layer, fields={"gross_total": "money"}, values={"gross_total": "12700"},
                                 picks={"gross_total": pick}, candidates={}, confidence={"gross_total": 0.55})
    g = out["gross_total"]
    assert g["status"] == "approximate" and g["method"] == "pick_line" and g["confidence"] == 0.55
    assert g["quote"] == "Fizetendo: 12 7OO" and g["page"] == 1 and len(g["boxes"]) == 1
