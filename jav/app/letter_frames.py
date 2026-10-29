"""The letter frames of the shared library, edited as versions (231, stage U, U3f; the owner's decision of 2026-10-28).

Plain-language summary: a letter that goes with a printed document (an insurance offer's covering letter, a quote's
reply) is written from a frame: its subject, its greeting, its paragraphs and its closing, with markers such as
`{{total}}` that code fills in from the document. The frames come with the system in rule files; a person may now
change a frame's text. A changed frame is kept in versions as everything a person edits is (`jav/core/versions.py`):
saved as a draft, made active by the same rule as a process's own values (`configs/process_settings.json`), and set
aside to bring the file's text back. A case keeps the version active when it starts (its own rule values,
`capabilities.RULES`): a change reaches the cases started after it.

- `FrameKind`, `register_kind(kind)`: a kind of frame (the insurance letters' `letter_frame`, the quote's
  `quote_letter_frame`), registered by the module that writes its letters: the rule file and key that hold its frames,
  the fields a person edits and the outputs whose values its markers may name.
- `listing()`: every kind with its frames, each with the file's text, the text in effect and its versions.
- `propose(kind, ident, values, actor, note=)`: a draft of the frame with the fields `values` changes, refused
  (`FrameError`, every problem named) when a field is empty or too long or a marker names no value of the documents.
- `activate(kind, ident, version, actor)`, `retire(kind, ident, actor)`: a version made the frame's text, or the file's
  brought back.
- `in_effect(kind, ident)`: the frame's active version as a case keeps it (the rule file, the key, the text and where
  it came from), or None while the file's text counts; `config_frames(config, prefix)`: a kind's frames as a rule file
  holds them.

Layer: application, the shared library; it uses the shared versioning, the output contract and the rule files.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from jav.app.outputs import contract, markers
from jav.core import cfg, identity, store, versions
from jav.core.clock import utc_stamp as _now
from jav.core.user_messages import explained

__all__ = ["FIELD_FORMS", "LINE", "PARAGRAPHS", "TEXT", "FrameError", "FrameField", "FrameKind", "FrameStateError", "UnknownFrame", "activate",
           "config_frames", "in_effect", "kinds", "listing", "propose", "register_kind", "retire"]

LINE, TEXT, PARAGRAPHS = "line", "text", "paragraphs"
FIELD_FORMS = (LINE, TEXT, PARAGRAPHS)
LINE_CHARS, TEXT_CHARS = 300, 5000
_VALUE_MARKER = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*$")

store.register_schema("letter_frames", """
-- 231 (U3f): a letter frame's text as a person changed it, every change a version of its own
CREATE TABLE IF NOT EXISTS letter_frame_versions (
    frame_id        TEXT NOT NULL,     -- <kind>/<ident>
    version         INTEGER NOT NULL,
    state           TEXT NOT NULL,     -- draft | active | superseded | retired (`jav/core/versions.py`)
    kind            TEXT NOT NULL,
    ident           TEXT NOT NULL,
    content         TEXT NOT NULL,     -- JSON: the whole frame
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
    PRIMARY KEY (frame_id, version)
);
CREATE INDEX IF NOT EXISTS ix_letter_frame_versions_state ON letter_frame_versions(kind, state);
""")


class FrameError(ValueError):
    """A frame text that cannot be saved or made active (an empty or too long field, a marker naming no value)."""


class UnknownFrame(versions.VersionNotFound):
    """No such kind, frame or version."""


class FrameStateError(versions.VersionStateError):
    """A version not in a state that allows this."""


VERSIONS = versions.VersionTable("letter_frame_versions", "frame_id", UnknownFrame, FrameStateError)


@dataclass(frozen=True)
class FrameField:
    """A field of a frame a person edits: its dotted `path` in the frame, its `label` (an English source text the
    interface translates), its `form` (a line, a text, or paragraphs as a list of texts) and the `group` it stands
    under (a language), if any."""

    path: str
    label: str
    form: str = LINE
    group: str | None = None


@dataclass(frozen=True)
class FrameKind:
    """A kind of frame: `kind` its shared library kind (`process_settings.used_by`), `title` and `what` its name and
    one sentence (English source texts), its frames in the rule file `config` under `prefix` (the frame `x` at the key
    `prefix + x`), `frames()` the file's frames by id, the `fields` a person edits, and `outputs()` the outputs whose
    values its markers may name."""

    kind: str
    title: str
    what: str
    config: str
    prefix: str
    frames: Callable[[], Mapping[str, Mapping[str, Any]]]
    fields: tuple[FrameField, ...]
    outputs: Callable[[], tuple[str, ...]]
    module: str = ""

    def key(self, ident: str) -> str:
        return f"{self.prefix}{ident}"


_KINDS: dict[str, FrameKind] = {}


def register_kind(kind: FrameKind) -> None:
    """A module that writes letters registers its kind of frame (a second registration of the same kind replaces it)."""
    if bad := [f.path for f in kind.fields if f.form not in FIELD_FORMS]:
        raise ValueError(f"letter frame kind {kind.kind}: unknown field form in {bad}")
    _KINDS[kind.kind] = kind


def kinds() -> list[FrameKind]:
    return list(_KINDS.values())


def _kind(kind: str) -> FrameKind:
    try:
        return _KINDS[kind]
    except KeyError:
        raise UnknownFrame(f"no kind of letter frame {kind!r}") from None


def _file_frame(k: FrameKind, ident: str) -> dict[str, Any]:
    frames = k.frames()
    if ident not in frames:
        raise explained(UnknownFrame, "no letter frame {{frame}}", frame=ident)
    return copy.deepcopy(dict(frames[ident]))


def _id(kind: str, ident: str) -> str:
    return f"{kind}/{ident}"


def _get(frame: Mapping[str, Any], path: str) -> Any:
    node: Any = frame
    for part in path.split("."):
        node = node.get(part) if isinstance(node, Mapping) else None
    return node


def _put(frame: dict[str, Any], path: str, value: Any) -> None:
    *parents, last = path.split(".")
    node = frame
    for part in parents:
        node = node.setdefault(part, {})
    node[last] = value


def _allowed(k: FrameKind) -> set[str]:
    return {key for output in k.outputs() for key in contract.spec(output)["values"]}


def _marker_problems(text: str, allowed: set[str]) -> list[str]:
    found = markers.ANY.findall(text)
    out = [f"{{{{{m}}}}} is not a marker" for m in found if not _VALUE_MARKER.match(m)]
    out += [f"{{{{{m.strip()}}}}} names no value of the document" for m in found
            if _VALUE_MARKER.match(m) and m.strip() not in allowed]
    if "{{" in markers.ANY.sub("", text) or "}}" in markers.ANY.sub("", text):
        out.append("a marker is not closed")
    return out


def _problems(k: FrameKind, frame: Mapping[str, Any]) -> list[str]:
    """What keeps the frame from being saved: each field filled, not too long, a line on one line, and each marker a
    value of the documents its letters go with."""
    allowed, out = _allowed(k), []
    for f in k.fields:
        value = _get(frame, f.path)
        texts = value if f.form == PARAGRAPHS and isinstance(value, list) else [value]
        if f.form == PARAGRAPHS and (not isinstance(value, list) or not value):
            out.append(f"{f.path}: at least one paragraph is needed")
            continue
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                out.append(f"{f.path}: it cannot be empty")
                continue
            if f.form == LINE and ("\n" in text or len(text) > LINE_CHARS):
                out.append(f"{f.path}: one line of at most {LINE_CHARS} characters")
            elif len(text) > TEXT_CHARS:
                out.append(f"{f.path}: at most {TEXT_CHARS} characters")
            out += [f"{f.path}: {p}" for p in _marker_problems(text, allowed)]
    return out


def _clean(form: str, value: Any) -> Any:
    if form == PARAGRAPHS:
        if not isinstance(value, list):
            return value
        return [p.strip() for p in value if isinstance(p, str) and p.strip()]
    return value.strip() if isinstance(value, str) else value


def _active_row(c: Any, kind: str, ident: str) -> Any:
    return VERSIONS.active(c, _id(kind, ident))


def in_effect(kind: str, ident: str) -> tuple[str, str, dict[str, Any], dict[str, Any]] | None:
    """The frame's active version as a case keeps it: (its rule file, its key there, the text, {"setting": its id,
    "version": n}); None while the file's text counts, or for a kind or frame nobody registered."""
    k = _KINDS.get(kind)
    if k is None or ident not in k.frames():
        return None
    with store.connect() as c:
        row = _active_row(c, kind, ident)
    if row is None:
        return None
    return k.config, k.key(ident), json.loads(row["content"]), {"setting": row["frame_id"], "version": row["version"]}


