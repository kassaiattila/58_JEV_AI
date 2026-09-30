"""077 (J6): the third-party PDF parsers run in a separate helper process, with a time and a memory limit.

A broken or hostile PDF must not hang the worker or the local service's page images: a request over its time limit or
memory limit stops the helper, the caller gets a named error, and the next request starts a new helper. Our own
processing (lines, cells) stays in the calling process and gives the same result as before. The parser stand-ins are in
`tests/pdf_reader_probe.py`; every PDF is generated.
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import Image

from jav import cfg, isolated_pdf, ocr, page_image, pdf
from jav.isolated_pdf import PdfReaderError, PdfReaderLimit, Reader, ReaderSettings
from tests import pdf_reader_probe as probe
from tests.pdfgen import INVOICE_LINES, write_text_pdf


def _blank_pdf(path: Path, *, pages: int = 1, size_pt: float = 300.0) -> Path:
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(size_pt, size_pt)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def reader():
    r = Reader(memory_mb=512, startup_timeout_s=60)
    yield r
    r.close()


@pytest.fixture()
def in_process(monkeypatch):
    """The behaviour before 077: the same functions, run in the calling process."""
    base = isolated_pdf.settings()
    monkeypatch.setattr(isolated_pdf, "settings", lambda: ReaderSettings(**{**base.__dict__, "isolated": False}))


# --- the settings -----------------------------------------------------------------------------------------------------


def test_settings_come_from_the_service_config():
    got = isolated_pdf.settings()
    assert got == ReaderSettings(**cfg.load("service")["pdf_reader"])
    assert got.isolated is True
    assert 0 < got.page_image_timeout_s <= got.read_timeout_s and got.render_timeout_s > 0 and got.memory_mb >= 256


def test_limit_errors_are_value_errors():
    """The local service answers a ValueError with 422 and its message (not 500), like an oversized document."""
    assert issubclass(PdfReaderLimit, ValueError) and issubclass(PdfReaderError, ValueError)


# --- the helper process -----------------------------------------------------------------------------------------------


def test_the_helper_runs_in_another_process_and_is_reused(reader):
    first = reader.call(probe.helper_pid, timeout_s=10)
    assert first != __import__("os").getpid()
    assert reader.call(probe.helper_pid, timeout_s=10) == first
    assert reader.call(probe.echo, timeout_s=10, value={"a": [1, 2.5, "€"]}) == {"a": [1, 2.5, "€"]}
    assert reader.starts == 1


def test_a_hanging_request_is_stopped_at_its_time_limit(reader):
    first = reader.call(probe.helper_pid, timeout_s=10)
    t0 = time.perf_counter()
    with pytest.raises(PdfReaderLimit, match="1 s") as exc:
        reader.call(probe.sleep_for, timeout_s=1, seconds=60)
    assert exc.value.reason == "timeout"
    assert time.perf_counter() - t0 < 15
    second = reader.call(probe.helper_pid, timeout_s=10)  # the next request gets a new helper
    assert second != first and reader.starts == 2


def test_a_request_over_the_memory_limit_is_stopped(reader):
    with pytest.raises(PdfReaderLimit) as exc:
        reader.call(probe.allocate, timeout_s=30, mb=1024)
    assert exc.value.reason in {"memory", "stopped"}
    assert reader.call(probe.allocate, timeout_s=30, mb=16) == 16 * 1_048_576  # a new helper, still usable


@pytest.mark.skipif(sys.platform != "win32", reason="the job object is the Windows memory limit")
def test_the_helper_is_in_a_memory_limited_job_on_windows(reader):
    reader.call(probe.helper_pid, timeout_s=10)
    assert reader.memory_limited is True


def test_a_crashing_helper_is_reported_and_replaced(reader):
    with pytest.raises(PdfReaderLimit, match="stopped") as exc:
        reader.call(probe.crash, timeout_s=10)
    assert exc.value.reason == "stopped"
    assert reader.call(probe.echo, timeout_s=10, value=1) == 1 and reader.starts == 2


def test_a_helper_that_died_between_requests_is_replaced(reader):
    reader.call(probe.helper_pid, timeout_s=10)
    reader._proc.kill()  # e.g. stopped from outside while idle
    reader._proc.join(10)
    assert reader.call(probe.echo, timeout_s=10, value=3) == 3 and reader.starts == 2


def test_a_parser_error_comes_back_by_name_and_keeps_the_helper(reader):
    with pytest.raises(PdfReaderError, match="^ValueError: broken xref$"):
        reader.call(probe.fail, timeout_s=10, message="broken xref")
    assert reader.call(probe.echo, timeout_s=10, value=2) == 2 and reader.starts == 1


# --- the four places that parse PDFs ----------------------------------------------------------------------------------


def test_text_layer_is_the_same_as_in_process(tmp_path, monkeypatch):
    path = write_text_pdf(tmp_path / "szamla.pdf", INVOICE_LINES)
    isolated = pdf.read_pdf(path)
    base = isolated_pdf.settings()
    monkeypatch.setattr(isolated_pdf, "settings", lambda: ReaderSettings(**{**base.__dict__, "isolated": False}))
    local = pdf.read_pdf(path)
    assert isolated.has_text_layer and "MINTA-2026-001" in isolated.text
    assert (isolated.text, isolated.lines, isolated.page_count, isolated.page_sizes, isolated.words) == (
        local.text, local.lines, local.page_count, local.page_sizes, local.words)
    assert [ln.model_dump() for ln in isolated.layout] == [ln.model_dump() for ln in local.layout]


def test_a_corrupt_pdf_is_a_named_error(tmp_path):
    bad = tmp_path / "hibas.pdf"
    bad.write_bytes(b"%PDF-1.4\nnot a PDF body at all\n%%EOF")
    with pytest.raises(PdfReaderError, match="^Pdfminer.*Root"):  # the parser's own error type, by name
        pdf.read_pdf(bad)


def test_page_image_and_page_count_come_from_the_helper(tmp_path):
    path = _blank_pdf(tmp_path / "ket_oldal.pdf", pages=2, size_pt=300.0)
    assert page_image.page_count(path) == 2
    img = Image.open(io.BytesIO(page_image.render(path, 2, dpi=144)))
    assert (img.width, img.height) == (600, 600)
    with pytest.raises(page_image.BadPage, match="1..2"):
        page_image.render(path, 3)
    data = path.read_bytes()  # 075: the already verified bytes are rendered, not the file read again
    assert Image.open(io.BytesIO(page_image.render(path, 1, dpi=72, data=data))).size == (300, 300)


def test_ocr_page_images_and_sizes_come_from_the_helper(tmp_path):
    path = _blank_pdf(tmp_path / "szkennelt.pdf", pages=2, size_pt=200.0)
    out = tmp_path / "kepek"
    out.mkdir()
    pngs = ocr.render_pages(path, out, dpi=72)
    assert [p.name for p in pngs] == ["p-1.png", "p-2.png"] and all(p.is_file() for p in pngs)
    assert ocr.page_sizes(path) == [(200.0, 200.0), (200.0, 200.0)]
    assert ocr.page_sizes(tmp_path / "nincs_ilyen.pdf") == []  # unreadable: no word layer, as before


def test_the_in_process_switch_gives_the_same_page_image(tmp_path, in_process):
    path = _blank_pdf(tmp_path / "egy.pdf", size_pt=300.0)
    assert Image.open(io.BytesIO(page_image.render(path, 1, dpi=144))).size == (600, 600)
    assert page_image.page_count(path) == 1


def test_a_render_limit_becomes_an_ocr_to_do(tmp_path, monkeypatch):
    path = _blank_pdf(tmp_path / "lassu.pdf")

    def over_limit(fn, *, kind, **kwargs):
        raise PdfReaderLimit("the PDF reader gave no answer within 1 s", reason="timeout")

    monkeypatch.setattr(isolated_pdf, "run", over_limit)
    with pytest.raises(ocr.PdfRenderLimit) as exc:
        ocr.render_pages(path, tmp_path)
    assert isinstance(exc.value, ocr.OcrUnavailableError)  # the flow gives a to-do ("ocr:unavailable:PdfRenderLimit")
