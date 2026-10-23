"""144 (DECISIONS 144): the bank's own PDF behind a statement read by code, on the pairing page's documents.

A statement read by code is stored as the reader's statement file (`format: jav.domains.finance.statement_table`), which names the PDF
it was read from (`source`) or, for a ledger export, the month's PDF (`source.companion`). The documents' statement pane
showed a broken image for it; now the service finds the PDF again (in the folder of the package that brought the
statement, or under any path the store fingerprinted with that content), frames the line on it and serves its pages
from the verified bytes. Synthetic data only: a made-up account, partner and amounts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jav.app import work
from jav.ai import grounding
from jav.core import store
from jav.domains.finance import reconcile, reconcile_package as rp, statement_original as so
from tests import test_api
from tests import test_reconcile_k2_129 as k2
from tests import test_reconcile_package_131 as e1
from tests.pdfgen import write_text_pdf

env = test_api.env
db = e1.db

PDF_LINES = ["Example Bank statement 2026.04", "2026.04.10 Example Supplier INV-0001 -100,00",
             "2026.04.12 Other Partner REF-7 -25,00"]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _statement(tmp: Path, *, source: dict | None = None, name: str = "stmt") -> tuple[str, list[str], Path]:
    """A statement read by code: the bank's PDF in `tmp/bank`, the reader's statement file as the item of a package whose
    source is that folder, and the stored statement. Returns the document id, the line ids and the PDF."""
    bank = tmp / "bank"
    bank.mkdir(exist_ok=True)
    pdf = write_text_pdf(bank / "statement-2026-04.pdf", PDF_LINES)
    lines = [e1._line(), e1._line(memo="REF-7", amount="25.00", day="2026-04-12", counterparty_name="Other Partner")]
    values = {**k2._statement(*lines), "account_no": k2.OWN}
    body = {"format": so.FORMAT, "version": 1, "institution": "Example Bank", "profile": "example",
            "source": source if source is not None else {"file": pdf.name, "sha256": _sha(pdf.read_bytes()), "repairs": []},
            "statement": values}
    statement_file = tmp / "statement_tables" / f"{name}.json"
    statement_file.parent.mkdir(exist_ok=True)
    statement_file.write_text(json.dumps(body), encoding="utf-8")
    k2._run(k2.RUN, [name])
    doc = k2._save(name, values, run_id=k2.RUN, doc_type=so.DOC_TYPE, validation=k2.VERIFIED)
    with store.connect() as c:
        c.execute("UPDATE workpackages SET source_ref=? WHERE id='wp-1'", (str(bank),))
        c.execute("INSERT INTO workpackage_items(workpackage_id, item_id, kind, source_path, sha256, added_revision)"
                  " VALUES ('wp-1',?,?,?,?,1)", (doc, so.DOC_TYPE, str(statement_file), _sha(statement_file.read_bytes())))
    return doc, e1._ids(doc, *lines), pdf


def test_the_bank_pdf_behind_a_statement_read_by_code_is_found_and_the_line_framed(db, tmp_path):
    doc, (first, second), pdf = _statement(tmp_path)
    wp_id = e1._package()
    found = rp.locate(wp_id, second)
    assert (found["image"], found["pages"], found["page"]) == ("original", 1, 1) and found["box"] is not None
    assert found["original"] == {"file": pdf.name, "state": so.FOUND}
    assert found["statement"]["institution"] == "Example Bank"
    assert [ln["id"] for ln in found["statement"]["lines"]] == [first, second]
    assert found["statement"]["lines"][1]["memo"] == "REF-7"
    assert rp.locate(wp_id, first)["box"][1] < found["box"][1]  # the first line stands above the second
    assert rp.original_page(wp_id, first, 1, dpi=72).startswith(b"\x89PNG")


def test_a_pdf_changed_or_gone_since_the_reading_is_not_shown(db, tmp_path):
    _doc, (first, _second), pdf = _statement(tmp_path)
    wp_id = e1._package()
    assert rp.locate(wp_id, first)["image"] == "original"
    write_text_pdf(pdf, [*PDF_LINES, "an added line"])
    changed = rp.locate(wp_id, first)
    assert (changed["image"], changed["original"]["state"], changed["box"]) == (None, so.MISSING, None)
    assert changed["statement"]["lines"]  # the statement as read still shows
    with pytest.raises(KeyError):
        rp.original_page(wp_id, first, 1, dpi=72)
    pdf.unlink()
    assert rp.locate(wp_id, first)["original"]["state"] == so.MISSING


def test_a_moved_pdf_is_found_by_its_content_where_the_store_saw_it(db, tmp_path):
    _doc, (first, _second), pdf = _statement(tmp_path)
    moved = tmp_path / "elsewhere" / "renamed.pdf"
    moved.parent.mkdir()
    pdf.rename(moved)
    wp_id = e1._package()
    assert rp.locate(wp_id, first)["original"]["state"] == so.MISSING
    work.fingerprint(moved)  # the store fingerprinted it (e.g. a folder survey)
    assert rp.locate(wp_id, first)["image"] == "original"


def test_an_export_without_a_pdf_has_no_original_page(db, tmp_path):
    _doc, (first, _second), _pdf = _statement(tmp_path, source={"file": "export.xlsx", "sha256": "0" * 64, "repairs": []})
    found = rp.locate(e1._package(), first)
    assert (found["image"], found["original"]) == (None, {"file": "export.xlsx", "state": so.EXPORT})
    assert len(found["statement"]["lines"]) == 2


def test_a_ledger_exports_pdf_companion_is_its_original(db, tmp_path):
    bank = tmp_path / "bank"
    bank.mkdir()
    pdf = write_text_pdf(bank / "statement-2026-04.pdf", PDF_LINES)
    source = {"file": "ledger.xml", "sha256": "1" * 64, "repairs": [],
              "companion": {"file": pdf.name, "sha256": _sha(pdf.read_bytes())}}
    _doc, (first, _second), _pdf = _statement(tmp_path, source=source)
    found = rp.locate(e1._package(), first)
    assert (found["image"], found["original"]["file"]) == ("original", pdf.name) and found["box"] is not None


def test_the_places_of_a_statements_lines_are_found_once(db, tmp_path, monkeypatch):
    _doc, (first, second), _pdf = _statement(tmp_path)
    wp_id = e1._package()
    calls = []
    real = grounding.locate_rows
    monkeypatch.setattr(grounding, "locate_rows", lambda *a, **k: calls.append(1) or real(*a, **k))
    rp.locate(wp_id, first)
    rp.locate(wp_id, second)
    assert len(calls) == 1


def test_a_pdf_statement_keeps_its_own_page(db):
    k2._run(k2.RUN, ["stmt"])
    stmt = e1._stmt("stmt", e1._line(), run_id=k2.RUN)
    [lid] = e1._ids(stmt, e1._line())
    found = rp.locate(e1._package(), lid)
    assert (found["image"], found["original"], found["open"]["item_id"]) == ("item", None, stmt)
    assert found["statement"]["lines"][0]["id"] == lid
    with pytest.raises(KeyError):
        rp.original_page(e1._package(name="May"), lid, 1, dpi=72)


def test_the_service_serves_the_original_page_of_a_line_in_the_scope(env):
    c = env["client"]
    _doc, (first, _second), _pdf = _statement(env["tmp"])
    wp_id = e1._package()
    r = c.get(f"/api/workpackages/{wp_id}/reconcile/original/pages/1.png", params={"line_id": first, "dpi": 72})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png" and r.content.startswith(b"\x89PNG")
    assert c.get(f"/api/workpackages/{wp_id}/reconcile/original/pages/9.png", params={"line_id": first}).status_code == 422
    assert c.get(f"/api/workpackages/{wp_id}/reconcile/original/pages/1.png", params={"line_id": "nope"}).status_code == 422
    other = e1._stmt("other", e1._line(), account=e1.OTHER)
    out = c.get(f"/api/workpackages/{wp_id}/reconcile/original/pages/1.png", params={"line_id": e1._ids(other, e1._line())[0]})
    assert out.status_code == 422  # not in the package's scope
    assert reconcile.ENGINE_VERSION
