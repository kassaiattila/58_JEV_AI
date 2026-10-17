"""151 (backlog F-outgoing-invoice-S-path; DECISIONS 151): an S path for the outgoing invoice.

The outgoing invoice pack had only the G path (GPT extraction + JEV verification). It now has the S path too: code
finds the candidates, a JEV Choice per field picks one (configs/callsites/select_invoice_out.json, the roles of
select_foreign turned round: our company is the issuer). The automatic path stays the G path until the owner decides
on the measurement, and the G path keeps its own glossary, so its questions do not change. Eight synthetic outgoing
invoices (configs/golden_synthetic.json) are the etalon; a local case list (outside git) compares the S path with the G
path's results on real invoices. Synthetic data and a stand-in JEV only; no paid calls.
"""

import argparse
import json
from pathlib import Path

from jav import cfg, cli, evals, store, typepack
from jav.adapters import jev as jev_mod
from jav.jev_select import site_for
from jav.jev_verify import VerifySite
from tests.test_runtime_worker import FakeClient

CASES = [c for c in cfg.load("golden_synthetic")["cases"] if c["type_key"] == "invoice_out"]


def test_the_pack_has_both_paths_and_the_automatic_one_stays_g():
    pack = typepack.get("invoice_out")
    assert pack.arms == ("S", "G") and pack.default_arm == "G" and pack.select_callsite == "select_invoice_out"
    assert [typepack.resolve_arm("invoice_out", a) for a in ("auto", "S", "G")] == ["G", "S", "G"]


def test_the_g_path_keeps_its_own_glossary():
    own = cfg.load("callsite:verify_invoice_out")
    site = VerifySite(typepack.get("invoice_out"))
    assert site.glossary == own["glossary"]
    assert "callsite:select_invoice_out" not in site.hash_names  # its call site hash does not move with the S path's
    hu = VerifySite(typepack.get("invoice_hu"))  # a pack whose G path takes the select call site's glossary: unchanged
    assert hu.glossary == cfg.load("callsite:select")["glossary"] and "callsite:select" in hu.hash_names


def test_every_scored_field_has_its_question():
    site = site_for("invoice_out")
    pack = typepack.get("invoice_out")
    asked = [f for r in site.requests.values() for f in r["fields"]]
    fields = [f for f in pack.scored_fields if f != "currency"]
    assert sorted(asked) == sorted(fields) and len(asked) == len(set(asked))  # each field in exactly one request
    assert all(f in site.instructions and f in site.presence_what and f in site.field_kind for f in fields)
    assert site.extra_request == {"currency": "out_money"}
    assert set(site.extra["currency"]["criteria"]) >= {"HUF", "EUR", "USD", "CHF", "none"}


def test_the_synthetic_etalon_covers_the_outgoing_layouts():
    assert len(CASES) == 8
    expected = {f for c in CASES for f in c["expected"]}
    assert expected == set(typepack.get("invoice_out").scored_fields)  # every scored field is measured somewhere


def test_the_candidates_hold_every_expected_value_but_a_private_persons_name(tmp_path):
    cases = evals.load_synthetic_cases("invoice_out", out_dir=tmp_path)
    recall = evals.candidate_recall(cases, verbose=False, type_key="invoice_out")
    assert sum(hit for hit, _ in recall.values()) == sum(n for _, n in recall.values()) - 1
    assert recall["buyer_name"] == (7, 8)  # 'Teszt Elek' without a legal form or label is no name candidate


def test_the_s_path_runs_on_an_outgoing_invoice(tmp_path):
    from jav.flow import run_one

    (case,) = evals.load_synthetic_cases("invoice_out", out_dir=tmp_path)[:1]
    client = FakeClient()
    adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        state = run_one(str(case.pdf), case.case_id, "S", doc_type="invoice_out")
    assert state.final_status in ("done", "needs_review") and client.calls == 3  # out_parties, out_header, out_money
    with store.use_store(tmp_path / "w.sqlite"), store.connect() as c:
        steps = sorted(r["step"] for r in c.execute("SELECT step FROM ledger WHERE provider='jev'"))
    assert steps == ["out_header", "out_money", "out_parties"]


def test_a_local_case_list_is_measured_apart(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    listing = tmp_path / "cases.json"
    listing.write_text(json.dumps({"cases": [{"case_id": "a", "path": str(pdf), "expected": {"invoice_number": "AB001"}},
                                             {"case_id": "gone", "path": str(tmp_path / "gone.pdf"), "expected": {}}]}),
                       encoding="utf-8")
    cases = evals.load_case_file(listing, "invoice_out")
    assert [(c.case_id, c.pdf, c.expected, c.type_key) for c in cases] == [("a", pdf, {"invoice_number": "AB001"}, "invoice_out")]
    seen = {}

    def golden(arm, run_one, **kw):
        seen.update(kw, arm=arm)
        return []

    monkeypatch.setattr(evals, "golden", golden)
    args = argparse.Namespace(store=None, arm="S", tracker=False, no_cache=False, type="invoice_out", engine="jev",
                              budget_usd=None, jev_budget_usd="0.20", synthetic=False, cases=str(listing))
    assert cli.cmd_golden(args) == 0
    assert seen["label"] == "local" and [c.case_id for c in seen["cases"]] == ["a"]


def test_the_local_label_is_in_the_run_files_name():
    assert evals._run_name("invoice_out", "local_S") == "invoice_out_local_S"
    assert Path(evals.SYNTHETIC_DIR).name == "synthetic_golden"
