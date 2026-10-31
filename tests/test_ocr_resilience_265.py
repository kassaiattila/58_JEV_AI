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
