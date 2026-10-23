"""218 (plan G-process-core P3e): the read-only view of the rules - what a rule decides, with which values, in which
version, and how many decisions it has made.

Plain-language summary: Settings › Rules lists every machine decision point of the decision trace (`jav.core.trace`):
what it decides and what it is not for, in plain words (`configs/rule_help.json`, English source the interface
translates), the rule values it decides with, read from the rule files the running process loaded, which version of
each rule file is in use and since when (`jav.core.rulebook`), and how many decisions the trace holds, how many of them
were made with the rule files in use now, and the latest. It only reads: nothing here changes a rule, and the texts are
kept apart from the rule files, so their fingerprints and the AI requests stay the same. Price lists and output
templates, which a person edits, have their own pages.

- `rows()`: one row per decision point, in the order of the areas, for the `rules` dataset (`jav.app.datasets`).
- `resolve(data, key)`: the value at a rule key as the trace names it (`bands.default.noul_no_max`,
  `band_for.invoice.pick`, `recipes[processing].max_item_usd`); a key that is not there is a `KeyError`.

Layer: application operation (read-only); it reads the core's trace, calculation snapshot, config loader and store,
and the datasets' label sets.
"""

from __future__ import annotations

import fnmatch
import json
import re
from typing import Any

from jav.ai import typepack
from jav.core import cfg, rulebook, store, trace

# the formats of a shown value (`configs/rule_help.json`) and the form each is served in: a number the interface sets
# as a percentage or percentage points, yes or no, a number, a label or labels (the interface translates them), an
# email's next step or the next step of each intent (the interface names a step by its code, as everywhere), or amounts
# by provider
FORMATS = {"percent": "percent", "points": "points", "yes_no": "yes_no", "number": "number", "doc_types": "names",
           "fields": "names", "labels": "names", "provider": "name", "route": "route", "intent_routes": "routes",
           "usd_by_provider": "usd"}
COMPARED = frozenset({"percent", "points"})  # a threshold's label reads on into its value: "... below 60 %"
_FOLDERS = {"types": "type", "callsites": "callsite"}  # a rule file under a folder of `configs/` by its loader name
_ITEM = re.compile(r"([A-Za-z_]\w*)\[([^\]]+)\]")  # a list's item by its id: `recipes[processing]`
_MISSING = object()


def config_of(file: str) -> dict[str, Any]:
    """The loaded rule file by its path under `configs/` (`policy.json`, `types/invoice_hu.json`)."""
    folder, _, name = file.removesuffix(".json").rpartition("/")
    return cfg.load(f"{_FOLDERS[folder]}:{name}" if folder else name)


def resolve(data: Any, key: str) -> Any:
    """The value at a rule key. A part of the key may itself contain dots (`band_for.invoice.pick`): at each level the
    longest name present is taken."""
    node, rest = data, key
    while rest:
        item = _ITEM.match(rest)
        if item and isinstance(node, dict) and isinstance(node.get(item[1]), list):
            node = next((x for x in node[item[1]] if isinstance(x, dict) and x.get("id") == item[2]), _MISSING)
            if node is _MISSING:
                raise KeyError(key)
            rest = rest[item.end():].removeprefix(".")
            continue
        parts = rest.split(".")
        for n in range(len(parts), 0, -1):
            name = ".".join(parts[:n])
            if isinstance(node, dict) and name in node:
                node, rest = node[name], ".".join(parts[n:])
                break
        else:
            raise KeyError(key)
    return node


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _step(code: str) -> dict[str, Any]:
    """An email's next step as the interface names it: its code, and whether its extraction reads the email's own text
    too (its type pack reads text, as the email domain's `mailbox.reads_text` says)."""
    kind, _, key = code.partition(":")
    reads = kind == "m2" and key in typepack.keys() and "text" in typepack.get(key).inputs
    return {"code": code, "reads_text": reads}


def _value(spec: dict[str, Any]) -> dict[str, Any]:
    """A shown value, read from the loaded rule file; a code is given by the interface's own label."""
    from jav.app import datasets

    raw = resolve(config_of(spec["file"]), spec["key"])
    fmt = spec["format"]
    if fmt == "yes_no":
        value: Any = bool(raw)
    elif fmt in ("doc_types", "fields"):
        names = datasets.label_set("doc_type" if fmt == "doc_types" else "field")
        value = [names.get(k, k) for k in _as_list(raw)]
    elif fmt == "labels":
        value = [spec["labels"].get(k, k) for k in _as_list(raw)]
    elif fmt == "route":
        value = _step(raw)
    elif fmt == "provider":
        value = datasets.PROVIDER_NAMES.get(raw, raw)
    elif fmt == "intent_routes":
        intents = datasets.label_set("intent")
        value = [[intents.get(i, i), _step(r)] for i, r in raw.items()]
    elif fmt == "usd_by_provider":
        value = [[datasets.PROVIDER_NAMES.get(p, p), str(v)] for p, v in raw.items()]
    else:
        value = raw
    return {"file": spec["file"], "key": spec["key"], "label": spec["label"], "format": FORMATS[fmt], "value": value}


