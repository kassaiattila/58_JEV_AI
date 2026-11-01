"""265 (code review AI-02, AI-04): a failed OCR engine is a named unavailability, and the OCR cache is written whole.

- AI-02: a hung or failed tesseract was a general error, retried twice, and never became the `ocr:unavailable` to-do;
  now it is `OcrEngineFailed`, an `OcrUnavailableError`.
- AI-04: the OCR cache was written in place and read without tolerance, so a truncated file failed every later item
  of the same document; now it is written to a temporary file and replaced in one step, and a broken one reads as
  missing (`jav.core.jsonfile`, shared with the JEV cache).
Synthetic files; no OCR engine runs.
"""

from __future__ import annotations

import subprocess

import pytest

from jav.core import jsonfile
from jav.documents import ocr


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("tesseract", 1), subprocess.CalledProcessError(1, "tesseract"),
                                     OSError("no such file")])
def test_a_failed_engine_is_an_unavailability(tmp_path, monkeypatch, failure) -> None:
    monkeypatch.setattr(ocr, "native_exe", lambda: "tesseract")
    monkeypatch.setattr(ocr, "tessdata_dir", lambda: tmp_path)

    def run(*a, **k):
        raise failure

    monkeypatch.setattr(ocr.subprocess, "run", run)
    with pytest.raises(ocr.OcrUnavailableError) as err:
        ocr._run_tesseract(tmp_path / "p1.png", tmp_path / "p1")
    assert isinstance(err.value, ocr.OcrEngineFailed)


def test_a_cache_file_is_written_whole_and_a_broken_one_reads_as_missing(tmp_path) -> None:
    target = tmp_path / "cache" / "key.json"
    jsonfile.write_atomic(target, {"words": [1, 2]})
    assert jsonfile.read_tolerant(target) == {"words": [1, 2]}
    assert list(target.parent.glob("*.tmp")) == []
    target.write_text('{"words": [1, 2', encoding="utf-8")  # a write cut short
    assert jsonfile.read_tolerant(target) is None
    assert jsonfile.read_tolerant(tmp_path / "missing.json") is None


TSV = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
       "5\t1\t1\t1\t1\t1\t100\t100\t200\t40\t95\tPayable\n")


def test_the_recognition_reads_a_broken_cache_file_as_missing_and_writes_it_whole(tmp_path, monkeypatch) -> None:
    """272 (K5): the shared helper was tested alone; here through the recognition itself (a stand-in engine)."""
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 invented")
    page = tmp_path / "p1.png"
    page.write_bytes(b"png")
    runs: list[int] = []
    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(ocr, "engine", lambda want=None: "native")
    monkeypatch.setattr(ocr, "engine_version", lambda eng: "invented 1.0")
    monkeypatch.setattr(ocr, "render_pages", lambda path, out, max_pages=None: [page])
    monkeypatch.setattr(ocr, "_run_tesseract", lambda png, base, psm=None, eng=None: runs.append(1) or TSV)
    first = ocr.ocr_pdf(source, page_count=1)
    [cached] = list((tmp_path / "cache").glob("*.json"))
    assert first.lines and runs == [1] and list(cached.parent.glob("*.tmp")) == []
    cached.write_text('{"words": [', encoding="utf-8")  # a write cut short
    again = ocr.ocr_pdf(source, page_count=1)
    assert again.lines == first.lines and runs == [1, 1]  # recognised again, not failed
    assert jsonfile.read_tolerant(cached)["page_count"] == 1  # and written whole
