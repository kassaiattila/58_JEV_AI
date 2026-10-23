"""The invented IT quote requests (189, plan F-IT-quote-request A1).

Plain-language summary: the golden set of the coming quote request logic pack is invented (`configs/golden_quotes.json`).
These tests check that it is what the owner chose on 2026-10-21 (10-15 emails, mostly Hungarian with 2-3 in English,
the request sometimes in the body and sometimes in 3-4 attached PDF or Excel forms, a few emails that only look like
requests), that every expected number follows from the price list, recomputed here independently, and that its
emails can be laid out and read back like downloaded mail. No AI call, no store.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pdfplumber
import pytest
from openpyxl import load_workbook

from jav import quote_golden
from jav.domains.email.emails import load_message_dir
from jav.domains.email.intents import INTENT_KEYS


@pytest.fixture(scope="module")
def golden() -> quote_golden.QuoteGolden:
    return quote_golden.load()


def _requests(golden):
    return [c for c in golden.cases if c.expected.intent == quote_golden.QUOTE_REQUEST]


def test_the_set_is_what_the_owner_chose(golden) -> None:
    cases, requests = golden.cases, _requests(golden)
    assert 10 <= len(cases) <= 15
    assert 2 <= sum(c.language == "en" for c in cases) <= 3
    assert len(cases) - len(requests) >= 2  # emails that only look like requests
    attachments = [a for c in requests for a in c.message.attachments]
    assert 3 <= len(attachments) <= 4 and {a.format for a in attachments} == {"pdf", "xlsx"}
    assert sum(not c.message.attachments for c in requests) >= 3  # the request in the body
    categories = {golden.price_list.item(line.sku).category for c in requests for line in c.expected.quote.lines}
    assert categories == {"hardware", "licence", "service"}


def test_the_intents_are_registered_or_the_new_quote_request(golden) -> None:
    assert {c.expected.intent for c in golden.cases} <= set(INTENT_KEYS) | {quote_golden.QUOTE_REQUEST}


def _won(x: Decimal) -> Decimal:
    return x.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def test_every_quote_follows_from_the_price_list(golden) -> None:
    prices = golden.price_list
    for case in _requests(golden):
        exp = case.expected
        priced = [m for m in exp.matches if m.sku]
        assert [line.item for line in exp.quote.lines] == [m.item for m in priced], case.id
        for line, match in zip(exp.quote.lines, priced):
            item = prices.item(match.sku)
            requested = exp.request.items[match.item]
            percent = max((d.percent for d in prices.discounts
                           if d.category == item.category and requested.quantity >= d.min_quantity), default=Decimal(0))
            assert (line.sku, line.quantity, line.unit) == (item.sku, requested.quantity, item.unit), case.id
            assert (line.unit_price, line.discount_percent) == (item.unit_price, percent), case.id
            assert line.net == _won(item.unit_price * requested.quantity * (100 - percent) / 100), case.id
        net = sum((line.net for line in exp.quote.lines), Decimal(0))
        assert exp.quote.net_total == net, case.id
        assert exp.quote.vat_total == _won(net * prices.vat_percent / 100), case.id
        assert exp.quote.gross_total == net + exp.quote.vat_total, case.id


def test_an_unpriced_item_is_a_blocker_and_an_ambiguous_one_names_its_candidates(golden) -> None:
    blockers = [(c.id, m) for c in _requests(golden) for m in c.expected.matches if m.blocker]
    assert {m.blocker for _, m in blockers} == {"not_in_price_list", "ambiguous"}
    for case_id, m in blockers:
        assert m.sku is None, case_id
        assert (len(m.candidates) >= 2) == (m.blocker == "ambiguous"), case_id


def test_a_deadline_is_not_before_the_email(golden) -> None:
    dated = [c for c in _requests(golden) if c.expected.request.deadline]
    assert len(dated) >= 5
    for case in dated:
        assert case.expected.request.deadline >= date.fromisoformat(case.message.received_at[:10]), case.id


def test_the_emails_are_read_back_like_downloaded_mail(golden, tmp_path) -> None:
    folders = quote_golden.lay_out_all(tmp_path, golden)
    assert [f.name for f in folders] == [c.id for c in golden.cases]
    for case, folder in zip(golden.cases, folders):
        msg = load_message_dir(folder)
        assert (msg.subject, msg.body, msg.sender, msg.mailbox) == \
               (case.message.subject, case.message.body, case.message.sender, golden.seller.email)
        assert [a.filename for a in msg.attachments] == [a.filename for a in case.message.attachments]
        assert all(a.path for a in msg.attachments), case.id  # inside the email's own folder


def test_a_pdf_form_has_its_rows_as_text_and_an_excel_form_its_table(golden, tmp_path) -> None:
    for case in golden.cases:
        for attachment in case.message.attachments:
            path = quote_golden.lay_out(case, tmp_path, mailbox=golden.seller.email) / attachment.filename
            if attachment.format == "pdf":
                with pdfplumber.open(path) as pdf:
                    text = pdf.pages[0].extract_text()
                for row in attachment.rows:
                    for cell in filter(None, (c.strip() for c in row.split("   "))):
                        assert cell in text, (case.id, cell)
            else:
                sheet = load_workbook(path, read_only=True)[attachment.sheet]
                read = [tuple(cell for cell in row) for row in sheet.iter_rows(values_only=True)]
                assert read == [tuple(None if v == "" else v for v in row) for row in attachment.table], case.id


def test_the_price_list_is_written_as_an_excel_sheet(golden, tmp_path) -> None:
    path = quote_golden.write_price_list(tmp_path / "arlista.xlsx", golden)
    rows = list(load_workbook(path, read_only=True).active.iter_rows(values_only=True))
    columns = golden.price_list.columns
    assert rows[0] == tuple(columns[k] for k in ("sku", "name", "unit", "unit_price", "category"))
    assert [(r[0], r[3]) for r in rows[1:]] == [(i.sku, int(i.unit_price)) for i in golden.price_list.items]


def test_a_broken_set_is_refused(golden) -> None:
    data = golden.model_dump(mode="json")
    case = next(c for c in data["cases"] if c["expected"]["intent"] == quote_golden.QUOTE_REQUEST)
    case["expected"]["matches"][0]["sku"] = "NO-SUCH-ITEM"
    with pytest.raises(ValueError, match="not in the price list"):
        quote_golden.QuoteGolden.model_validate(data)