def _version(r: Any) -> dict[str, Any]:
    return {"version": r["version"], "state": r["state"], "content": json.loads(r["content"]), "note": r["note"],
            "made_by": r["made_by"], "made_at": r["made_at"], "activated_by": r["activated_by"],
            "activated_at": r["activated_at"]}


def _markers(k: FrameKind, frame: Mapping[str, Any]) -> list[str]:
    seen: dict[str, None] = {}
    for f in k.fields:
        value = _get(frame, f.path)
        for text in value if isinstance(value, list) else [value]:
            for m in markers.ANY.findall(text if isinstance(text, str) else ""):
                seen[m.strip()] = None
    return list(seen)


def listing() -> dict[str, Any]:
    """Every kind with its frames: each frame's file text, the text in effect (its active version's, else the file's),
    the markers it uses and its versions (newest first); and the rule of who may make a version active."""
    from jav.app import process_settings

    out = []
    with store.connect() as c:
        for k in kinds():
            rows = c.execute("SELECT * FROM letter_frame_versions WHERE kind=? ORDER BY ident, version DESC",
                             (k.kind,)).fetchall()
            by_ident: dict[str, list[Any]] = {}
            for r in rows:
                by_ident.setdefault(r["ident"], []).append(r)
            frames = []
            for ident, file_frame in k.frames().items():
                own = by_ident.get(ident, [])
                active = next((r for r in own if r["state"] == versions.ACTIVE), None)
                content = json.loads(active["content"]) if active else dict(file_frame)
                frames.append({"ident": ident, "file": dict(file_frame), "content": content,
                               "active": active["version"] if active else None, "markers": _markers(k, content),
                               "versions": [_version(r) for r in own]})
            out.append({"kind": k.kind, "title": k.title, "what": k.what, "frames": frames,
                        "fields": [{"path": f.path, "label": f.label, "form": f.form, "group": f.group} for f in k.fields],
                        "markers": sorted(_allowed(k))})
    return {"kinds": out, "policy": process_settings.policy()}


