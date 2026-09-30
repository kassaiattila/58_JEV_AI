"""Config as data: the loader of the `configs/` JSON files and the `config_hash` (ROADMAP §1).

Files: `configs/doc_types.json`, `configs/intents.json`, `configs/policy.json`, `configs/callsites/<call_site>.json`.
Every file: `{"meta": {"name", "version", "changelog": [...]}, ...content}`. The `config_hash` is the sha256 of the
content's canonical JSON (without `meta.changelog`, so that a note does not change it), shortened to 16 hex digits.
The hash goes to the ledger with every JEV call (`adapters.jev.ask(config_hash=...)`), so a measurement can be traced
back to the config version. On a content change `meta.version` must be bumped too (the `configs` CLI command shows
the hashes).

The Python modules (doc_types, intents, policy, detect, intent, jev_select, jev_verify) read from here; the code is
the mechanism, the JSON is the parameter. The JSON stores regex patterns as strings; the module compiles them.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jav.config import PROJECT_ROOT

CONFIG_DIR = PROJECT_ROOT / "configs"
CALLSITE_DIR = CONFIG_DIR / "callsites"
HASH_LEN = 16


TYPES_DIR = CONFIG_DIR / "types"  # type packs: all type data of one document type's extraction (jav/typepack.py)


def path_of(name: str) -> Path:
    """`doc_types` -> configs/doc_types.json; `callsite:detect` -> configs/callsites/detect.json; `type:invoice_hu` -> configs/types/invoice_hu.json."""
    if name.startswith("callsite:"):
        return CALLSITE_DIR / f"{name.split(':', 1)[1]}.json"
    if name.startswith("type:"):
        return TYPES_DIR / f"{name.split(':', 1)[1]}.json"
    return CONFIG_DIR / f"{name}.json"


@lru_cache(maxsize=None)
def load(name: str) -> dict[str, Any]:
    p = path_of(name)
    if not p.exists():
        raise FileNotFoundError(f"konfig hiányzik: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if "meta" not in data or "version" not in data["meta"]:
        raise ValueError(f"konfig meta.version hiányzik: {p}")
    return data


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
        h.update(canonical(load(name)).encode("utf-8"))
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
    return str(load(name)["meta"]["version"])


def all_names() -> list[str]:
    names = [p.stem for p in sorted(CONFIG_DIR.glob("*.json"))]
    names += [f"callsite:{p.stem}" for p in sorted(CALLSITE_DIR.glob("*.json"))]
    names += [f"type:{p.stem}" for p in sorted(TYPES_DIR.glob("*.json"))] if TYPES_DIR.exists() else []
    return names


def report() -> list[dict[str, str]]:
    """CLI report: name, version, hash, last changelog entry."""
    rows = []
    for name in all_names():
        d = load(name)
        log = d["meta"].get("changelog") or []
        rows.append({"name": name, "version": version(name), "hash": config_hash(name), "last": (log[-1].get("note", "") if log else "")[:80]})
    return rows


def reload() -> None:
    """For tests / config changes at run time: clears the cache."""
    load.cache_clear()
    config_hash.cache_clear()
    file_digest.cache_clear()
