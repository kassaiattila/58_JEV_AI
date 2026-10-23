"""153 (review C4): a full card number is not saved with a document's extracted data, nor written to a download.

The decision of 144 (keep only a card number's first six and last four digits) covered the statements read by code and
the reconciliation's views; a card statement processed as a document (the AI extraction) saved and exported the full
numbers. Extracted data is now masked when it is saved, and the downloads mask any full number still in older data.
The text sent to the AI services is not masked here (that would change the requests: a decision of its own). Synthetic
values: the published Visa test number, built at run time.
"""

from jav.app import export
from jav.core import card_numbers

CARD = " ".join(["4111"] + ["1111"] * 3)  # the schemes' published test number


def test_extracted_values_are_masked_however_deep():
    data = {"transactions": [{"memo": f"card {CARD} shop", "amount": "10.00"}], "account_no": "11112223-33334444",
            "note": None, "total": 12}
    assert card_numbers.mask_values(data) == {
        "transactions": [{"memo": "card 411111xxxxxx1111 shop", "amount": "10.00"}], "account_no": "11112223-33334444",
        "note": None, "total": 12}


def test_a_download_masks_a_full_number_in_older_data():
    record = {"item_id": "a", "file": "statement.pdf", "doc_type": "statement_cib", "fields": {"memo": f"card {CARD}"},
              "provenance": {"memo": {"page": 1, "quote": f"card {CARD}"}}, "corrected": [], "open_reasons": [], "lists": {},
              "row_pages": {}, "pages": {}, "kinds": {}, "arm": "G", "final_status": "done", "source_email": None, "duplicate": None}
    _head, rows = export.datapoints_table([record])
    assert all("4111 1111" not in str(cell) for row in rows for cell in row)
    assert any("411111xxxxxx1111" in str(cell) for row in rows for cell in row)
