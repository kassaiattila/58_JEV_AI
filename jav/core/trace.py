"""218 (plan G-process-core P3b): the decision trace - which rule decided, with what, in which version.

Plain-language summary: a machine decision (this document is an invoice, this field waits for a person, this step's
estimate is over its budget) is recorded in one shared trace, in the same transaction as the decision's result: the
decision point, what it was about, what the rule read (probabilities, differences, amounts), what it decided, and which
rule files and keys it used, each with its version and content fingerprint, together with the process's calculation
snapshot (`jav.core.rulebook`). So years later it can be told which rule of which version decided, with what input, and
a changed rule can be tried on the stored inputs without processing anything again (plan P3d).

- `register(point)`: a decision point: its code, what it decides and what it is not for, its owner module, the rule
  files it reads (a pattern names a family, such as the type packs: `types/*.json`) and its rule: a pure function of
  the stored inputs that gives the stored outcome (`replay`).
- `record_in(c, point, subject=, inputs=, outcome=, keys=, ...)`: one trace row in the caller's write transaction.
- `rows(...)`, `replay(row)`: reading the trace back, and the rule run again on a row's inputs; `reading(file, key)`:
  the rows whose decision read one rule key (231 B3).

231 (plan stage B, B3): a decision made while a case's own rule values lay over the files (`cfg.overlay`) records them
beside each file it read (`process_values`: the key, the value, the stored setting and its version), and `replay` runs
the rule with them over the files again. Stage D0 (D0-e): a file the case read as it started (its kept copy, not the
file this process holds) is recorded with the kept copy's version and fingerprint and `kept: true`, and `replay` reads
that copy again. Stage D (D-a): the content it read (the kept copy with the keys added since) is stored by its
fingerprint (`effective_sha256`), and `replay` reads exactly that.

A person's decision has its own journal (`jav.core.decisions`); this trace is the machine's. Measurements and replays
write into their own copy of the store, so they never grow the live trace.

Layer: shared core; it imports only the store, the config loader and the calculation snapshot. The owners register their points.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from jav.core import cfg, rulebook, store
from jav.core.clock import utc_stamp as _now

store.register_schema("trace", """
CREATE TABLE IF NOT EXISTS decision_trace (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    point        TEXT NOT NULL,     -- a registered decision point (`register`)
    subject_kind TEXT NOT NULL,     -- what it decided about: a document, a datapoint, an email, a workflow step ...
    subject_id   TEXT NOT NULL,
    run_id       TEXT,              -- the run it was made in
    case_id      TEXT,              -- the case it was made in
    inputs       TEXT NOT NULL,     -- JSON: what the rule read
    inputs_sha   TEXT NOT NULL,
    outcome      TEXT NOT NULL,     -- JSON: what it decided (the rule's value for the inputs)
    rules        TEXT NOT NULL,     -- JSON: [{file, version, sha256, keys}] the rule files and keys it used
    snapshot_id  TEXT NOT NULL,     -- the calculation snapshot of the process that decided
    at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_decision_trace_subject ON decision_trace(subject_kind, subject_id, id);
CREATE INDEX IF NOT EXISTS ix_decision_trace_point ON decision_trace(point, id);
CREATE INDEX IF NOT EXISTS ix_decision_trace_run ON decision_trace(run_id);
""")


class UnknownPoint(ValueError):
    """No module registered this decision point, or it names a rule file the point does not read."""


@dataclass(frozen=True)
class Point:
    """A machine decision point. `rule(inputs)` is the pure function whose value for the stored inputs is the stored
    outcome; `files` are the rule files under `configs/` it may read, by path or by a pattern (`fnmatch`)."""

    code: str
    what: str
    not_for: str
    owner: str
    files: tuple[str, ...]
    rule: Callable[[Mapping[str, Any]], Any]


_POINTS: dict[str, Point] = {}


def register(point: Point) -> None:
    """The same point again adds nothing; another one of the same code is an error."""
    known = _POINTS.get(point.code)
    if known is not None and known != point:
        raise ValueError(f"decision point {point.code!r} is registered already by {known.owner}")
    _POINTS[point.code] = point


def points() -> list[Point]:
    """In the order they were registered."""
    return list(_POINTS.values())


def point(code: str) -> Point:
    try:
        return _POINTS[code]
    except KeyError:
        raise UnknownPoint(f"no module registered the decision point {code!r}") from None


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


_FOLDERS = {"callsite": "callsites", "type": "types", "process": "processes"}  # as `cfg.path_of` places a config name


def file_of(name: str) -> str:
    """A config name's file under `configs/`, as the trace names it (`callsite:x` -> `callsites/x.json`)."""
    prefix, _, rest = name.partition(":")
    return f"{_FOLDERS[prefix]}/{rest}.json" if rest and prefix in _FOLDERS else f"{name}.json"


def _process_values() -> dict[str, list[dict[str, Any]]]:
    """231 (B3): the case's own values lying over the files now, by rule file."""
    over = cfg.current_overlay()
    if over is None:
        return {}
    return {file_of(name): [{"key": key, "value": value, **(over.refs.get(name, {}).get(key) or {})}
                             for key, value in sorted(values.items())] for name, values in over.values.items()}


def _rules(p: Point, keys: Mapping[str, Iterable[str]], snapshot: rulebook.Snapshot,
           c: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    if unknown := sorted(name for name in keys if not any(fnmatch.fnmatchcase(name, f) for f in p.files)):
        raise UnknownPoint(f"the decision point {p.code} reads no rule file {unknown}")
    own = _process_values()
    over = cfg.current_overlay()
    out = []
    for name in sorted(keys):
        found = snapshot.files.get(name)
        entry = {"file": name, "version": found.version if found else None, "sha256": found.sha256 if found else None,
                 "keys": sorted(set(keys[name]))}
        if over is not None and (kept := over.base.get(_name_of(name))) is not None:  # D0-e: the case's kept copy
            entry.update(version=kept.version, sha256=kept.sha256, kept=True)
            if c is not None:  # D-a: what it read, kept for its replay
                read = json.dumps(kept.data, ensure_ascii=False, sort_keys=True).encode("utf-8")
                entry["effective_sha256"] = rulebook.store_content_in(c, name + rulebook.EFFECTIVE, kept.version, read)
        if name in own:
            entry["process_values"] = own[name]
        out.append(entry)
    return out


def _name_of(file: str) -> str:
    """The config name of a file the trace names (`callsites/x.json` -> `callsite:x`)."""
    folder, _, rest = file.removesuffix(".json").partition("/")
    prefixes = {v: k for k, v in _FOLDERS.items()}
    return f"{prefixes[folder]}:{rest}" if rest and folder in prefixes else folder


def recorded_overlay(row: Mapping[str, Any]) -> cfg.Overlay | None:
    """231 (B3): the case's own values a row's decision was made with, as an overlay (None: the files alone); D0-e: and
    the kept copies of the files it read as the case started (from the stored contents)."""
    values: dict[str, dict[str, Any]] = {}
    refs: dict[str, dict[str, dict[str, Any]]] = {}
    base: dict[str, cfg.Kept] = {}
    for entry in row.get("rules") or []:
        name = _name_of(entry["file"])
        for v in entry.get("process_values") or []:
            values.setdefault(name, {})[v["key"]] = v["value"]
            refs.setdefault(name, {})[v["key"]] = {k: v[k] for k in ("setting", "version") if k in v}
        if entry.get("kept") and (kept := _kept_copy(name, entry["sha256"], entry.get("version"),
                                                     entry.get("effective_sha256"))) is not None:
            base[name] = kept
    return cfg.Overlay(values, refs, base=base) if values or base else None


def _kept_copy(name: str, sha256: str, version: str | None, effective: str | None = None) -> cfg.Kept | None:
    """D0-e: a file's kept copy by its stored content, with the keys the file gained since (None: not stored); D-a: the
    content the decision read, where it was stored (`effective`)."""
    with store.connect() as c:
        if effective is not None and (read := rulebook.content_in(c, effective)) is not None:
            return cfg.Kept(json.loads(read), sha256, version)
        content = rulebook.content_in(c, sha256)
    if content is None:
        return None
    with cfg.overlay(None):
        newer = cfg.load(name)
    return cfg.Kept(cfg.filled(json.loads(content), newer), sha256, version)


def record_in(c: sqlite3.Connection, code: str, *, subject: tuple[str, str], inputs: Mapping[str, Any], outcome: Any,
              keys: Mapping[str, Iterable[str]], run_id: str | None = None, case_id: str | None = None) -> int:
    """One trace row in the caller's write transaction, so the decision's result and its trace are written together or
    not at all. `keys`: the rule keys it used, by rule file (each one the point reads). Returns the row's id."""
    p = point(code)
    snapshot = rulebook.current()
    text = _json(dict(inputs))
    cur = c.execute(
        "INSERT INTO decision_trace(point, subject_kind, subject_id, run_id, case_id, inputs, inputs_sha, outcome, rules,"
        " snapshot_id, at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (code, subject[0], subject[1], run_id, case_id, text, hashlib.sha256(text.encode("utf-8")).hexdigest(),
         _json(outcome), _json(_rules(p, keys, snapshot, c)), rulebook.store_in(c, snapshot), _now()))
    return int(cur.lastrowid)


def _row(r: sqlite3.Row) -> dict[str, Any]:
    out = dict(r)
    for name in ("inputs", "outcome", "rules"):
        out[name] = json.loads(out[name])
    return out


def reading(file: str, key: str) -> list[dict[str, Any]]:
    """231 (B3): the trace rows whose decision read rule `key` of `file` (a path under `configs/`), oldest first."""
    with store.connect() as c:
        found = [_row(r) for r in c.execute("SELECT * FROM decision_trace WHERE instr(rules, ?) > 0 ORDER BY id",
                                            (_json({"file": file})[1:-1],))]
    return [r for r in found if any(e["file"] == file and key in e["keys"] for e in r["rules"])]


def rows(*, point: str | None = None, subject: tuple[str, str] | None = None, run_id: str | None = None,
         case_id: str | None = None, last: int | None = None) -> list[dict[str, Any]]:
    """The trace rows matching every filter given, oldest first (with `last`: only the latest that many)."""
    where, args = [], []
    for column, value in (("point", point), ("run_id", run_id), ("case_id", case_id)):
        if value is not None:
            where.append(f"{column}=?")
            args.append(value)
    if subject is not None:
        where.append("subject_kind=? AND subject_id=?")
        args += list(subject)
    sql = "SELECT * FROM decision_trace" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY id DESC"
    if last is not None:
        sql += f" LIMIT {int(last)}"
    with store.connect() as c:
        return [_row(r) for r in reversed(c.execute(sql, args).fetchall())]


def replay(row: Mapping[str, Any], *, over: cfg.Overlay | None = None) -> Any:
    """The point's rule run again on the row's stored inputs (its value equals the stored outcome while the rule's code
    is the same); 231 (B3): with the case's own values it was made with over the files, or with `over` instead."""
    with cfg.overlay(over if over is not None else recorded_overlay(row)):
        return json.loads(_json(point(row["point"]).rule(row["inputs"])))
