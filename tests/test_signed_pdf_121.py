"""121 (F-aláírt-pdf-általános): a digitally signed PDF is read; any other form or active content stays excluded.

The native reader excluded every PDF with an interactive form, and a digital signature is a form field: 79 of the
532 PDFs of two of the owner's yearly invoice folders are signed. A signed PDF without a fitting type pack therefore
got no general facts. A form whose fields are all signatures fills nothing in and runs nothing; it is now read. An
empty form, any other field kind, an XFA form, and an action anywhere (an automatic one, JavaScript, a field action)
still exclude the file. All PDFs are synthetic.

The owner's second decision (2026-10-07) on the other signed PDFs of those folders: an opening view setting (a page
and a zoom, no action) is no action; a PDF with embedded files is read for its visible content, the embedded files
stay unopened and the reading is partial; and the presence of page annotations is checked without resolving their
object graph, whose cycles (a signature widget and its page) made the reader reject 19 valid signed PDFs as corrupt.
"""
from __future__ import annotations

import re

import pytest

from jav.readers import pipeline
from test_reader_visual_108 import pdf_with_catalog_entry

SIGNATURE = (b"<< /FT /Sig /T (Signature1) /V << /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached"
             b" /ByteRange [0 10 20 10] /Contents <00> >> >>")


def _read(tmp_path, entry: bytes):
    return pipeline.read_files([pdf_with_catalog_entry(tmp_path, entry)]).bundle.results[0]


def test_a_signature_only_form_is_read(tmp_path):
    result = _read(tmp_path, b"/AcroForm << /Fields [" + SIGNATURE + b"] /SigFlags 3 >>")
    assert result.status != "excluded"
    assert any("Synthetic PDF content" in (e.text or "") for e in result.elements)


def test_an_escaped_signature_field_kind_is_still_a_signature(tmp_path):
    result = _read(tmp_path, b"/Acro#46orm << /Fields [<< /F#54 /S#69g /T (S) >>] >>")
    assert result.status != "excluded"


@pytest.mark.parametrize("entry", [
    b"/AcroForm << /Fields [] >>",  # an empty form: not a signature, the earlier rule stands
    b"/AcroForm << /Fields [" + SIGNATURE + b" << /FT /Tx /T (name) >>] >>",  # a text field next to the signature
    b"/AcroForm << /Fields [" + SIGNATURE + b"] /XFA (synthetic) >>",
    b"/AcroForm << /Fields [<< /FT /Sig /T (S) /AA << /K << /S /JavaScript /JS (synthetic) >> >> >>] >>",
    b"/AcroForm << /Fields [" + SIGNATURE + b"] >> /OpenAction << /S /JavaScript /JS (synthetic) >>",
    b"/AcroForm << /Fields [<< /T (no kind) >>] >>",
    b"/OpenAction << /S /GoTo /D [3 0 R /Fit] >>",  # an action dictionary, even a harmless one, is still an action
    b"/OpenAction << /S /Launch /F (synthetic.exe) >>",
    b"/Names << /JavaScript << /Names [] >> >>",
])
def test_any_other_form_or_action_stays_excluded(tmp_path, entry):
    result = _read(tmp_path, entry)
    assert result.status == "excluded" and not result.elements


def test_an_opening_view_setting_is_no_action(tmp_path):
    result = _read(tmp_path, b"/OpenAction [3 0 R /Fit]")
    assert result.status != "excluded"
    assert any("Synthetic PDF content" in (e.text or "") for e in result.elements)


def test_embedded_files_stay_unopened_and_the_reading_is_partial(tmp_path):
    result = _read(tmp_path, b"/Names << /EmbeddedFiles << /Names [(invoice.xml) << /Type /Filespec /F (invoice.xml)"
                             b" /EF << /F 3 0 R >> >>] >> >>")
    assert result.status == "partial"
    assert any("Synthetic PDF content" in (e.text or "") for e in result.elements)
    assert any(i.code == "unread_content" and "embedded" in i.message.lower() for i in result.issues)


def test_a_signature_annotation_cycle_is_a_visible_gap_not_a_corrupt_file(tmp_path):
    from test_reader_visual_108 import write_text_pdf
    import re

    path = write_text_pdf(tmp_path / "cycle.pdf", ["Synthetic PDF content"])
    bodies = re.findall(rb"[0-9]+ 0 obj\n(.*?)\nendobj", path.read_bytes(), re.DOTALL)
    page_no = next(i for i, b in enumerate(bodies, 1) if b"/Type /Page " in b or b"/Type /Page>>" in b or b"/Type /Page\n" in b)
    widget_no = len(bodies) + 1
    # a signature widget pointing back at its page and at itself as its own field parent: a cycle
    bodies[page_no - 1] = bodies[page_no - 1].replace(b"/Type /Page", f"/Annots [{widget_no} 0 R] /Type /Page".encode(), 1)
    bodies.append(f"<< /Type /Annot /Subtype /Widget /FT /Sig /Rect [0 0 0 0] /P {page_no} 0 R /Parent {widget_no} 0 R"
                  f" /Kids [{widget_no} 0 R] >>".encode())
    bodies[0] = bodies[0].replace(b"/Pages 2 0 R", f"/Pages 2 0 R /AcroForm << /Fields [{widget_no} 0 R] >>".encode())
    output, offsets = bytearray(b"%PDF-1.4\n"), []
    for index, body in enumerate(bodies, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(bodies) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(output)
    result = pipeline.read_files([path]).bundle.results[0]
    assert result.status == "partial"
    assert any(i.code == "unread_content" and "annotations" in i.message for i in result.issues)


def test_an_object_listed_but_absent_is_skipped_not_a_corrupt_file(tmp_path):
    # an incrementally saved (signed) PDF may list an object number in its cross-reference table that is not there
    path = pdf_with_catalog_entry(tmp_path, b"")
    data = path.read_bytes()
    size = int(re.search(rb"/Size (\d+)", data).group(1))
    xref_at = int(re.search(rb"startxref\n(\d+)", data).group(1))
    table = data[xref_at:data.index(b"trailer", xref_at)]
    table = table.replace(f"0 {size}\n".encode(), f"0 {size + 1}\n".encode(), 1) + f"{xref_at - 1:010d} 00000 n \n".encode()
    data = data[:xref_at] + table + data[data.index(b"trailer", xref_at):].replace(f"/Size {size}".encode(), f"/Size {size + 1}".encode())
    path.write_bytes(data)
    result = pipeline.read_files([path]).bundle.results[0]
    assert result.status != "corrupt"
    assert any("Synthetic PDF content" in (e.text or "") for e in result.elements)
