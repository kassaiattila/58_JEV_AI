"""121 (F-aláírt-pdf-általános): a digitally signed PDF is read; any other form or active content stays excluded.

The native reader excluded every PDF with an interactive form, and a digital signature is a form field: 79 of the
532 PDFs of two of the owner's yearly invoice folders are signed. A signed PDF without a fitting type pack therefore
got no general facts. A form whose fields are all signatures fills nothing in and runs nothing; it is now read. An
empty form, any other field kind, an XFA form, and an action anywhere (an automatic one, JavaScript, a field action)
still exclude the file. All PDFs are synthetic.
"""
from __future__ import annotations

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
])
def test_any_other_form_or_action_stays_excluded(tmp_path, entry):
    result = _read(tmp_path, entry)
    assert result.status == "excluded" and not result.elements
