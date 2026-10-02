"""047 T1.2: detailed type within the coarse detection category (e.g. bank statement → CIB or Erste).

Detection (`jav/detect.py`, M1) yields 12 coarse categories; extraction asks for the pack of the detailed type. Steps:
1. candidates: the category's packs (`parent`), without the dependent types (`auto_detect=false`, DECISIONS 047/3);
2. one candidate → that one (`single`), without a call;
3. the legacy anchor score (port of `anchor_check` in V4 `sidecar/app/detect_engine/service.py`) at the START of the
   document (`anchor_head_chars`; in a Díjbeszedő batch the start of the sub-invoice decides, not the rest of the
   batch): required hit 1, +0.25 per supporting pattern, -0.5 per excluder, clamped between 0 and 2. If the best
   candidate has a required hit and leads the second by at least `policy.json detect_detail.anchor_margin` → that one
   (`anchors`), without a call;
4. several possible → JEV Choice among the candidates with `none` (`jev`); the raw probability goes into the result,
   the threshold into the policy. Without JEV or on `none` the detailed type stays open (`key=None`); a human decides.
   086: processing without JEV passes a `chooser` instead (`jav.detect_gpt.choose_detail`, method `gpt`): the same
   question to GPT, with the token log-probabilities as confidence.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from jav import cfg, typepack

NONE = "none"
_WS = re.compile(r"\s+")

class DetailResult(BaseModel):
    broad: str
    key: str | None
    method: str  # single | anchors | jev | gpt | no_jev | no_candidate
    confidence: float | None = None  # gpt: None = not measurable
    probabilities: dict[str, float] = Field(default_factory=dict)
    candidates: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)  # the legacy anchor score per candidate (0-2)


def config_hash() -> str:
    """067 (066 Á18): the call site and all type packs together (the question's options are the packs' descriptions)."""
    return cfg.combine(cfg.config_hash("callsite:detect_detail"), typepack.catalog_hash())


def candidates(broad: str) -> list[str]:
    out = []
    for key in typepack.keys():
        pack = typepack.get(key)
        if pack.auto_detect and (pack.parent == broad or (pack.parent is None and key == broad)):
            out.append(key)
    return sorted(out)


def _match(pattern: str, text: str) -> bool:
    try:
        return re.search(pattern, text, re.IGNORECASE) is not None
    except re.error:
        return pattern.lower() in text


def anchor_score(detect: dict[str, tuple[str, ...]], text: str) -> tuple[bool, float]:
    """(required hit, score) - the semantics of the legacy `anchor_check` on the lower-cased, whitespace-normalised
    text."""
    norm = _WS.sub(" ", text.lower())
    required = detect.get("required_any", ())
    required_hit = not required or any(_match(p, norm) for p in required)
    supporting = sum(_match(p, norm) for p in detect.get("supporting", ()))
    excluders = sum(_match(p, norm) for p in detect.get("excluders", ()))
    return required_hit, max(0.0, min(2.0, (1.0 if required_hit else 0.0) + 0.25 * supporting - 0.5 * excluders))


def _state(text: str, conf: dict[str, Any]) -> dict[str, Any]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()][: conf["head_lines"]]
    return {"head_lines": [f"L{i:02d}: {ln[: conf['max_line_chars']]}" for i, ln in enumerate(lines, 1)]}


def resolve(broad: str, text: str, *, jev: Any, run_id: str, use_cache: bool = True, chooser: Any = None) -> DetailResult:
    cands = candidates(broad)
    if not cands:
        return DetailResult(broad=broad, key=None, method="no_candidate")
    if len(cands) == 1:
        return DetailResult(broad=broad, key=cands[0], method="single", candidates=cands)
    from jav.policy import DETECT_DETAIL

    packs = {k: typepack.get(k) for k in cands}
    conf = cfg.load("callsite:detect_detail")
    head = text[: conf["anchor_head_chars"]]
    scored = {k: anchor_score(packs[k].detect, head) for k in cands}
    ranked = sorted(cands, key=lambda k: -scored[k][1])
    base = dict(broad=broad, candidates=cands, scores={k: round(v[1], 3) for k, v in scored.items()})
    top, second = ranked[0], ranked[1]
    if scored[top][0] and scored[top][1] - scored[second][1] >= DETECT_DETAIL["anchor_margin"]:
        return DetailResult(key=top, method="anchors", **base)
    if jev is None and chooser is not None:
        key, confidence, probabilities = chooser(broad, {k: packs[k].document for k in ranked}, _state(text, conf), run_id=run_id)
        return DetailResult(key=key if key in packs else None, method="gpt", confidence=confidence, probabilities=probabilities, **base)
    if jev is None:
        return DetailResult(key=None, method="no_jev", **base)
    from typesafe_sdk import Choice  # the JEV SDK type; the call goes through the shared adapter (`jev.ask`)

    criteria = {k: packs[k].document for k in ranked}
    criteria[NONE] = conf["none_description"]
    result = jev.ask(conf["request_id"], _state(text, conf), {"detail_type": Choice(instructions=conf["instructions"], criteria=criteria)},
                     run_id=run_id, use_cache=use_cache, config_hash=config_hash())
    pick = result.response.choices["detail_type"]
    key = pick.choice if pick.choice in packs else None
    return DetailResult(key=key, method="jev", confidence=float(pick.confidence),
                        probabilities={k: round(float(v), 4) for k, v in dict(pick.probabilities).items()}, **base)
