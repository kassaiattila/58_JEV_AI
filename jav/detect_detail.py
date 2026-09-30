"""047 T1.2: részletes típus a durva felismerési kategórián belül (pl. bankkivonat → CIB vagy Erste).

A felismerés (`jav/detect.py`, M1) 12 durva kategóriát ad; a kinyerés a részletes típus csomagját kéri. A lépés:
1. jelöltek: a kategória csomagjai (`parent`), a függő típusok nélkül (`auto_detect=false`, DECISIONS 047/3);
2. egy jelölt → az (`single`), hívás nélkül;
3. a régi horgony-pontszám (a V4 `sidecar/app/detect_engine/service.py` `anchor_check` portja) az irat ELEJÉN
   (`anchor_head_chars`; a Díjbeszedő-kötegben a részszámla eleje dönt, nem a köteg többi része): kötelező találat 1,
   támogatónként +0,25, kizárónként -0,5, 0 és 2 közé szorítva. Ha a legjobb jelöltnek van kötelező találata, és legalább
   `policy.json detect_detail.anchor_margin` előnye van a másodikhoz képest → az (`anchors`), hívás nélkül;
4. több lehetséges → JEV Choice a jelöltek közül `none`-nal (`jev`); a nyers valószínűség az eredményben, a küszöb a
   policyban. JEV nélkül vagy `none` esetén a részletes típus nyitva marad (`key=None`), a döntés emberé.
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
    method: str  # single | anchors | jev | no_jev | no_candidate
    confidence: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    candidates: list[str] = Field(default_factory=list)
    scores: dict[str, float] = Field(default_factory=dict)  # a régi horgony-pontszám jelöltenként (0-2)


def config_hash() -> str:
    """067 (066 Á18): a hívási hely és az összes típuscsomag (a kérdés opciói a csomagok leírásai) együtt."""
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
    """(kötelező találat, pontszám) - a régi `anchor_check` szemantikája a kisbetűsített, szóköz-normalizált szövegen."""
    norm = _WS.sub(" ", text.lower())
    required = detect.get("required_any", ())
    required_hit = not required or any(_match(p, norm) for p in required)
    supporting = sum(_match(p, norm) for p in detect.get("supporting", ()))
    excluders = sum(_match(p, norm) for p in detect.get("excluders", ()))
    return required_hit, max(0.0, min(2.0, (1.0 if required_hit else 0.0) + 0.25 * supporting - 0.5 * excluders))


def _state(text: str, conf: dict[str, Any]) -> dict[str, Any]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()][: conf["head_lines"]]
    return {"head_lines": [f"L{i:02d}: {ln[: conf['max_line_chars']]}" for i, ln in enumerate(lines, 1)]}


def resolve(broad: str, text: str, *, jev: Any, run_id: str, use_cache: bool = True) -> DetailResult:
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
    if jev is None:
        return DetailResult(key=None, method="no_jev", **base)
    from typesafe_sdk import Choice  # a JEV SDK-típus; a hívás a közös adapteren megy (`jev.ask`)

    criteria = {k: packs[k].document for k in ranked}
    criteria[NONE] = conf["none_description"]
    result = jev.ask(conf["request_id"], _state(text, conf), {"detail_type": Choice(instructions=conf["instructions"], criteria=criteria)},
                     run_id=run_id, use_cache=use_cache, config_hash=config_hash())
    pick = result.response.choices["detail_type"]
    key = pick.choice if pick.choice in packs else None
    return DetailResult(key=key, method="jev", confidence=float(pick.confidence),
                        probabilities={k: round(float(v), 4) for k, v in dict(pick.probabilities).items()}, **base)
