"""The installation's defaults: its own values of keys of the rule files (231, stage U, U4a; the owner's decisions of
2026-10-29).

Plain-language summary: the rule files hold the values the system decides with (a review band, the lines a quote
holds); until now only a release changed them. The installation may now keep its own value of a key a person may
set, a default, kept in versions as everything a person edits is (`jav/core/versions.py`): saved as a draft, made
active by the same rule as a process's own values (`configs/process_settings.json`, the owner's decision: as for the
processes), and set aside to bring the file's value back. A process's own value of the same key still goes over it.
A case keeps the defaults active at its start among its own values; work outside a case reads the active ones (the
long-running processes name this module to the config reader, `cfg.use_defaults`). A measurement reads the files.

- `editable()`: the keys a person may set, by id (`<file>.<key>`), each a `capabilities.RuleKey`: the capabilities'
  rule keys and (U4b) every value the rules view shows that its description (`configs/rule_help.json`, `edit`) lets a
  person set; `fixed()`: the values it shows that stay the file's, with why (a cost or a budget, the catalogue's
  structure, a number's format). A key that changes a paid request or a budget is never one.
- `propose(file, key, value, actor, note=)`, `activate(file, key, version, actor)`, `retire(file, key, actor)`.
- `active()`: the active defaults as a case keeps them ({file: {key: value}}, {file: {key: origin}}); `overlay_now()`:
  the same as an overlay for the config reader, read again at most every `REFRESH_S` seconds; `use()`: names it.
- `view()`: every key a person may set with its file value, its active default and its versions.
- `preview(file, key, value)` (U4c): what the value would have changed: every earlier decision that read the key and
  that no process's own value decided, its rule run again with it (nothing is written, no AI is asked).

Layer: application; it uses the capabilities' rule keys, the shared versioning and the process values' rule of who may
make a value active.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

from jav.app import capabilities
from jav.core import cfg, completion, identity, store, trace, versions
from jav.core.clock import utc_stamp as _now
from jav.core.user_messages import explained

__all__ = ["DefaultError", "DefaultStateError", "FIXED", "REFRESH_S", "UnknownDefault", "activate", "active", "editable",
           "fixed", "overlay_now", "preview", "propose", "register_options", "retire", "use", "view"]

REFRESH_S = 2.0  # how stale a process's view of the active defaults may be (a case reads them afresh at its start)
FIXED = ("cost", "structure", "format")  # U4b: why a value the rules view shows stays the file's
DEFAULT_SETTING = "default:"  # the origin a default's value carries in a case's values and the decision trace

store.register_schema("rule_defaults", """
-- 231 (U4a): the installation's own value of a rule key, every change a version of its own
CREATE TABLE IF NOT EXISTS rule_default_versions (
    default_id      TEXT NOT NULL,     -- <file>.<key>
    version         INTEGER NOT NULL,
    state           TEXT NOT NULL,     -- draft | active | superseded | retired (`jav/core/versions.py`)
    file            TEXT NOT NULL,
    key             TEXT NOT NULL,
    value           TEXT NOT NULL,     -- JSON
    note            TEXT,
    made_by         TEXT NOT NULL,
    made_by_id      TEXT,
    made_at         TEXT NOT NULL,
    activated_by    TEXT,
    activated_by_id TEXT,
    activated_at    TEXT,
    retired_by      TEXT,
    retired_by_id   TEXT,
    retired_at      TEXT,
    PRIMARY KEY (default_id, version)
);
CREATE INDEX IF NOT EXISTS ix_rule_default_versions_state ON rule_default_versions(state);
""")


class DefaultError(ValueError):
    """A value the key cannot take, or a key a person may not set."""


class UnknownDefault(versions.VersionNotFound):
    """No such key or version."""


class DefaultStateError(versions.VersionStateError):
    """A version not in a state that allows this."""


VERSIONS = versions.VersionTable("rule_default_versions", "default_id", UnknownDefault, DefaultStateError)


def editable() -> dict[str, capabilities.RuleKey]:
    """The keys a person may set for the installation, by id: the rule keys the capabilities let a process set and
    (U4b) the values the rules view shows that their description lets a person set."""
    out: dict[str, capabilities.RuleKey] = {}
    for cap in capabilities.catalogue():
        for rule in cap.rule_keys:
            out.setdefault(rule.id, rule)
    for rule in _declared()[0]:
        out.setdefault(rule.id, rule)
    return out


def fixed() -> dict[str, str]:
    """U4b: the values the rules view shows that stay the file's, by id, with why (one of `FIXED`)."""
    return dict(_declared()[1])


def _file_value(file: str, key: str) -> Any:
    with cfg.overlay(None):
        node: Any = cfg.load(file)
    for part in key.split("."):
        node = node[part]
    return node