def propose(kind: str, ident: str, values: Mapping[str, Any], actor: identity.Who, *, note: str | None = None) -> dict[str, Any]:
    """A draft of the frame: the text in effect with the fields `values` names changed; refused when a field is not
    one a person edits, when nothing changed, or when the text has a problem (each one named)."""
    k = _kind(kind)
    fields = {f.path: f for f in k.fields}
    if unknown := sorted(set(values) - set(fields)):
        raise explained(FrameError, "a letter frame has no field {{fields}}", fields=", ".join(unknown))
    current = in_effect(kind, ident)
    frame = copy.deepcopy(current[2]) if current else _file_frame(k, ident)
    before = copy.deepcopy(frame)
    for path, value in values.items():
        _put(frame, path, _clean(fields[path].form, value))
    if frame == before:
        raise explained(FrameError, "the letter frame is unchanged")
    if problems := _problems(k, frame):
        raise explained(FrameError, "the letter frame cannot be saved: {{problems}}", problems="; ".join(problems))
    fid = _id(kind, ident)
    with store.connect() as c:
        store.begin_immediate(c)
        try:
            version = int(VERSIONS.latest(c, fid)["version"]) + 1
        except UnknownFrame:
            version = 1
        c.execute("INSERT INTO letter_frame_versions(frame_id, version, state, kind, ident, content, note, made_by,"
                  " made_by_id, made_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (fid, version, versions.DRAFT, kind, ident, json.dumps(frame, ensure_ascii=False),
                   (note or "").strip() or None, identity.name_of(actor), identity.id_of(actor), _now()))
    return listing()


def activate(kind: str, ident: str, version: int, actor: identity.Who) -> dict[str, Any]:
    """The version becomes the frame's text for the cases that start from now on (checked again: the documents' values
    may have changed since); `process_settings.SettingRefused` when the rule does not let this person."""
    from jav.app import process_settings

    k = _kind(kind)
    _file_frame(k, ident)
    with store.connect() as c:
        store.begin_immediate(c)
        row = VERSIONS.row(c, _id(kind, ident), version)
        if not process_settings.may_activate(actor, row["made_by"]):
            raise explained(process_settings.SettingRefused,
                            "by the rule of this installation, {{name}} may not make this value active",
                            name=identity.name_of(actor))
        if problems := _problems(k, json.loads(row["content"])):
            raise explained(FrameError, "the letter frame cannot be saved: {{problems}}", problems="; ".join(problems))
        VERSIONS.activate(c, _id(kind, ident), version, actor=actor)
    return listing()


def retire(kind: str, ident: str, actor: identity.Who) -> dict[str, Any]:
    """The frame's own text is set aside: the file's counts again for the cases that start from now on. Where the rule
    names owners only they may; otherwise anyone may (it brings back the text the system came with)."""
    from jav.app import process_settings

    _file_frame(_kind(kind), ident)
    with store.connect() as c:
        store.begin_immediate(c)
        if _active_row(c, kind, ident) is None:
            raise explained(FrameStateError, "the letter frame {{frame}} has no text of its own", frame=ident)
        rule = process_settings.policy()
        if rule["activation"] == process_settings.OWNER and identity.name_of(actor) not in rule["owners"]:
            raise explained(process_settings.SettingRefused,
                            "by the rule of this installation, {{name}} may not make this value active",
                            name=identity.name_of(actor))
        VERSIONS.retire(c, _id(kind, ident), actor=actor)
    return listing()


def config_frames(config: str, prefix: str) -> Callable[[], dict[str, Any]]:
    """The frames a rule file holds under `prefix` (a dotted key ending in a dot), as the file has them now."""
    def frames() -> dict[str, Any]:
        node: Any = cfg.load(config)
        for part in prefix.rstrip(".").split(".") if prefix else ():
            node = node.get(part) if isinstance(node, dict) else None
        return dict(node or {})

    return frames
