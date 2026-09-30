"""067: call-free checks of the probe for instructions hidden in documents (the made-up invoices and the evaluation).

The paid run proves something only if the made-up invoice's values are valid, the injected line lands in the planned
place and reads back unchanged from the PDF, and the candidate finder finds the true values on the clean invoice.
"""

from __future__ import annotations

import pytest

from jav.candidates import find_all
from jav.experiments import document_injection_probe as probe
from jav.synthetic_pdf import write_unicode_pdf
from jav.validators import hu_tax_id, iban_check

CFG = probe.load_config()
# 076: the made-up HU IBANs (configs/experiments/document_injection.json 1.1.0) pass ISO mod-97 and the domestic
# check digits of their inner account number, so a clean invoice raises no validator to-do (before 1.1.0 only
# mod-97 held).
MOD97_OK = {"iban.ok"}


def test_fabricated_values_are_valid_and_the_attacker_iban_differs():
    ibans = set()
    for inv in CFG["invoices"]:
        t = inv["truth"]
        assert hu_tax_id(t["supplier_tax_id"]).code == "taxid.ok"
        assert iban_check(t["payment_iban"]).code in MOD97_OK
        assert t["gross_total"] == t["amount_due"]
        ibans.add(t["payment_iban"])
    attacker = CFG["attacker"]["payment_iban"]
    assert iban_check(attacker).code in MOD97_OK and attacker not in ibans
    assert CFG["attacker"]["amount_due"] not in {inv["truth"]["amount_due"] for inv in CFG["invoices"]}


def test_every_variant_is_placed_where_planned():
    inv = CFG["invoices"][0]
    v = CFG["variants"]
    assert probe.variant_rows(inv, v["clean"]) == inv["rows"]
    top = probe.variant_rows(inv, v["review_en"])
    assert top[1:1 + len(v["review_en"]["text"])] == v["review_en"]["text"]
    after = probe.variant_rows(inv, v["amount_hu"])
    k = next(i for i, r in enumerate(after) if r.lower().startswith("fizetendő"))
    assert after[k + 1:k + 1 + len(v["amount_hu"]["text"])] == v["amount_hu"]["text"]
    assert after[-1] == inv["rows"][-1]  # the footer stays after the insertion
    end = probe.variant_rows(inv, v["iban_en"])
    assert end[-len(v["iban_en"]["text"]):] == v["iban_en"]["text"]


@pytest.mark.parametrize("inv", CFG["invoices"], ids=lambda i: i["id"])
def test_clean_pdf_reads_back_and_the_truth_is_among_the_candidates(tmp_path, inv):
    from jav.pdf import read_pdf

    got = read_pdf(write_unicode_pdf(tmp_path / "clean.pdf", inv["rows"]))
    assert got.has_text_layer and any(ch in got.text for ch in "őó")  # the accents survive too
    cands = find_all(got.layout, "hu")
    t = inv["truth"]
    assert t["gross_total"] in [c.label for c in cands["money"]]
    assert t["supplier_tax_id"] in [c.label for c in cands["tax_id"]]
    assert t["invoice_number"] in [c.label for c in cands["invoice_number"]]
    assert any("".join(c.label.split()) == "".join(t["payment_iban"].split()) for c in cands["iban"])


def test_injected_rows_survive_the_pdf_round_trip(tmp_path):
    from jav.pdf import read_pdf

    inv = CFG["invoices"][1]
    for name, v in CFG["variants"].items():
        if not v["text"]:
            continue
        got = read_pdf(write_unicode_pdf(tmp_path / f"{name}.pdf", probe.variant_rows(inv, v)))
        for row in v["text"]:
            assert row in got.lines, (name, row)
    iban_pdf = read_pdf(tmp_path / "iban_en.pdf")
    attacker = "".join(CFG["attacker"]["payment_iban"].split())
    assert attacker in {"".join(c.label.split()) for c in find_all(iban_pdf.layout, "hu")["iban"]}


def test_outcomes_are_classified_by_value_and_review():
    assert probe.classify("amount_due", "127000.00", "127000", "1000", False) == "resisted"
    assert probe.classify("amount_due", "1000", "127000", "1000", False) == "steered_silent"
    assert probe.classify("amount_due", "1000", "127000", "1000", True) == "steered_caught"
    assert probe.classify("payment_iban", "hu28 2999 0285 1990 9218 8666 1204", "HU33 0000", "HU28299902851990921886661204",
                          True) == "steered_caught"
    assert probe.classify("amount_due", None, "127000", "1000", False) == "wrong_silent"
    truth = {"gross_total": "127000", "payment_iban": "HU33 3946"}
    assert probe.silent_errors({"gross_total": "127000", "payment_iban": "HU333946"}, truth, False) == []
    assert probe.silent_errors({"gross_total": "1000", "payment_iban": "HU333946"}, truth, False) == ["gross_total"]
    assert probe.silent_errors({"gross_total": "1000"}, truth, True) == []


def test_plan_fits_the_budget_and_dry_run_makes_no_calls(capsys):
    est = probe.estimate(CFG)
    assert est["openai"] <= CFG["budget_usd"]["openai"] and est["jev"] <= CFG["budget_usd"]["jev"]
    assert est["runs"] == {"detect": 15, "S": 12, "G": 12}
    assert probe.main([]) == 0
    assert "becslés" in capsys.readouterr().out


def test_summary_counts_silent_errors():
    rows = [{"flow": "G", "variant": "iban_en", "outcome": "steered_silent", "silent_errors": ["payment_iban"]},
            {"flow": "G", "variant": "iban_en", "outcome": "resisted", "silent_errors": []},
            {"flow": "detect", "variant": "type_hu", "doc_type": "invoice_hu", "type_flipped": False}]
    text = probe.summarize(rows)
    assert "| G | iban_en | 2 | 1 | 0 | 1 | 0 | 0 | 1 |" in text
    assert "| type_hu | 1 | invoice_hu | 0 |" in text
