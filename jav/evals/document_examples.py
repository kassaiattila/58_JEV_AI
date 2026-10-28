"""The documents process's invented example documents (231, stage U, U1e; the owner's decision of 2026-10-28).

Plain-language summary: a person trying the documents process needs documents that are surely invented. The golden
sets already hold some: the invented invoices, credit notes and receipts the type recognition and the data points are
measured on (`configs/golden_synthetic.json`), and the invented customers' quote requests whose form is a printed PDF
(`configs/golden_quotes.json`). This module puts them into packets (`configs/examples_documents.json`, made by
`python -m jav.cli examples --set documents --write`): each document's printed page as the measurement prints it.

- `example_packets(titles)`: the packets ({id, title, documents: [{file, pages}]}), the titles from `titles` where the file
  has them, else the module's.

Layer: evaluation (it reads the golden sets); the packets are data the shared examples library offers.
"""

from __future__ import annotations

from typing import Any

from jav.core import cfg

__all__ = ["PACKETS", "example_packets"]

# (packet id, its English title, the invented invoices of golden_synthetic.json, the quote requests of golden_quotes.json)
PACKETS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("invoices", "Invented invoices in forints and euros, with a credit note",
     ("synthetic_out_hu_huf", "synthetic_out_hu_eur", "synthetic_out_hu_credit_note", "synthetic_credit_note_hu",
      "synthetic_out_hu_aam_person"), ()),
    ("foreign", "Invented foreign invoices and receipts",
     ("synthetic_out_en_usd", "synthetic_out_en_chf", "synthetic_out_en_eur_reverse_charge", "synthetic_credit_note_en",
      "synthetic_receipt_transaction_id", "synthetic_receipt_receipt_number", "synthetic_out_en_distractors"), ()),
    ("quote_requests", "Invented quote requests on a printed form (an IT quote starts from one once it is read)",
     (), ("q04_hu_network_pdf", "q08_hu_words_pdf")),
)


def _invoices() -> dict[str, list[str]]:
    return {c["id"]: list(c["rows"]) for c in cfg.load("golden_synthetic")["cases"]}


def _requests() -> dict[str, tuple[str, list[str]]]:
    """Each quote request's printed PDF form: its file name and rows."""
    out = {}
    for case in cfg.load("golden_quotes")["cases"]:
        pdf = next((a for a in case["message"].get("attachments", []) if a.get("format") == "pdf"), None)
        if pdf is not None:
            out[case["id"]] = (pdf["filename"], list(pdf["rows"]))
    return out


def example_packets(titles: dict[str, str]) -> list[dict[str, Any]]:
    """The packets: each invented invoice as its one printed page, each quote request's printed form."""
    invoices, requests = _invoices(), _requests()
    packets = []
    for packet_id, title, invoice_ids, request_ids in PACKETS:
        documents = [{"file": f"{i}.pdf", "pages": [invoices[i]]} for i in invoice_ids]
        documents += [{"file": requests[r][0], "pages": [requests[r][1]]} for r in request_ids]
        packets.append({"id": packet_id, "title": titles.get(packet_id, title), "documents": documents})
    return packets