def _members(value: Any) -> list[str]:
    """The option-like values a file value holds (a list's items, a map's values, or itself)."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, dict):
        return [str(v) for v in value.values()]
    return [str(value)]


def _doc_types() -> set[str]:
    from jav.ai import doc_types, typepack

    return set(typepack.keys()) | {t.key for t in doc_types.DOC_TYPES}


def _fields() -> set[str]:
    return set(cfg.load("field_labels")["fields"])


# U4b: where a declaration's options come from (`options_from`), by name: the shared ones here, a domain's registered
# by the domain (the email's routes and warning signs)
_OPTIONS: dict[str, Callable[[], Iterable[str]]] = {"doc_types": _doc_types, "fields": _fields}


def register_options(source: str, values: Callable[[], Iterable[str]]) -> None:
    """A domain names the values a default's options may come from (a second registration replaces the first)."""
    _OPTIONS[source] = values


def _options_from(source: str) -> set[str]:
    if source not in _OPTIONS:
        completion.complete("rule_default_options")
    if source not in _OPTIONS:
        raise ValueError(f"no registry of options {source!r}")
    return {str(v) for v in _OPTIONS[source]()}


def _declared() -> tuple[list[capabilities.RuleKey], list[tuple[str, str]]]:
    """U4b: the values the rules view shows, as keys a person may set (each with the options it may take, the file's
    own values among them) and as values that stay the file's ((id, why)); a capability's own key is the capability's."""
    with cfg.overlay(None):  # the files' values and the registries as released
        return _declared_from(cfg.load("rule_help")["points"])


def _declared_from(points: dict[str, Any]) -> tuple[list[capabilities.RuleKey], list[tuple[str, str]]]:
    keys: list[capabilities.RuleKey] = []
    kept: list[tuple[str, str]] = []
    seen: set[str] = set()
    for point in points.values():
        for v in point["values"]:
            file, key, edit = v["file"].removesuffix(".json"), v["key"], v.get("edit") or {}
            rid = f"{file}.{key}"
            if rid in seen or edit.get("kind") == "capability":
                continue
            seen.add(rid)
            if "fixed" in edit:
                kept.append((rid, str(edit["fixed"])))
                continue
            options: tuple[str, ...] = ()
            if edit["kind"] in ("choice", "set", "map"):
                found = set(edit.get("options") or ()) | (_options_from(edit["options_from"]) if "options_from" in edit else set())
                options = tuple(sorted(found | set(_members(_file_value(file, key)))))
            keys.append(capabilities.RuleKey(file, key, edit["kind"], v["label"], least=edit.get("least"),
                                             most=edit.get("most"), options=options))
    return keys, kept


def _rule(file: str, key: str) -> capabilities.RuleKey:
    rule = editable().get(f"{file}.{key}")
    if rule is None:
        raise explained(DefaultError, "the installation sets no default {{key}}", key=f"{file}.{key}")
    return rule


def _id(file: str, key: str) -> str:
    return f"{file}.{key}"


def active() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """The active defaults as a case keeps them: ({file: {key: value}}, {file: {key: {"setting": id, "version": n}}});
    a key no longer a person may set is left out."""
    keys = editable()
    values: dict[str, dict[str, Any]] = {}
    refs: dict[str, dict[str, Any]] = {}
    with store.connect() as c:
        rows = c.execute("SELECT default_id, version, file, key, value FROM rule_default_versions WHERE state=?",
                         (versions.ACTIVE,)).fetchall()
    for r in rows:
        if r["default_id"] in keys:
            values.setdefault(r["file"], {})[r["key"]] = json.loads(r["value"])
            refs.setdefault(r["file"], {})[r["key"]] = {"setting": DEFAULT_SETTING + r["default_id"],
                                                         "version": r["version"]}
    return values, refs


_lock = threading.Lock()
_seen: dict[str, Any] = {"at": 0.0, "overlay": None}


def overlay_now() -> cfg.Overlay | None:
    """The active defaults as an overlay over the files (None: none is active), read from the store again at most every
    `REFRESH_S` seconds; the same object while nothing changed, so the reader's applied copies are kept."""
    with _lock:
        if time.monotonic() - _seen["at"] < REFRESH_S:
            return _seen["overlay"]
        values, refs = active()
        old = _seen["overlay"]
        changed = (values, refs) != ((dict(old.values), dict(old.refs)) if old is not None else ({}, {}))
        _seen.update(at=time.monotonic(), overlay=(cfg.Overlay(values, refs) if values else None) if changed else old)
        return _seen["overlay"]


def _forget() -> None:
    with _lock:
        _seen["at"] = 0.0


def use() -> None:
    """A long-running process (the service, the worker) reads the installation's defaults over the files."""
    cfg.use_defaults(overlay_now)


