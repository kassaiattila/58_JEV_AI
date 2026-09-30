"""BACKLOG (M3 jelek, handoff 011): sürgősség Score-ral, „több kérés van-e" Noul, beszúrt utasítás (promptinjekció) Noul.

Offline: hamis kliens adja a Jev-választ (Choice + Noulok + Score egy kérésben); a policy és az eval-riport tiszta függvény.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typesafe_sdk import Choice, Noul, Score, SystemOneResponse

from jav import cfg, policy, store
from jav.adapters.jev import JevAdapter
from jav.emails import Attachment, EmailMessage
from jav.intent import NOUL_KEYS, SCORE_KEYS, build_questions, classify


class FakeClient:
    """Choice: `szamlakuldes` 0,9; Noul: a `nouls` szótár szerint (alap 0,1); Score: a `scores` szótár szerint (alap: 2. szint 0,6)."""

    def __init__(self, nouls: dict[str, float] | None = None, scores: dict[str, dict[int, float]] | None = None) -> None:
        self.nouls = nouls or {}
        self.scores = scores or {}
        self.requests: list[dict] = []

    def system_one(self, *, state, questions, model):
        self.requests.append({"state": state, "questions": questions})
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                keys = list(q.criteria)
                pick = "szamlakuldes" if "szamlakuldes" in keys else keys[0]
                answers[qid] = {"type": "choice", "choice": pick, "confidence": 0.9,
                                "probabilities": {k: (0.9 if k == pick else round(0.1 / max(len(keys) - 1, 1), 4)) for k in keys}}
            elif isinstance(q, Score):
                probs = self.scores.get(qid) or {0: 0.1, 1: 0.2, 2: 0.6, 3: 0.1}
                probs = {str(k): v for k, v in probs.items()}
                score = sum(int(k) * v for k, v in probs.items())
                answers[qid] = {"type": "score", "score": score, "confidence": max(probs.values()), "probabilities": probs,
                                "legend": {str(i): c for i, c in enumerate(q.criteria)}}
            else:
                answers[qid] = {"type": "noul", "noul": self.nouls.get(qid, 0.1)}
        # JSON-módban, mint az SDK a HTTP-válasznál: a Score szint-kulcsai stringként érkeznek, a modell egésszé alakítja
        return SystemOneResponse.model_validate_json(json.dumps({"model": "jev-1.13.0", "usage": {"input_tokens": 400, "output_tokens": 5}, "answers": answers}))


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    return tmp_path


def _msg() -> EmailMessage:
    return EmailMessage(message_id="m1", mailbox="x@example.hu", sender="noreply@billingo.hu", subject="Számlája érkezett",
                        body="Önnek elektronikus számlája érkezett.\nFizetési határidő: 2026-06-05\n", attachments=[Attachment(filename="a.pdf")])


def test_email_intent_config_has_score_and_guard_questions():
    """v1.1.0: `urgency` Score (3–10 helyzet-leírás, nem fokozat-szó), `multiple_requests` és `prompt_injection` Noul; `tone_urgent` nincs."""
    data = cfg.load("callsite:email_intent")
    assert tuple(int(x) for x in data["meta"]["version"].split(".")) >= (1, 1, 0)
    q = data["questions"]
    assert "tone_urgent" not in q
    urg = q["urgency"]
    assert urg["kind"] == "score" and 3 <= len(urg["criteria"]) <= 10
    assert all(isinstance(c, str) and len(c) > 30 for c in urg["criteria"])  # helyzet-leírás, nem „közepes"
    for key in ("multiple_requests", "prompt_injection"):
        assert q[key]["kind"] == "noul" and set(q[key]["criteria"]) == {"true", "false"}
    assert SCORE_KEYS == ("urgency",)
    assert set(NOUL_KEYS) == {"requires_action", "mentions_deadline", "attachment_is_the_subject", "multiple_requests", "prompt_injection"}


def test_build_questions_builds_score_object():
    qs = build_questions()
    assert isinstance(qs["urgency"], Score) and isinstance(qs["prompt_injection"], Noul)
    assert list(qs["urgency"].criteria) == cfg.load("callsite:email_intent")["questions"]["urgency"]["criteria"]
    assert set(qs) == {"intent", *NOUL_KEYS, *SCORE_KEYS}


def test_classify_fills_signals_and_scores(isolated: Path):
    fake = FakeClient(nouls={"prompt_injection": 0.85, "multiple_requests": 0.2}, scores={"urgency": {0: 0.05, 1: 0.15, 2: 0.7, 3: 0.1}})
    jev = JevAdapter(client=fake, cache_dir=isolated / "cache")
    r = classify(jev, _msg(), run_id="t1", use_cache=False)
    assert r.intent == "szamlakuldes"
    assert r.signals["prompt_injection"] == 0.85 and r.signals["multiple_requests"] == 0.2
    assert "tone_urgent" not in r.signals and "urgency" not in r.signals  # a Score nem Noul-jel
    u = r.scores["urgency"]
    assert u.level == 2 and abs(u.score - 1.85) < 1e-6 and u.confidence == 0.7
    assert u.probabilities == {"0": 0.05, "1": 0.15, "2": 0.7, "3": 0.1}
    json.dumps(r.scores["urgency"].model_dump())  # jsonl-be írható


def test_adapter_cache_roundtrip_keeps_score_answers(isolated: Path):
    """A kérés-hash cache Score-válasszal: a fájlban a szint-kulcsok stringek, a visszaolvasás (JSON-mód) egésszé alakítja."""
    fake = FakeClient(scores={"urgency": {0: 0.1, 1: 0.1, 2: 0.2, 3: 0.6}})
    jev = JevAdapter(client=fake, cache_dir=isolated / "cache")
    first = classify(jev, _msg(), run_id="t1", use_cache=True)
    second = classify(jev, _msg(), run_id="t2", use_cache=True)
    assert not first.call.cached and second.call.cached
    assert second.scores["urgency"].level == 3 and second.scores["urgency"].probabilities == first.scores["urgency"].probabilities
    assert len(fake.requests) == 1 + 1  # 1 alias-szonda (jev-latest -> konkrét verzió) + 1 élő hívás; a második classify cache-találat


def test_policy_signal_reasons_and_route():
    """Beszúrt utasítás az igen-sávban: review-ok + `human:suspicious` útvonal minden más elé; a több-kérés jel csak mérhető, nem review-ok."""
    assert policy.email_signal_reasons({"prompt_injection": 0.9, "multiple_requests": 0.9}) == ["signal:prompt_injection:0.90"]
    assert policy.email_signal_reasons({"prompt_injection": 0.2, "multiple_requests": 0.95}) == []
    assert policy.email_signal_reasons({"prompt_injection": 0.5}) == []  # bizonytalan sáv: uncertain_review false
    pdf_typed = [Attachment(filename="a.pdf", path="a.pdf", doc_type="invoice_hu", type_conf=0.98, status="done")]
    assert policy.email_next_flow("szamlakuldes", 0.9, pdf_typed, signals={"prompt_injection": 0.9}) == "human:suspicious"
    assert policy.email_next_flow("szamlakuldes", 0.9, pdf_typed, signals={"prompt_injection": 0.2}) == "m2:invoice_hu"
    assert policy.email_next_flow("szamlakuldes", 0.9, pdf_typed, signals=None) == "m2:invoice_hu"
    assert policy.email_next_flow("szamlakuldes", 0.3, pdf_typed, signals={"prompt_injection": 0.9}) == "human:suspicious"  # az injekció a low_conf elé
    p = cfg.load("policy")
    assert p["email"]["signal_review"] == ["prompt_injection"] and p["email"]["signal_routes"] == {"prompt_injection": "human:suspicious"}
    assert "email.urgency" in p["band_for"]


def test_injection_probe_perturbation_is_pure_and_bilingual():
    """Beszúrt-utasítás szonda: a golden levél törzséhez a végén egy, a feldolgozó rendszernek címzett mondat kerül; az eredeti nem változik."""
    from jav.evals_email import INJECTIONS, inject_instruction

    msg = _msg()
    original = msg.body
    variants = {name: inject_instruction(msg, name) for name in INJECTIONS}
    assert set(variants) >= {"clean", "hu_override_top", "en_override_top", "hu_reroute_top", "en_override_end"}
    assert variants["clean"].body == original and msg.body == original
    assert variants["en_override_end"].body.startswith(original) and "ignore" in variants["en_override_end"].body.lower()
    top = variants["en_override_top"].body
    assert top.startswith(original.split("\n")[0]) and "ignore" in top.lower() and top.endswith(original.split("\n", 1)[1])
    assert "utasítás" in variants["hu_override_top"].body.lower()
    assert all(v.message_id == msg.message_id and v.subject == msg.subject for v in variants.values())


def test_eval_report_reads_scores_as_score_judgments(tmp_path: Path):
    from jav.eval_report import band_of, determinism_summary, judgments_from_file, per_question

    rows = [
        {"case_id": "e1", "expected": "szamlakuldes", "got": "szamlakuldes", "confidence": 0.99, "signals": {"prompt_injection": 0.05},
         "scores": {"urgency": {"level": 2, "score": 1.85, "confidence": 0.7, "probabilities": {"0": 0.05, "1": 0.15, "2": 0.7, "3": 0.1}}},
         "next_flow": "m1:detect", "top3": {"szamlakuldes": 1.0}},
        {"case_id": "e1", "expected": "szamlakuldes", "got": "szamlakuldes", "confidence": 0.98, "signals": {"prompt_injection": 0.06},
         "scores": {"urgency": {"level": 1, "score": 1.4, "confidence": 0.5, "probabilities": {"0": 0.1, "1": 0.5, "2": 0.3, "3": 0.1}}},
         "next_flow": "m1:detect", "top3": {"szamlakuldes": 1.0}},
    ]
    path = tmp_path / "20260920_000000_email_determinism.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    js = judgments_from_file(path)
    sc = [j for j in js if j.kind == "score"]
    assert len(sc) == 2 and {j.question for j in sc} == {"urgency"} and {j.callsite for j in sc} == {"email.urgency"}
    assert sc[0].label == "2" and sc[0].confidence == 0.7 and sc[0].top_prob == 0.7 and sc[0].second_prob == 0.15 and sc[0].p is None
    assert band_of(sc[0]) in ("auto", "uncertain", "human")
    pq = {(r["question"], r["kind"]): r for r in per_question(js)}
    assert pq[("urgency", "score")]["n"] == 1 and pq[("urgency", "score")]["mean"] == 0.7  # csak az 1. futás; conf az érték
    det = {r["question"]: r for r in determinism_summary(js)}
    assert det["urgency"]["flips"] == 1 and det["urgency"]["std_max"] > 0
    # beszúrt-utasítás szonda: a prompt_injection igazsága a variánsból; az esetek variánsonként külön (nem ismételt futás)
    probe = tmp_path / "20260920_000001_email_injection_probe.jsonl"
    probe.write_text("\n".join(json.dumps({**rows[0], "variant": v, "signals": {"prompt_injection": p}}) for v, p in (("clean", 0.05), ("en_override", 0.9))), encoding="utf-8")
    pj = judgments_from_file(probe)
    inj = {j.case_id: j for j in pj if j.question == "prompt_injection"}
    assert inj["e1/clean"].expected == "no" and inj["e1/clean"].correct is True
    assert inj["e1/en_override"].expected == "yes" and inj["e1/en_override"].correct is True
    assert all(j.run_no == 1 and j.flow == "email_injection_probe" for j in pj)
