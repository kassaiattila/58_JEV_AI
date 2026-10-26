"""Which of a quote case's steps go together (231, stage D0, D0-b; the reassessment of 2026-10-26, F04, P02).

Plain-language summary: a quote's proposal, draft, approval and letter belong to the case's step that makes them, so the
same capability may stand twice in one case (two price lists matched, two quotes composed) and each keeps its own. The
steps that go together are named by the pack: a line composition names the match it starts from (`from_step`), a letter
the composition whose approved version it answers (`from_step`); a step that names none takes the case's only step of
that kind. A package that is no case's has none of them (its quote is kept under an empty step, as before D0-b).

- `of(wp_id, step)`: the match, composition and letter steps that go with `step` (any of them; None: the case's first).
- `rebuild(conn, table, ddl, capability)`: an older store's quote table keyed by the case alone, rebuilt with the step
  of the case that used the capability (the store's schema change helper).
- `key(wp_id, step)`: the decision journal's key of a step's quote state (`<case>:<step>`).

Layer: application operation of the quotes domain over the process runtime's view of a case's pack.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass

MATCH, COMPOSE, LETTER = "catalogue_match", "line_draft", "letter_draft"
NONE = ""  # the step of a quote kept by a package that is no case's


@dataclass(frozen=True)
class Steps:
    """The steps of a case that go together: its match, its line composition and its letter ("" when it has none)."""

    match: str = NONE
    compose: str = NONE
    letter: str = NONE

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _steps(wp_id: str) -> list[tuple[str, str, str | None]]:
    """(step id, capability name, the step it names) of the case's pack, in its order; [] for no case."""
    from jav.app import process_packs, process_runtime  # lazy: the process runtime reads the domains' capabilities

    try:
        pack = process_runtime.pack_for(wp_id)
    except (KeyError, process_packs.PackError):
        return []
    if pack is None:
        return []
    return [(s.id, s.uses.split("@", 1)[0], s.params.get("from_step")) for s in pack.steps]


def of(wp_id: str, step: str | None = None) -> Steps:
    """The match, composition and letter steps of the case that go with `step` (a match, composition or letter step;
    None or another step: the case's first match and what goes with it)."""
    steps = _steps(wp_id)
    kind = {sid: cap for sid, cap, _ in steps}
    names = {sid: ref for sid, _, ref in steps}

    def first(cap: str) -> str:
        return next((sid for sid, c, _ in steps if c == cap), NONE)

    def naming(cap: str, source: str) -> str:
        """The step of `cap` that names `source`, else the first of `cap` that names none."""
        named = [sid for sid, c, ref in steps if c == cap and ref == source]
        free = [sid for sid, c, ref in steps if c == cap and not ref]
        return (named or free or [NONE])[0]

    cap = kind.get(step or NONE)
    if cap == MATCH and step:
        compose = naming(COMPOSE, step)
        return Steps(step, compose, naming(LETTER, compose) if compose else NONE)
    if cap == COMPOSE and step:
        return Steps(names[step] or first(MATCH), step, naming(LETTER, step))
    if cap == LETTER and step:
        compose = names[step] or first(COMPOSE)
        return Steps((names.get(compose) or first(MATCH)) if compose else first(MATCH), compose, step)
    match = first(MATCH)
    compose = (naming(COMPOSE, match) if match else NONE) or first(COMPOSE)
    return Steps(match, compose, (naming(LETTER, compose) if compose else NONE) or first(LETTER))


def rebuild(conn: sqlite3.Connection, table: str, ddl: str, capability: str) -> None:
    """D0-b, the store's schema change helper: an older store's `table` (keyed by the case alone, no `step_id`) rebuilt
    by `ddl` (its new layout), each row under the step of its case that uses `capability` ("" for a package that is no
    case's); in one write transaction checked again inside it, so two processes starting at once rebuild it once."""
    def older() -> bool:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        return bool(cols) and "step_id" not in cols

    def step_of(wp_id: str) -> str:
        """The case's first step of `capability`, by the definition it started with (the core's own read)."""
        from jav.core.process import cases

        row = cases.find_case_in(conn, wp_id)
        if row is None:
            return NONE
        kind = f"cap.{capability}.v"
        return next((s.id for s in cases.definition_of(row).steps if s.kind.startswith(kind)), NONE)

    if not older():
        return
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if older():
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
            conn.execute(f"DROP TABLE IF EXISTS {table}_d0")
            conn.execute(ddl.replace(f"CREATE TABLE IF NOT EXISTS {table} (", f"CREATE TABLE {table}_d0 (", 1))
            conn.executemany(f"INSERT INTO {table}_d0({', '.join(cols)}, step_id) VALUES ({', '.join('?' * (len(cols) + 1))})",
                             [(*tuple(r), step_of(r["workpackage_id"])) for r in rows])
            conn.execute(f"DROP TABLE {table}")
            conn.execute(f"ALTER TABLE {table}_d0 RENAME TO {table}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def key(wp_id: str, step: str) -> str:
    """The decision journal's key of a step's quote state (the package's alone when the step is none)."""
    return f"{wp_id}:{step}" if step else wp_id


__all__ = ["COMPOSE", "LETTER", "MATCH", "NONE", "Steps", "key", "of", "rebuild"]