def propose(file: str, key: str, value: Any, actor: identity.Who, *, note: str | None = None) -> dict[str, Any]:
    """A draft default of the key, refused (`DefaultError`, every problem named) when the key is not one a person may
    set or the value does not fit its declaration."""
    rule = _rule(file, key)
    if problems := rule.problems(value):
        raise explained(DefaultError, "the default cannot take this value: {{problems}}", problems="; ".join(problems))
    did = _id(file, key)
    with store.connect() as c:
        store.begin_immediate(c)
        try:
            version = int(VERSIONS.latest(c, did)["version"]) + 1
        except UnknownDefault:
            version = 1
        c.execute("INSERT INTO rule_default_versions(default_id, version, state, file, key, value, note, made_by,"
                  " made_by_id, made_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (did, version, versions.DRAFT, file, key, json.dumps(value), (note or "").strip() or None,
                   identity.name_of(actor), identity.id_of(actor), _now()))
    return view()


def activate(file: str, key: str, version: int, actor: identity.Who) -> dict[str, Any]:
    """The version becomes the installation's value of the key for the cases that start from now on and the work
    outside a case (checked again: the declaration may have changed since); `process_settings.SettingRefused` when the
    process values' rule does not let this person."""
    from jav.app import process_settings

    rule = _rule(file, key)
    with store.connect() as c:
        store.begin_immediate(c)
        row = VERSIONS.row(c, _id(file, key), version)
        if not process_settings.may_activate(actor, row["made_by"]):
            raise explained(process_settings.SettingRefused,
                            "by the rule of this installation, {{name}} may not make this value active",
                            name=identity.name_of(actor))
        if problems := rule.problems(json.loads(row["value"])):
            raise explained(DefaultError, "the default cannot take this value: {{problems}}", problems="; ".join(problems))
        VERSIONS.activate(c, _id(file, key), version, actor=actor)
    _forget()
    return view()


def retire(file: str, key: str, actor: identity.Who) -> dict[str, Any]:
    """The installation's own value is set aside: the file's value counts again for the cases that start from now on.
    Where the rule names owners only they may; otherwise anyone may (it brings back the released value)."""
    from jav.app import process_settings

    _rule(file, key)
    with store.connect() as c:
        store.begin_immediate(c)
        if VERSIONS.active(c, _id(file, key)) is None:
            raise explained(DefaultStateError, "the installation has no value of its own for {{key}}", key=_id(file, key))
        rule = process_settings.policy()
        if rule["activation"] == process_settings.OWNER and identity.name_of(actor) not in rule["owners"]:
            raise explained(process_settings.SettingRefused,
                            "by the rule of this installation, {{name}} may not make this value active",
                            name=identity.name_of(actor))
        VERSIONS.retire(c, _id(file, key), actor=actor)
    _forget()
    return view()


def _version(r: Any) -> dict[str, Any]:
    return {"version": r["version"], "state": r["state"], "value": json.loads(r["value"]), "note": r["note"],
            "made_by": r["made_by"], "made_at": r["made_at"], "activated_by": r["activated_by"],
            "activated_at": r["activated_at"]}


def view() -> dict[str, Any]:
    """Every key a person may set: its declaration, the file's value, the installation's active value (None: the
    file's counts) and its versions (newest first); and the rule of who may make a value active."""
    from jav.app import process_settings

    with store.connect() as c:
        rows = c.execute("SELECT * FROM rule_default_versions ORDER BY default_id, version DESC").fetchall()
    by_id: dict[str, list[Any]] = {}
    for r in rows:
        by_id.setdefault(r["default_id"], []).append(r)
    out = []
    for did, rule in sorted(editable().items()):
        own = by_id.get(did, [])
        current = next((r for r in own if r["state"] == versions.ACTIVE), None)
        out.append({"id": did, "file": rule.file, "key": rule.key, "kind": rule.kind, "what": rule.what,
                    "least": rule.least, "most": rule.most, "options": list(rule.options),
                    "file_value": rule.file_value(), "value": json.loads(current["value"]) if current else None,
                    "active": current["version"] if current else None, "versions": [_version(r) for r in own]})
    return {"keys": out, "policy": process_settings.policy()}


def _process_own(row: dict[str, Any], file: str, key: str) -> bool:
    """Whether a process's own value of the key decided the row (a default would not have reached it)."""
    name = trace.file_of(file)
    return any(e["file"] == name and any(v["key"] == key and not str(v.get("setting", "")).startswith(DEFAULT_SETTING)
                                         for v in e.get("process_values") or [])
               for e in row.get("rules") or [])


def preview(file: str, key: str, value: Any) -> dict[str, Any]:
    """U4c: what the default `value` of the key would have changed, from the decision trace: every decision that read
    the key, in a case or outside one, run again with the values it was made with and with `value` in place of the
    key's; a decision a process's own value of the key decided is counted apart (`covered`), as a default would not
    have reached it. Nothing is written, no AI is asked."""
    from jav.app import process_settings

    rule = _rule(file, key)
    if problems := rule.problems(value):
        raise explained(DefaultError, "the default cannot take this value: {{problems}}", problems="; ".join(problems))
    rows, covered = [], 0
    for row in trace.reading(trace.file_of(file), key):
        if _process_own(row, file, key):
            covered += 1
        else:
            rows.append(row)
    return {"id": rule.id, "value": value, "file_value": rule.file_value(), "covered": covered,
            **process_settings.replayed(rows, file, key, value)}
