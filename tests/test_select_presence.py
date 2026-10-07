"""S path presence Noul (BACKLOG: JEV_PLAYBOOK §4/5) - offline, with a fake client.

- next to each field's Choice, a `<field>__present` Noul in the same batched request ("is it there at all");
- the pick carries the raw `present_p` and the chosen candidate's line number (`line_no`, from code - no extra
  question);
- policy: chosen value + "absent" presence → review reason; `none` + "present" presence → review reason; record conf =
  the weakest judgement (min of the fields' effective confidences);
- store: `record_conf` + `evidence` into the `datapoints` table (additive migration); eval: presence judgements with
  ground truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typesafe_sdk import Choice, Noul, SystemOneResponse

from jav import cfg, policy, store
from jav.adapters.jev import JevAdapter
from jav.jev_select import PRESENCE_WHAT, build_presence, effective_conf, record_conf, select_fields
from jav.models import Candidate, CellLayout, FieldPick, FlowState, LineLayout


class FakeClient:
    """Choice: the first candidate with 0.9; Noul: per the `nouls` dict (default 0.9 = "present")."""

    def __init__(self, nouls: dict[str, float] | None = None, pick_none: set[str] | None = None) -> None:
        self.nouls = nouls or {}
        self.pick_none = pick_none or set()
        self.requests: list[dict] = []

    def system_one(self, *, state, questions, model):
        self.requests.append({"state": state, "questions": questions})
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                keys = list(q.criteria)
                pick = "none" if qid in self.pick_none else keys[0]
                answers[qid] = {"type": "choice", "choice": pick, "confidence": 0.9, "probabilities": {k: (0.9 if k == pick else round(0.1 / max(len(keys) - 1, 1), 4)) for k in keys}}
            else:
                answers[qid] = {"type": "noul", "noul": self.nouls.get(qid, 0.9)}
        return SystemOneResponse.model_validate({"model": "jev-1.13.0", "usage": {"input_tokens": 500, "output_tokens": 5}, "answers": answers})


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    return tmp_path


def _lines(texts: list[str]) -> list[LineLayout]:
    return [LineLayout(no=i, page=1, text=t, cells=[CellLayout(text=t, x0=30, x1=300)]) for i, t in enumerate(texts, 1)]


def _cands() -> dict[str, list[Candidate]]:
    return {
        "tax_id": [Candidate(kind="tax_id", label="12345678-1-42", raw="12345678-1-42", line_no=2, context="L02"),
                   Candidate(kind="tax_id", label="87654321-2-13", raw="87654321-2-13", line_no=5, context="L05")],
        "name": [Candidate(kind="name", label="Teszt Kft.", raw="Teszt Kft.", line_no=1, context="L01")],
        "date": [Candidate(kind="date", label="2024-01-05", raw="2024.01.05.", line_no=3, context="L03")],
        "money": [Candidate(kind="money", label="1000", raw="1 000 Ft", line_no=6, context="L06")],
    }


LINES = _lines(["Teszt Kft.", "Adószám: 12345678-1-42", "Kelt: 2024.01.05.", "Vevő: Példa Zrt.", "Adószám: 87654321-2-13", "Bruttó: 1 000 Ft"])


def test_select_json_has_presence_block():
    d = cfg.load("callsite:select")
    assert d["meta"]["version"] >= "1.1.0"
    assert "{what}" in d["presence_template"]
    assert set(d["presence_what"]) == set(d["instructions"])  # a presence question next to every Choice field
    assert set(PRESENCE_WHAT) == set(d["instructions"])


def test_presence_noul_is_batched_with_the_choice(isolated: Path):
    client = FakeClient(nouls={"supplier_tax_id__present": 0.95, "buyer_tax_id__present": 0.1})
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.13.0")
    picks, calls = select_fields(jev, LINES, _cands(), run_id="r")

    parties = next(r for r in client.requests if "supplier_tax_id" in r["questions"])
    assert isinstance(parties["questions"]["supplier_tax_id__present"], Noul)
    assert "supplier_address__present" not in parties["questions"]  # no candidate -> no Choice, no presence question
    q = build_presence("supplier_tax_id")
    assert "SUPPLIER" in q.instructions and "Lnn" in q.instructions

    p = picks["supplier_tax_id"]
    assert p.label == "12345678-1-42" and p.present_p == 0.95 and p.line_no == 2  # line ID from the candidate, in code
    assert picks["buyer_tax_id"].present_p == 0.1 and picks["buyer_tax_id"].line_no == 2  # fake client picks the first
    assert picks["supplier_address"].present_p is None and picks["supplier_address"].line_no is None
    assert len(calls) == 3  # still three batched requests, no extra call


def test_effective_and_record_confidence():
    chosen_ok = FieldPick(field="a", label="x", confidence=0.9, present_p=0.95, n_options=2, request_id="r")
    chosen_absent = FieldPick(field="b", label="x", confidence=0.9, present_p=0.2, n_options=2, request_id="r")
    none_present = FieldPick(field="c", label=None, confidence=0.8, present_p=0.9, n_options=2, request_id="r")
    none_absent = FieldPick(field="d", label=None, confidence=0.8, present_p=0.05, n_options=2, request_id="r")
    no_presence = FieldPick(field="e", label="x", confidence=0.7, n_options=2, request_id="r")
    no_cands = FieldPick(field="f", label=None, confidence=None, n_options=0, request_id="r")  # 069: no candidate, no judgement
    assert effective_conf(chosen_ok) == 0.9
    assert effective_conf(chosen_absent) == 0.2  # chosen, but "not there" -> the weaker judgement
    assert effective_conf(none_present) == pytest.approx(0.1)  # none, but "present" -> 1 - 0.9
    assert effective_conf(none_absent) == 0.8
    assert effective_conf(no_presence) == 0.7
    assert record_conf({"a": chosen_ok, "b": chosen_absent, "f": no_cands}) == 0.2  # min of the JEV judgements, zero-candidate excluded
    assert record_conf({"f": no_cands}) is None


def test_presence_policy_reasons():
    st = FlowState(source_path="x.pdf", case_id="c", arm="S", picks={
        "supplier_tax_id": FieldPick(field="supplier_tax_id", label="12345678-1-42", confidence=0.9, present_p=0.2, n_options=2, request_id="r"),
        "invoice_number": FieldPick(field="invoice_number", label=None, confidence=0.9, present_p=0.9, n_options=3, request_id="r"),
        "due_date": FieldPick(field="due_date", label=None, confidence=0.9, present_p=0.5, n_options=2, request_id="r"),  # uncertain band: no reason
        "gross_total": FieldPick(field="gross_total", label="1000", confidence=0.95, present_p=0.97, n_options=2, request_id="r"),
    })
    policy.apply_pick_policy(st)
    assert "pick:absent_but_chosen:supplier_tax_id:0.20" in st.review_reasons
    assert "pick:present_but_none:invoice_number:0.90" in st.review_reasons
    assert "pick:none:invoice_number" in st.review_reasons  # required field with none (the old reason stays too)
    assert not any("due_date" in r or "gross_total" in r for r in st.review_reasons)
    assert policy.band_name("invoice.pick.presence") == "default"


def test_store_keeps_record_conf_and_evidence(isolated: Path):
    store.insert_datapoints(
        run_id="r1", doc_id="d1", doc_type="invoice_hu", arm="S", datapoints={"gross_total": "1000"}, field_conf={"gross_total": 0.95},
        validation=[], route="auto", review_reasons=[], final_status="done", record_conf=0.2,
        evidence={"gross_total": {"line_no": 6, "present_p": 0.97}},
    )
    with store.connect() as c:
        row = c.execute("SELECT record_conf, evidence FROM datapoints WHERE run_id='r1'").fetchone()
    assert row["record_conf"] == 0.2 and '"line_no": 6' in row["evidence"]


def test_eval_report_presence_judgments(tmp_path: Path):
    import json

    from jav import eval_report as er

    row = {"case_id": "c1", "arm": "S", "run_no": 1, "route": "auto", "review_reasons": [], "record_conf": 0.2,
           "scores": {"supplier_name": True, "invoice_number": True}, "expected_present": {"supplier_name": True, "invoice_number": False},
           "picks": {"supplier_name": {"label": "A", "confidence": 0.99, "n_options": 3, "top3": {"A": 0.99}, "present_p": 0.97, "line_no": 1},
                     "invoice_number": {"label": None, "confidence": 0.9, "n_options": 2, "top3": {"none": 0.9}, "present_p": 0.2, "line_no": None}},
           "verdicts": None}
    p = tmp_path / "20260101_000000_golden_S.jsonl"
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")
    js = er.judgments_from_file(p)
    pres = [j for j in js if j.kind == "noul"]
    assert {j.question for j in pres} == {"supplier_name.present", "invoice_number.present"} and {j.callsite for j in pres} == {"invoice.pick.presence"}
    a = next(j for j in pres if j.question == "supplier_name.present")
    assert a.p == 0.97 and a.expected == "yes" and a.correct is True
    b = next(j for j in pres if j.question == "invoice_number.present")
    assert b.expected == "no" and b.label == "no" and b.correct is True
    md = er.report_markdown([p])
    assert "supplier_name.present" in md
