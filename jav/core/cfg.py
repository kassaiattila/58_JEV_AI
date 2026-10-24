"""Config as data: the loader of the `configs/` JSON files and the `config_hash` (ROADMAP §1).

Files: `configs/doc_types.json`, `configs/intents.json`, `configs/policy.json`, `configs/callsites/<call_site>.json`.
Every file: `{"meta": {"name", "version", "changelog": [...]}, ...content}`. The `config_hash` is the sha256 of the
content's canonical JSON (without `meta.changelog`, so that a note does not change it), shortened to 16 hex digits.
The hash goes to the ledger with every JEV call (`jav.ai.jev.ask(config_hash=...)`), so a measurement can be traced
back to the config version. On a content change `meta.version` must be bumped too (the `configs` CLI command shows
the hashes).

The Python modules (doc_types, intents, policy, detect, intent, jev_select, jev_verify) read from here; the code is
the mechanism, the JSON is the parameter. The JSON stores regex patterns as strings; the module compiles them.

227 (plan R3b): a decision point's rule file (`jav.core.trace`, `Point.files`) is read when its rule applies, never
copied when a module is loaded: a module's rule table is a `Section`, a read-through view, so a reload (`reload`)
reaches the decisions without a restart. The loader does not reread a changed file by itself: the service runs from
the working folder, and a half-edited rule must not reach it. The registries, the call sites and the prompts stay as
loaded: their change is a new AI request, measured and released.

231 (plan stage B, B3): a process may keep its own values of some keys of the rule files (`jav/app/process_settings.py`).
While code works on one case, its values lie over the files (`overlay`, a context of the call): `load` returns the
file with them in place, so a module reads them as it reads the file. `config_hash` and `version` stay the file's.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from jav.core.config import PROJECT_ROOT

log = logging.getLogger(__name__)

CONFIG_DIR = PROJECT_ROOT / "configs"
CALLSITE_DIR = CONFIG_DIR / "callsites"
HASH_LEN = 16


TYPES_DIR = CONFIG_DIR / "types"  # type packs: all type data of one document type's extraction (jav/ai/typepack.py)
PROCESSES_DIR = CONFIG_DIR / "processes"  # 231 (A4): process packs, one kind of business process each (jav/app/process_packs.py)


def path_of(name: str) -> Path:
    """`doc_types` -> configs/doc_types.json; `callsite:detect` -> configs/callsites/detect.json; `type:invoice_hu` -> configs/types/invoice_hu.json;
    `process:it_quote` -> configs/processes/it_quote.json (231)."""
    if name.startswith("callsite:"):
        return CALLSITE_DIR / f"{name.split(':', 1)[1]}.json"
    if name.startswith("type:"):
        return TYPES_DIR / f"{name.split(':', 1)[1]}.json"
    if name.startswith("process:"):
        return PROCESSES_DIR / f"{name.split(':', 1)[1]}.json"
    return CONFIG_DIR / f"{name}.json"


@lru_cache(maxsize=None)
def _file(name: str) -> dict[str, Any]:
    p = path_of(name)
    if not p.exists():
        raise FileNotFoundError(f"konfig hiányzik: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if "meta" not in data or "version" not in data["meta"]:
        raise ValueError(f"konfig meta.version hiányzik: {p}")
    return data


@dataclass(frozen=True)
class Overlay:
    """231 (B3): a case's own values over the rule files: `values` {config name: {dotted key: value}}, and `refs`, the
    same keys' origin {config name: {dotted key: {"setting": id, "version": n}}} that the decision trace records."""

    values: Mapping[str, Mapping[str, Any]]
    refs: Mapping[str, Mapping[str, Mapping[str, Any]]] = field(default_factory=dict)
    _cache: dict[str, dict[str, Any]] = field(default_factory=dict, compare=False, repr=False)

    def applied(self, name: str, data: dict[str, Any]) -> dict[str, Any]:
        """The file's data with these values in place; a key the file no longer holds (a case started before the file
        changed) is left out, with a warning in the log."""
        if name not in self._cache:
            out = copy.deepcopy(data)
            for key, value in self.values[name].items():
                *parents, last = key.split(".")
                node: Any = out
                for part in parents:
                    node = node.get(part) if isinstance(node, dict) else None
                if not isinstance(node, dict) or last not in node:
                    log.warning("config %s holds no rule %s: the case's own value %r is left out", name, key, value)
                    continue
                node[last] = value
            self._cache[name] = out
        return self._cache[name]


