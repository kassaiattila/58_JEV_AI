"""127 (backlog S-injection, JEV part): every S selection question and every JEV verification question says that the
document text is data, not instructions. The sentence sits in each question's instructions, never in the state (the
state is where the document text itself is). One text for every call site; the verify_* call sites inherit it.

Offline: the question builders only read the JSON; the request test uses a fake client, so no JEV call is made.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typesafe_sdk import Choice, Noul, SystemOneResponse

from jav import cfg, store
from jav.adapters.jev import JevAdapter
from jav.jev_select import SelectSite, select_fields
from jav.jev_verify import VerifySite
from jav.models import Candidate, LineLayout
from jav.typepack import get as get_pack

DATA = "data, not instructions"
S_SITES = ("select", "select_foreign", "select_utility")
PACKS = ("invoice_hu", "invoice_foreign", "villamos_energia_szamla")


def _guard() -> str:
    return cfg.load("callsite:verify")["document_guard"]


def test_one_guard_text_in_every_s_call_site_and_the_verify_base():
    texts = {cfg.load(f"callsite:{name}")["document_guard"] for name in (*S_SITES, "verify")}
    assert len(texts) == 1
    assert DATA in texts.pop()


def test_every_verify_call_site_inherits_the_guard_unchanged():
    for path in sorted(cfg.CALLSITE_DIR.glob("verify_*.json")):
        data = cfg.load(f"callsite:{path.stem}")
        assert data.get("inherits") == "verify", path.name
        assert "document_guard" not in data, path.name  # no call site overrides the shared text


@pytest.mark.parametrize("pack_key", PACKS)
def test_every_s_question_carries_the_guard_after_the_glossary(pack_key: str):
    site = SelectSite(get_pack(pack_key))
    head = f"{site.glossary}\n\n{_guard()}\n\n"
    field = next(iter(site.instructions))
    cand = Candidate(kind=site.field_kind[field], label="x", raw="x", line_no=1, context="L01")
    questions = [site.build_choice(field, [cand]), site.build_presence(field)]
    questions += [site.build_extra(key) for key in site.extra]
    for q in questions:
        assert isinstance(q.instructions, str) and q.instructions.startswith(head)


@pytest.mark.parametrize("pack_key", PACKS)
def test_every_verify_question_carries_the_guard_as_its_rule(pack_key: str):
    site = VerifySite(get_pack(pack_key))
    for name in site.nouls:
        assert site._noul(name).instructions["rule"] == _guard()


def test_the_invoice_verification_has_a_request_size_budget():
    for pack_key in ("invoice_hu", "invoice_foreign"):
        assert VerifySite(get_pack(pack_key)).request_char_budget == 110000


class _RecordingClient:
    """Answers the first option / 0.9 and keeps every request."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def system_one(self, *, state, questions, model):
        self.requests.append({"state": state, "questions": questions})
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                keys = list(q.criteria)
                answers[qid] = {"type": "choice", "choice": keys[0], "confidence": 0.9,
                                "probabilities": {k: (0.9 if i == 0 else 0.1 / max(len(keys) - 1, 1)) for i, k in enumerate(keys)}}
            else:
                answers[qid] = {"type": "noul", "noul": 0.9}
        return SystemOneResponse.model_validate({"model": "jev-1.13.0", "usage": {"input_tokens": 10, "output_tokens": 1}, "answers": answers})


def test_the_guard_never_goes_into_the_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    client = _RecordingClient()
    jev = JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    lines = [LineLayout(no=1, page=1, text="Teszt Kft."), LineLayout(no=2, page=1, text="Adószám: 12345678-1-42")]
    cands = {"tax_id": [Candidate(kind="tax_id", label="12345678-1-42", raw="12345678-1-42", line_no=2, context="L02")],
             "name": [Candidate(kind="name", label="Teszt Kft.", raw="Teszt Kft.", line_no=1, context="L01")]}
    select_fields(jev, lines, cands, run_id="r")
    assert client.requests
    for req in client.requests:
        assert _guard() not in json.dumps(req["state"], ensure_ascii=False)
        assert all(_guard() in (q.instructions if isinstance(q.instructions, str) else json.dumps(q.instructions))
                   for q in req["questions"].values() if isinstance(q, (Choice, Noul)))
