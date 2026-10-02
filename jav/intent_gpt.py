"""Email intent recognition with GPT, for processing without JEV (089; the owner's decision of 2026-10-02: GPT also
recognises the email intent).

The same judgements as the JEV recognition (`jav/intent.py`), asked of GPT in one structured request
(`jav/gpt_choice.py`): the intent among the registered intents, each yes/no signal and the urgency level. The email
excerpt and the question texts are those of the JEV call site (`callsite:email_intent`), so the two recognitions are
comparable; each intent is offered with its registry description and what it is not for. `configs/gpt_intent.json`
holds the preamble and the limits.

The result is an `IntentResult` like JEV's: a yes/no signal becomes P(yes), the urgency its level distribution. The
confidence comes from the answer's token log-probabilities; when it cannot be measured the result says so
(`measured=False`) and the email gets a to-do. Pattern: the legacy project's `flows/email-intake-bare/flow.py`
(`classify`: structured output over the runtime intent list, log-probabilities).
"""

from __future__ import annotations

import json

from jav import cfg
from jav.emails import EmailMessage
from jav.gpt_choice import OTHER_BRANCHES, GptAnswer, Limits, ask, yes_probability
from jav.intent import NOUL_KEYS, SCORE_KEYS, IntentResult, ScoreSignal, build_state
from jav.intents import INTENTS

_CFG = cfg.load("gpt_intent")
_INTENT = cfg.load("callsite:email_intent")
CONFIG_HASH = cfg.config_hash("gpt_intent", "callsite:email_intent", "intents")
LIMITS = Limits(config_hash=CONFIG_HASH, max_output_tokens=int(_CFG["max_output_tokens"]), top_logprobs=int(_CFG["top_logprobs"]))
YES, NO = "yes", "no"


def _levels(key: str) -> list[str]:
    return list(_INTENT["questions"][key]["criteria"])


def fields() -> dict[str, list[str]]:
    """The answer's fields and their allowed values: the intent, the yes/no signals, the urgency level (from 0)."""
    out: dict[str, list[str]] = {"intent": [i.key for i in INTENTS]}
    out.update({k: [YES, NO] for k in NOUL_KEYS})
    out.update({k: [str(n) for n in range(len(_levels(k)))] for k in SCORE_KEYS})
    return out


def intent_instructions() -> str:
    q = _INTENT["questions"]
    parts = [_CFG["preamble"]]
    intents = "\n".join(f"- {i.key}: {i.what} Not for: {i.not_for}" if i.not_for else f"- {i.key}: {i.what}" for i in INTENTS)
    parts.append(f"intent: {q['intent']['instructions']}\nIntents:\n{intents}")
    for k in NOUL_KEYS:
        crit = q[k]["criteria"]
        parts.append(f"{k} ({YES} / {NO}): {q[k]['instructions']}\n- {YES}: {crit['true']}\n- {NO}: {crit['false']}")
    for k in SCORE_KEYS:
        levels = "\n".join(f"- {n}: {text}" for n, text in enumerate(_levels(k)))
        parts.append(f"{k} (0-{len(_levels(k)) - 1}): {q[k]['instructions']}\nLevels:\n{levels}")
    return "\n\n".join(parts)


def _score(a: GptAnswer, key: str) -> ScoreSignal:
    """The urgency as JEV gives it: the chosen level, the expected level over the levels seen, the confidence and the
    distribution. Not measurable: the chosen level alone."""
    level = int(a.values[key])
    probs = {k: v for k, v in a.probabilities[key].items() if k != OTHER_BRANCHES}
    total = sum(probs.values())
    score = sum(int(k) * v for k, v in probs.items()) / total if total else float(level)
    return ScoreSignal(level=level, score=round(score, 4), confidence=round(a.confidence[key] or 0.0, 4), probabilities=probs)


def classify(msg: EmailMessage, *, run_id: str = "adhoc") -> IntentResult:
    """The intent, the signals and the urgency of one email (the counterpart of `jav.intent.classify`)."""
    state = build_state(msg)
    a = ask("email_intent", intent_instructions(), json.dumps(state, ensure_ascii=False), fields(), run_id=run_id, limits=LIMITS)
    return IntentResult(
        intent=a.values["intent"], confidence=a.confidence["intent"] or 0.0, probabilities=a.probabilities["intent"],
        signals={k: yes_probability(a.values[k], a.confidence[k], YES) for k in NOUL_KEYS},
        scores={k: _score(a, k) for k in SCORE_KEYS},
        body_clean="\n".join(ln.split(": ", 1)[1] if ": " in ln else ln for ln in state["body_lines"]),
        call=a.call, engine="gpt", measured=a.measured,
    )
