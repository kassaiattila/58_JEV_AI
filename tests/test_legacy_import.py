"""047 T1.4: importing the legacy project's exports for comparison (synthetic CSV; the legacy database is not read)."""

import json
from pathlib import Path

from jav import legacy_import, store

MANIFEST = "﻿document_id,doc_type,source_path,resolved_path,output_file,sha256\n" \
           "11,invoice_hu,/data/inbox/a.pdf,/data/inbox/_processed/a.pdf,documents/a.pdf," + "a" * 64 + "\n" \
           "12,statement_cib,/data/inbox/b.pdf,/data/inbox/_processed/b.pdf,documents/b.pdf," + "b" * 64 + "\n"
SUMMARY = "﻿doc_type,id,run_id,is_valid,needs_review,invoice_number,gross_total,issue_date,line_items.1.description," \
          "line_items.1.net_amount,line_items.2.description,line_items.2.net_amount\n" \
          "invoice_hu,11,deb-1,True,False,MINTA-1,12700,2026-01-05,Tétel A,10000,,\n" \
          "statement_cib,12,deb-2,False,True,,,,,,,\n"


def _batch(tmp: Path) -> Path:
    b = tmp / "intake-batches" / "Minta-köteg__0001"
    b.mkdir(parents=True)
    (b / "manifest.csv").write_text(MANIFEST, encoding="utf-8")
    (b / "osszesitett-adatok.csv").write_text(SUMMARY, encoding="utf-8")
    return tmp


def test_rows_are_joined_by_legacy_id_and_unflattened(tmp_path):
    rows = legacy_import.read_batches(_batch(tmp_path))
    by = {r.doc_id: r for r in rows}
    a = by["a" * 64]
    assert a.doc_type == "invoice_hu" and a.is_valid is True and a.needs_review is False
    assert a.datapoints["invoice_number"] == "MINTA-1" and a.datapoints["gross_total"] == "12700"
    assert a.datapoints["line_items"] == [{"description": "Tétel A", "net_amount": "10000"}]  # empty 2nd item dropped
    assert "invoice_number" not in by["b" * 64].datapoints  # an empty cell is not data


def test_import_is_idempotent_and_marked_legacy(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        assert legacy_import.import_batches(_batch(tmp_path)) == {"rows": 2, "inserted": 2}
        assert legacy_import.import_batches(tmp_path) == {"rows": 2, "inserted": 0}
        with store.connect() as c:
            (producer, dp), = c.execute("SELECT producer, datapoints FROM legacy_results WHERE doc_id = ?", ("a" * 64,)).fetchall()
        assert producer == "legacy:10_AIFLOW_V4" and json.loads(dp)["invoice_number"] == "MINTA-1"


def test_compare_reports_type_and_field_differences_without_calling_it_accuracy(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        legacy_import.import_batches(_batch(tmp_path))
        store.upsert_document(doc_id="a" * 64, source_path="a.pdf", doc_type="invoice_hu", detail_type="invoice_hu", detail_method="anchors")
        store.insert_datapoints(run_id="r1", doc_id="a" * 64, doc_type="invoice_hu", arm="S",
                                datapoints={"invoice_number": "MINTA-1", "gross_total": "12700", "issue_date": "2026-01-06"},
                                field_conf={}, validation=[], route="auto", review_reasons=[], final_status="done", config_hash="x")
        rep = legacy_import.compare()
    assert rep["documents"] == 1 and rep["type_agree"] == 1
    assert rep["fields"]["issue_date"] == {"same": 0, "different": 1, "only_legacy": 0, "only_new": 0}
    assert rep["fields"]["invoice_number"]["same"] == 1
    assert "not accuracy" in rep["note"]
