"""231 (stage D0, D0-c; the reassessment of 2026-10-26, F05, P03): the reply letter answers any approved offer, through
its output's builder.

Until D0-c the letter filled its frame with the IT quote's own document data and attached the quote's own file. Now it
reads the approved version as an offer (`OfferContent`: a header, lines, totals, a language, the request it answers),
fills the frame's values with the builder of the output the letter step names, and attaches that output's stored
document; a version that is no offer is refused with the fields it lacks. Synthetic content and a stand-in builder; no
paid call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jav.app import package_release, process_runtime, work
from jav.app.outputs import contract, parts
from jav.core import store
from jav.domains.quotes import quote_letter

OFFER = {"header": {"customer_name": "Invented Insured Ltd", "contact_name": "Teszt Elek", "contact_email": "elek@example.com"},
         "lines": [{"name": "Property cover"}], "totals": {"net": "100000", "vat": "0", "gross": "100000"},
         "currency": "HUF", "language": "en", "request": {"title": "Cover for the workshop"}}


@pytest.fixture()
def builder(monkeypatch):
    def data(content, *, package, version, approved_by, approved_at, output):
        values = {"contact_name": content["header"]["contact_name"], "gross_total": "123456", "currency": "HUF",
                  "package": package, "version": version}
        return contract.OutputData(output, tuple(contract.Value(k, k, v) for k, v in values.items()), ())

    monkeypatch.setattr(parts, "_VERSIONS", {"quote": parts.VersionDocument("quote", "tests.synthetic", data)})


def test_the_frame_is_filled_by_the_builder_of_the_letter_s_output(builder) -> None:
    body = quote_letter.compose(OFFER, package="Invented offer", n=2, paragraph="Thank you for your request.")
    assert body.startswith("Dear Teszt Elek") and "Thank you for your request." in body
    assert "123" in body and "456" in body  # the stand-in builder's gross total, written by code


def test_a_version_that_is_no_offer_is_refused_with_what_it_lacks(tmp_path: Path) -> None:
    with store.use_store(tmp_path / "letter.sqlite"):
        wp = work.create_workpackage(name="Invented", source_kind=process_runtime.CONTAINER, source_ref="pack:x@1",
                                     owner="anna")["id"]
        with store.connect() as c:
            store.begin_immediate(c)
            package_release.record_own(c, wp, content={"statement": []}, fingerprint="f" * 16, locks=[], actor="anna")
        with pytest.raises(quote_letter.LetterError, match="no offer a letter answers: header, lines, totals"):
            quote_letter.request(wp, actor="anna")
        assert quote_letter.view(wp)["version"] is None  # nothing to answer on the page either


def test_an_offer_fits_whatever_else_it_holds() -> None:
    assert quote_letter.OfferContent.model_validate({**OFFER, "premium_table": "T-2026"}).header["customer_name"] == \
        "Invented Insured Ltd"
