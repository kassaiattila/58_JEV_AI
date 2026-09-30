"""Forrásellenőrzött állítások és védett sorhatárok a PDF/OCR-elrendezésből (a 040-ben a kísérletekből a futtató kódba emelve)."""
from __future__ import annotations

import re
import hashlib

from pydantic import BaseModel, Field
from typesafe_sdk import Choice

from jav.models import LineLayout
from jav.adapters.jev import JevUnavailableError


class GroundedClaim(BaseModel):
    statement: str = Field(min_length=1, max_length=1000)
    source_sha256: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)


def verify_claim(text: str, claim: GroundedClaim, config: dict, ask) -> dict:
    """Szövegazonosság és pontos idézet ellenőrzése az AI-hívás előtt."""
    result = {"claim": claim.model_dump(), "status": "source_mismatch", "response": None}
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != claim.source_sha256:
        return result
    if not 0 <= claim.start < claim.end <= len(text) or text[claim.start:claim.end] != claim.quote:
        result["status"] = "invalid_quote"
        return result
    if len(text) > config["max_context_chars"]:
        result["status"] = "context_limit"
        return result
    try:
        response = ask("claim_relation", {"claim":claim.statement, "quote":claim.quote, "context":text},
                       {"relation":Choice(instructions=config["question"], criteria=config["criteria"])})
    except JevUnavailableError as exc:
        result.update(status="unavailable", error=exc.reason)
        return result
    answer = response.choices["relation"]
    result["response"] = response.model_dump(mode="json")
    result["status"] = ({"supports":"supported", "contradicts":"contradicted", "says_nothing":"unsupported"}[answer.choice]
                        if answer.confidence >= config["min_confidence"] else "uncertain")
    return result


def protected_boundaries(rows: list[LineLayout], config: dict) -> dict[int, list[str]]:
    """0-alapú sorindex -> a sor ELŐTTI tiltás okai; nem tanult táblázatfelismerő.

    A minták a típus/módszer konfigurációjából jönnek. A választható balcellás
    kivétel csak megengedi a JEV-vizsgálatot, nem ír elő sorösszevonást.
    """
    if any(row.no < 1 or row.page < 1 for row in rows) or any(
        b.no <= a.no or b.page < a.page for a, b in zip(rows, rows[1:])
    ):
        raise ValueError("layout must have ordered unique line numbers and pages")
    isolated = [re.compile(pattern, re.IGNORECASE) for pattern in config["isolated_line_patterns"]]
    starts = [re.compile(pattern, re.IGNORECASE) for pattern in config["new_block_patterns"]]
    result = {}
    for i in range(1, len(rows)):
        before, current = rows[i-1], rows[i]
        reasons = []
        if before.page != current.page:
            reasons.append("page_change")
        if any(pattern.search(row.text.strip()) for pattern in isolated for row in (before, current)):
            reasons.append("isolated_line")
        if any(pattern.search(current.text.strip()) for pattern in starts):
            reasons.append("new_block")
        if config["protect_multi_cell_rows"] and len(before.cells) > 1 and len(current.cells) > 1:
            left = min(before.cells, key=lambda cell: cell.x0)
            continuation = (config.get("allow_left_cell_continuation", False)
                            and left.x1 > left.x0
                            and all(left.x0 <= cell.x0 < cell.x1 <= left.x1 for cell in current.cells)
                            and all(cell is left or cell.x0 >= left.x1 for cell in before.cells))
            if not continuation:
                reasons.append("tabular_rows")
        if reasons:
            result[i] = reasons
    return result