def _text(v: dict[str, Any], steps: dict[str, str]) -> str:
    """A shown value as searchable plain text (the interface sets it in the chosen language); a next step by its
    label (`steps`)."""
    value, fmt = v["value"], v["format"]
    if fmt == "percent":
        shown = f"{value * 100:g} %"
    elif fmt == "points":
        shown = f"{value * 100:g} percentage points"
    elif fmt == "yes_no":
        shown = "yes" if value else "no"
    elif fmt == "names":
        shown = ", ".join(value)
    elif fmt == "route":
        shown = steps.get(value["code"], value["code"])
    elif fmt == "routes":
        shown = ", ".join(f"{a} → {steps.get(b['code'], b['code'])}" for a, b in value)
    elif fmt == "usd":
        shown = ", ".join(f"{p} {amount} USD" for p, amount in value)
    else:
        shown = str(value)
    return f"{v['label']} {shown}" if fmt in COMPARED else f"{v['label']}: {shown}"


def _dated(file: str, version: str | None) -> str | None:
    """The date of the rule file's version in its own changelog."""
    if version is None:
        return None
    meta = config_of(file).get("meta") or {}
    return next((e.get("date") for e in meta.get("changelog") or [] if str(e.get("version")) == version), None)


def _files(p: trace.Point, titles: dict[str, str], snapshot: rulebook.Snapshot,
           first_seen: dict[str, str]) -> list[dict[str, Any]]:
    """The rule files the point reads: each one's version and its date, or a family's count (`types/*.json`), and since
    when the content in use now is in use here (the first time a run, an item or a decision stored it; None before)."""
    out = []
    for pattern in p.files:
        matched = sorted(path for path in snapshot.files if fnmatch.fnmatchcase(path, pattern))
        seen = [s for path in matched if (s := first_seen.get(snapshot.files[path].sha256))]
        single = matched == [pattern]
        version = snapshot.files[pattern].version if single else None
        out.append({"file": pattern, "title": titles.get(pattern, pattern), "version": version,
                    "dated": _dated(pattern, version) if single else None, "count": None if single else len(matched),
                    "since": max(seen) if matched and len(seen) == len(matched) else None})
    return out


def _file_text(f: dict[str, Any]) -> str:
    return f"{f['title']} ({f['file']}) " + (f["version"] or f"{f['count']} files")


def _first_seen(snapshot: rulebook.Snapshot) -> dict[str, str]:
    shas = sorted({f.sha256 for f in snapshot.files.values()})
    out: dict[str, str] = {}
    with store.connect() as c:
        for n in range(0, len(shas), 500):  # well under every database's limit of bound values
            part = shas[n:n + 500]
            out.update((r["sha256"], r["first_seen_at"]) for r in c.execute(
                f"SELECT sha256, first_seen_at FROM rule_files WHERE sha256 IN ({','.join('?' * len(part))})", part))  # noqa: S608 - placeholders only
    return out


def _decisions(snapshot: rulebook.Snapshot) -> dict[str, dict[str, Any]]:
    """By point: the decisions in the trace, those made with the rule files in use now (each file's content the same),
    and the latest one's time."""
    out: dict[str, dict[str, Any]] = {}
    with store.connect() as c:
        groups = c.execute("SELECT point, rules, COUNT(*) AS n, MAX(at) AS last FROM decision_trace GROUP BY point, rules")
        for r in groups:
            d = out.setdefault(r["point"], {"decisions": 0, "current": 0, "last_at": None})
            d["decisions"] += r["n"]
            if all((f := snapshot.files.get(rule["file"])) is not None and f.sha256 == rule["sha256"]
                   for rule in json.loads(r["rules"])):
                d["current"] += r["n"]
            d["last_at"] = max(filter(None, (d["last_at"], r["last"])), default=None)
    return out


def rows() -> list[dict[str, Any]]:
    """One row per decision point, by area in the described order (the points of an area in their order there); a
    point without a description still shows, with its developer's text (a test asks for every description)."""
    from jav.app import datasets, registrations

    registrations.load_all()  # every point registered
    steps = datasets.label_set("next_flow")
    help_ = cfg.load("rule_help")
    snapshot = rulebook.current()
    first_seen, counts = _first_seen(snapshot), _decisions(snapshot)
    areas = list(help_["areas"])
    described = sorted(help_["points"].items(), key=lambda kv: areas.index(kv[1]["area"]))
    out = []
    for code, entry in [*described, *((p.code, None) for p in trace.points() if p.code not in help_["points"])]:
        p = trace.point(code)
        values = [_value(spec) for spec in entry["values"]] if entry else []
        files = _files(p, help_["files"], snapshot, first_seen)
        out.append({"_key": code, "area": entry["area"] if entry else None, "decision": entry["title"] if entry else code,
                    "what": entry["what"] if entry else p.what, "not_for": entry["not_for"] if entry else p.not_for,
                    "values": "; ".join(_text(v, steps) for v in values), "_values": values,
                    "files": "; ".join(_file_text(f) for f in files), "_files": files,
                    **counts.get(code, {"decisions": 0, "current": 0, "last_at": None})})
    return out


def area_labels() -> dict[str, str]:
    """The areas' names (English source; the interface translates them)."""
    return dict(cfg.load("rule_help")["areas"])


__all__ = ["COMPARED", "FORMATS", "area_labels", "config_of", "resolve", "rows"]