_overlay: ContextVar[Overlay | None] = ContextVar("cfg_overlay", default=None)


@contextmanager
def overlay(values: Overlay | None) -> Iterator[None]:
    """231 (B3): the reads inside this context see these values over the files (None: the files alone)."""
    token = _overlay.set(values if values is not None and values.values else None)
    try:
        yield
    finally:
        _overlay.reset(token)


def current_overlay() -> Overlay | None:
    """The values lying over the files in this context (None: the files alone)."""
    return _overlay.get()


def load(name: str) -> dict[str, Any]:
    """The config file `name`, with the values of the case at hand over it (`overlay`, 231 B3). Read only."""
    data = _file(name)
    over = _overlay.get()
    return over.applied(name, data) if over is not None and name in over.values else data


class Section(Mapping[str, Any]):
    """227 (plan R3b): a part of a config file (`name`, then the keys of `path` from its top) read through `load`
    whenever it is asked, never copied: a module's rule table follows a reload (`reload`) without a restart. A missing
    part reads as empty. Read only: a change of a rule is a change of its file."""

    def __init__(self, name: str, *path: str) -> None:
        self.name, self.path = name, path

    def _data(self) -> Mapping[str, Any]:
        data: Any = load(self.name)
        for key in self.path:
            data = data.get(key, {})
        return data

    def __getitem__(self, key: str) -> Any:
        return self._data()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data())

    def __len__(self) -> int:
        return len(self._data())

    def __repr__(self) -> str:
        return f"Section({self.name!r}{''.join(f', {k!r}' for k in self.path)})"


def canonical(data: dict[str, Any]) -> str:
    body = {k: v for k, v in data.items() if k != "meta"}
    body["_meta"] = {k: v for k, v in data.get("meta", {}).items() if k != "changelog"}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=None)
def config_hash(*names: str) -> str:
    """The joint hash of one or more configs (e.g. the detect call site + the doc_types registry)."""
    h = hashlib.sha256()
    for name in sorted(names):
        h.update(name.encode("utf-8"))
        h.update(canonical(_file(name)).encode("utf-8"))
    return h.hexdigest()[:HASH_LEN]


def combine(*parts: str) -> str:
    """067 (066 Á18): a short joint identifier of several hashes or file fingerprints (order-sensitive). It puts into
    one identifier everything that affects a call's result: call site, type pack, instruction and schema file,
    policy."""
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:HASH_LEN]


@lru_cache(maxsize=None)
def file_digest(path: Path) -> str:
    """The content fingerprint of a non-JSON config file (instruction, schema)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def version(name: str) -> str:
    return str(_file(name)["meta"]["version"])


def all_names() -> list[str]:
    names = [p.stem for p in sorted(CONFIG_DIR.glob("*.json"))]
    names += [f"callsite:{p.stem}" for p in sorted(CALLSITE_DIR.glob("*.json"))]
    names += [f"type:{p.stem}" for p in sorted(TYPES_DIR.glob("*.json"))] if TYPES_DIR.exists() else []
    names += [f"process:{p.stem}" for p in sorted(PROCESSES_DIR.glob("*.json"))] if PROCESSES_DIR.exists() else []
    return names


def report() -> list[dict[str, str]]:
    """CLI report: name, version, hash, last changelog entry."""
    rows = []
    for name in all_names():
        d = load(name)
        log = d["meta"].get("changelog") or []
        rows.append({"name": name, "version": version(name), "hash": config_hash(name), "last": (log[-1].get("note", "") if log else "")[:80]})
    return rows


_ON_RELOAD: list[Callable[[], None]] = []


def on_reload(fn: Callable[[], None]) -> None:
    """218: a module whose state follows the loaded configs (the calculation snapshot, `jav.core.rulebook`) is told
    when `reload` clears them."""
    if fn not in _ON_RELOAD:
        _ON_RELOAD.append(fn)


def reload() -> None:
    """For tests / config changes at run time: clears the cache."""
    _file.cache_clear()
    config_hash.cache_clear()
    file_digest.cache_clear()
    for fn in _ON_RELOAD:
        fn()
