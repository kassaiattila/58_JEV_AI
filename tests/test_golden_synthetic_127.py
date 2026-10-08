"""127: the synthetic golden cases (configs/golden_synthetic.json) - credit notes and receipts without an invoice
number, which the legacy golden sets do not cover.

Offline: the PDFs are written into a temporary folder and read back; the candidate finder must offer every expected
value (the free coverage check of the paid measurement); the command runs them under their own file name.
"""

import argparse
from decimal import Decimal

from jav import cfg, cli, evals
from jav.candidates import find_all
from jav.pdf import read_pdf
from jav.typepack import get as get_pack


def test_every_case_names_a_known_type_and_only_its_fields():
    data = cfg.load("golden_synthetic")
    assert data["meta"]["version"]
    ids = [c["id"] for c in data["cases"]]
    assert len(ids) == len(set(ids))
    for c in data["cases"]:
        pack = get_pack(c["type_key"])
        assert set(c["expected"]) <= set(pack.scored_fields), c["id"]


def test_the_cases_load_as_golden_cases_per_type(tmp_path):
    hu = evals.load_synthetic_cases("invoice_hu", out_dir=tmp_path)
    foreign = evals.load_synthetic_cases("invoice_foreign", out_dir=tmp_path)
    assert [c.case_id for c in hu] == ["synthetic_credit_note_hu"]
    assert {c.case_id for c in foreign} == {"synthetic_credit_note_en", "synthetic_receipt_transaction_id",
                                            "synthetic_receipt_receipt_number"}
    assert all(c.pdf.exists() and c.pdf.parent == tmp_path for c in hu + foreign)
    assert evals.load_synthetic_cases("viz_szamla", out_dir=tmp_path) == []


def test_the_candidate_finder_offers_every_expected_value(tmp_path):
    for type_key in ("invoice_hu", "invoice_foreign"):
        pack = get_pack(type_key)
        for case in evals.load_synthetic_cases(type_key, out_dir=tmp_path):
            cands = find_all(read_pdf(case.pdf).layout, pack.candidate_profile)
            for field, value in case.expected.items():
                kind = pack.kind(field)
                labels = {c.label for c in cands.get(kind, [])}
                assert value in labels, (case.case_id, field, value, sorted(labels))


def test_the_credit_notes_offer_the_referenced_original_too(tmp_path):
    """The point of the case: the original invoice's number is a candidate as well, so the Choice text decides."""
    for type_key, original in (("invoice_hu", "KI-2026-0417"), ("invoice_foreign", "AB12CD34-0008")):
        pack = get_pack(type_key)
        case = next(c for c in evals.load_synthetic_cases(type_key, out_dir=tmp_path) if "credit_note" in c.case_id)
        labels = {c.label for c in find_all(read_pdf(case.pdf).layout, pack.candidate_profile)["invoice_number"]}
        assert original in labels


def test_the_golden_command_runs_the_synthetic_cases_under_their_own_name(monkeypatch, tmp_path):
    got = {}
    monkeypatch.setattr(evals, "SYNTHETIC_DIR", tmp_path)
    monkeypatch.setattr(evals, "load_synthetic_cases", lambda type_key: ["case"])
    monkeypatch.setattr(evals, "golden", lambda *a, **k: got.update(k) or [])
    args = argparse.Namespace(store=None, arm="S", tracker=False, no_cache=False, type="invoice_foreign", no_jev=False,
                              budget_usd=None, jev_budget_usd="0.02", synthetic=True)
    assert cli.cmd_golden(args) == 0
    assert got["cases"] == ["case"] and got["label"] == "synthetic" and got["jev_budget_usd"] == Decimal("0.02")
    monkeypatch.setattr(evals, "load_synthetic_cases", lambda type_key: [])
    assert cli.cmd_golden(args) == 1
