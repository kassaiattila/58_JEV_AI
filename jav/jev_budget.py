"""Kérés-méret keret közös része a Jev-hívási helyekhez (S-kar választó és G-kar ellenőrző): egy kérést a hívási hely
`request_char_budget` (karakter) keretére illesztünk, és ha a szerver ennek ellenére `max_tokens_exceeded` hibát ad,
EGYSZER újrapróbáljuk szűkebb kerettel.

Miért kell: a karakter-keret csak becslés a token-korlátra (a magyar szöveg ~2,5 karakter / token, de ez a szövegforrástól
függ - az Azure DI szövege ugyanannyi karakterből több tokent adott, mint a tesseracté), ezért a keret alatt is jöhet
túllépés. A második próbálkozás a keret `RETRY_BUDGET_FACTOR`-szorosával fut; ha az sem fér be, a kivétel a flow-hoz jut
(`jev_unavailable:<ok>` review-ok, a flow nem dől el). Két hívási hely írta le kézzel ugyanezt (CLAUDE.md §4: ekkor lesz
keret-modul). A csökkentés mindig látszik a nyers futásban (`JevCall.state_chars`), a ledgerben a sikertelen első hívás is.
"""

from __future__ import annotations

from typing import Any, Callable

from jav.adapters.jev import JevAdapter, JevUnavailableError

RETRY_BUDGET_FACTOR = 0.6  # a második (egyetlen) újrapróbálás kerete az eredeti hányada
TOKEN_LIMIT_MARK = "max_tokens_exceeded"  # a szerver hiba-típusa a JevUnavailableError.reason-ben

Fit = Callable[[int | None], tuple[dict[str, Any], dict[str, Any]]]
Size = Callable[[dict[str, Any], dict[str, Any]], int]


def ask_within_budget(
    jev: JevAdapter, request_id: str, fit: Fit, budget: int | None, size: Size, **ask_kw: Any
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """`fit(budget)` → (state, questions) a keretre illesztve; `jev.ask(...)`; token-hibánál egyszer `fit(szűkebb)`, ahol a
    szűkebb keret az ELKÜLDÖTT kérés méretének (`size`, a hívási hely saját mérése) és a keretnek a kisebbike × 0,6 - így a
    tág keret alatt is tényleg kisebb lesz a második kérés. Visszatér: (a hívás eredménye, az elküldött state, az elküldött
    kérdések) - a választ a ténylegesen elküldött kérdéskészlettel kell kiolvasni. Keret nélkül (`budget=None`) nincs
    újrapróbálás: nincs mit szűkíteni."""
    state, questions = fit(budget)
    try:
        return jev.ask(request_id, state, questions, **ask_kw), state, questions
    except JevUnavailableError as exc:
        if budget is None or TOKEN_LIMIT_MARK not in (exc.reason or ""):
            raise
        tight = max(1, int(min(budget, size(state, questions)) * RETRY_BUDGET_FACTOR))
        state, questions = fit(tight)
        return jev.ask(request_id, state, questions, **ask_kw), state, questions


def line_numbers(evidence: dict[str, list[str]]) -> set[int]:
    """Az evidencia-sorok (`Lnn: szöveg`) 1-alapú sorszámai."""
    out: set[int] = set()
    for hits in evidence.values():
        for h in hits:
            if h.startswith("L") and ":" in h:
                head = h[1 : h.index(":")]
                if head.isdigit():
                    out.add(int(head))
    return out
