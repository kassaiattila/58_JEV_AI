"""Type recognition with GPT, for processing without JEV (086, backlog item F-jev, step K4).

The same three judgements as the JEV detection (`jav/detect.py`), asked of GPT in one structured request:
`doc_type` (the registered types + `unknown`), `issuer_is_hungarian` (yes / no) and `language`. The document excerpt
and the question texts are those of the JEV call site (`callsite:detect`), so the two recognitions are comparable;
each type is offered with the first clause of its registry description (`configs/gpt_detect.json`).

Confidence comes from the token log-probabilities of the answer (temperature 0, top 5 alternatives per token): the
probability of the chosen option is the product of its tokens' probabilities, and an alternative token's branch is
credited to the one option it leads to. This is the model's own distribution, not a calibrated probability like
JEV's, so it has its own band in `configs/policy.json` (`detect.doc_type.gpt`). Without log-probabilities the
confidence is unknown (`measured=False`), never invented. Pattern: the legacy project's
`sidecar/app/detect_engine/service.py` (`compute_detect_margin`) and `orchestrator/framework/sidecar.py` (`detect`).
Since 089 the call and the probability arithmetic live in `jav/gpt_choice.py`, shared with the email intent.

The detailed type (`choose_detail`) is the same kind of question among the category's type packs, plus `none`.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from jav import cfg
from jav.detect import DetectResult, build_state
from jav.doc_types import DOC_TYPES, UNKNOWN
from jav.gpt_choice import GptAnswer, Limits, field_probabilities, use_agent_factory
from jav.gpt_choice import ask as _ask
from jav.pdf import PdfText

__all__ = ["GptAnswer", "choose_detail", "detect", "detect_instructions", "field_probabilities", "short_description",
           "use_agent_factory", "use_type_descriptions"]

_CFG = cfg.load("gpt_detect")
_DETECT = cfg.load("callsite:detect")
CONFIG_HASH = cfg.config_hash("gpt_detect", "callsite:detect", "doc_types")
LANGUAGES: list[str] = list(_DETECT["questions"]["language"]["criteria"])
LIMITS = Limits(config_hash=CONFIG_HASH, max_output_tokens=int(_CFG["max_output_tokens"]), top_logprobs=int(_CFG["top_logprobs"]))
YES, NO, NONE = "yes", "no", "none"

_descriptions: ContextVar[bool] = ContextVar("gpt_detect_type_descriptions", default=True)


@contextmanager
def use_type_descriptions(on: bool):
    """Measurement switch (owner's decision of 2026-10-02: the short descriptions are measured against the bare keys):
    False offers the coarse types by their keys only, as the legacy project did."""
    token = _descriptions.set(on)
    try:
        yield
    finally:
        _descriptions.reset(token)


def short_description(text: str) -> str:
    """The first clause of a description (up to the first `:`, `;` or sentence end)."""
    return re.split(r"(?::|;|\.)\s", text.strip(), maxsplit=1)[0].strip()


def _type_lines() -> str:
    if not _descriptions.get():
        return "\n".join(f"- {key}" for key in [*(t.key for t in DOC_TYPES), UNKNOWN])
    lines = [f"- {t.key}: {short_description(t.what)}" for t in DOC_TYPES]
    lines.append(f"- {UNKNOWN}: {short_description(cfg.load('doc_types')['unknown']['what'])}")
    return "\n".join(lines)


def ask(request_id: str, instructions: str, prompt: str, fields: dict[str, list[str]], *, run_id: str) -> GptAnswer:
    """One structured GPT question with this module's limits (`jav/gpt_choice.py`)."""
    return _ask(request_id, instructions, prompt, fields, run_id=run_id, limits=LIMITS)


def detect_instructions() -> str:
    q = _DETECT["questions"]
    return "\n\n".join([
        _CFG["preamble"],
        f"doc_type: {q['doc_type']['instructions']}\nDocument types:\n{_type_lines()}",
        f"issuer_is_hungarian ({YES} / {NO}): {q['issuer_is_hungarian']['instructions']}",
        f"language ({' / '.join(LANGUAGES)}): {q['language']['instructions']}",
    ])


# --- the two questions ------------------------------------------------------------------------------------


def detect(pdf: PdfText, path: str | Path, *, run_id: str = "adhoc") -> DetectResult:
    """The coarse type, the issuer's nationality and the language (the counterpart of `jav.detect.detect`)."""
    state = build_state(pdf, path)
    fields = {"doc_type": [t.key for t in DOC_TYPES] + [UNKNOWN], "issuer_is_hungarian": [YES, NO], "language": LANGUAGES}
    a = ask("detect", detect_instructions(), json.dumps(state, ensure_ascii=False), fields, run_id=run_id)
    issuer = a.values["issuer_is_hungarian"]
    issuer_conf = a.confidence["issuer_is_hungarian"]
    issuer_hu = (issuer_conf if issuer == YES else 1.0 - issuer_conf) if issuer_conf is not None else (1.0 if issuer == YES else 0.0)
    return DetectResult(
        doc_type=a.values["doc_type"], confidence=a.confidence["doc_type"] or 0.0, probabilities=a.probabilities["doc_type"],
        issuer_hu=round(issuer_hu, 4), language=a.values["language"], language_conf=a.confidence["language"] or 0.0,
        anchor_hits=state["anchor_hits"], call=a.call, engine="gpt", measured=a.measured,
    )


def choose_detail(broad: str, descriptions: dict[str, str], state: dict[str, Any], *, run_id: str) -> tuple[str | None, float | None, dict[str, float]]:
    """The detailed type among the category's type packs (`descriptions`: key -> description), or None for `none`.
    Returns (key, confidence, probabilities); the confidence is None when it is not measurable."""
    options = list(descriptions) + [NONE]
    lines = [f"- {k}: {short_description(d)}" for k, d in descriptions.items()] + [f"- {NONE}: {_CFG['detail_none_description']}"]
    instructions = _CFG["detail_preamble"].format(broad=broad) + "\nDetailed types:\n" + "\n".join(lines)
    a = ask("detect_detail", instructions, json.dumps(state, ensure_ascii=False), {"detail_type": options}, run_id=run_id)
    key = a.values["detail_type"]
    return (None if key == NONE else key), a.confidence["detail_type"], a.probabilities["detail_type"]
