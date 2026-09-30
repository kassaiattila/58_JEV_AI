"""Konfig mint adat: a `configs/` JSON-fájlok betöltője és a `config_hash` (ROADMAP §1).

Fájlok: `configs/doc_types.json`, `configs/intents.json`, `configs/policy.json`, `configs/callsites/<call_site>.json`.
Minden fájl: `{"meta": {"name", "version", "changelog": [...]}, ...tartalom}`. A `config_hash` a tartalom kanonikus
JSON-jának sha256-a (a `meta.changelog` nélkül, hogy egy megjegyzés ne változtassa meg), 16 hex jegyre rövidítve.
A hash a ledgerbe kerül minden Jev-hívásnál (`adapters.jev.ask(config_hash=...)`), így egy mérés visszavezethető a
konfig-verzióra. Tartalmi változásnál a `meta.version` is lépjen (a `configs` CLI-parancs mutatja a hash-eket).

A Python-modulok (doc_types, intents, policy, detect, intent, jev_select, jev_verify) innen olvasnak; a kód a
mechanizmus, a JSON a paraméter. Regex-mintákat a JSON stringként tárol, a modul fordítja.
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


TYPES_DIR = CONFIG_DIR / "types"  # típus-csomagok: egy dokumentumtípus adatpont-kinyerésének minden típus-adata (jav/typepack.py)


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
    """Egy vagy több konfig együttes hash-e (pl. a detect hívási hely + a doc_types regiszter)."""
    h = hashlib.sha256()
    for name in sorted(names):
        h.update(name.encode("utf-8"))
        h.update(canonical(load(name)).encode("utf-8"))
    return h.hexdigest()[:HASH_LEN]


def combine(*parts: str) -> str:
    """067 (066 Á18): több hash vagy fájl-ujjlenyomat együttes, rövid azonosítója (sorrendfüggő). Ezzel kerül egy
    azonosítóba minden, ami egy hívás eredményét befolyásolja: hívási hely, típuscsomag, utasítás- és sémafájl, policy."""
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:HASH_LEN]


@lru_cache(maxsize=None)
def file_digest(path: Path) -> str:
    """Egy nem JSON-konfig fájl (utasítás, séma) tartalmának ujjlenyomata."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def version(name: str) -> str:
    return str(load(name)["meta"]["version"])


def all_names() -> list[str]:
    names = [p.stem for p in sorted(CONFIG_DIR.glob("*.json"))]
    names += [f"callsite:{p.stem}" for p in sorted(CALLSITE_DIR.glob("*.json"))]
    names += [f"type:{p.stem}" for p in sorted(TYPES_DIR.glob("*.json"))] if TYPES_DIR.exists() else []
    return names


def report() -> list[dict[str, str]]:
    """CLI-riport: név, verzió, hash, utolsó changelog-bejegyzés."""
    rows = []
    for name in all_names():
        d = load(name)
        log = d["meta"].get("changelog") or []
        rows.append({"name": name, "version": version(name), "hash": config_hash(name), "last": (log[-1].get("note", "") if log else "")[:80]})
    return rows


def reload() -> None:
    """Tesztekhez / futás közbeni konfig-módosításhoz: a cache ürítése."""
    load.cache_clear()
    config_hash.cache_clear()
    file_digest.cache_clear()
