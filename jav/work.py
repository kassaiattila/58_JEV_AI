"""Munkacsomag → recept → futás (040 K1): a keret üzleti rekordjai és szabályai, felülettől függetlenül.

Fogalmak (docs/GLOSSARY.md): a **munkacsomag** egy forrásból érkezett iratok csoportja, verziózott tartalommal; a
**recept** a `configs/recipes.json` verziózott leírása; a **futtatás** egy recept a munkacsomag RÖGZÍTETT bemenetén
(tételenként tartalomhash), próba (`shadow`) vagy éles (`apply`) módban. A V4 mintái: `businessWorkflowApi.ts`
(hozzárendelés `expected_revision`-nel, készenlét akadályokkal/figyelmeztetésekkel, idempotens indítás, jóváhagyás).

Szabályok:
- Minden módosítás `expected_revision`-t kér; eltérésnél `RevisionConflict` (nincs csendes felülírás).
- A futás a hozzárendelés és a bemenet pillanatképét tárolja; későbbi módosítás nem hat rá.
- Azonos csomag + hozzárendelés-verzió + bemenet + mód ismételt indítása a meglévő futást adja (`deduped`).
- Jóváhagyás csak éles módban, minden tétel lezárulta és nyitott teendő nélkül.
- A futás keretét a recept tételenkénti maximuma × tételszám adja (`jav.runtime.calls`, scope = run_id).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav import cfg, store, typepack
from jav.runtime import calls, queue

JOB_KIND = "run_item"

store.register_schema("work", """
CREATE TABLE IF NOT EXISTS workpackages (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source_kind TEXT NOT NULL,                 -- folder | upload | mailbox | manual
    source_ref  TEXT,
    revision    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workpackage_items (
    workpackage_id TEXT NOT NULL REFERENCES workpackages(id),
    item_id     TEXT NOT NULL,                 -- dokumentumnál a tartalom sha256-a (= documents.doc_id)
    kind        TEXT NOT NULL,                 -- document | email
    source_path TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    added_revision   INTEGER NOT NULL,
    removed_revision INTEGER,
    parent_item_id   TEXT,                     -- 058 K5.2: a levél csatolmányánál a levél tétele (a csatolmány eredete)
    PRIMARY KEY (workpackage_id, item_id)
);
CREATE TABLE IF NOT EXISTS recipe_assignments (
    workpackage_id TEXT NOT NULL REFERENCES workpackages(id),
    revision    INTEGER NOT NULL,
    recipe_id   TEXT NOT NULL,
    recipe_version INTEGER NOT NULL,
    recipe_hash TEXT NOT NULL,
    params      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    note        TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (workpackage_id, revision)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    workpackage_id TEXT NOT NULL REFERENCES workpackages(id),
    dedup_key   TEXT UNIQUE NOT NULL,
    mode        TEXT NOT NULL,                 -- shadow | apply
    assignment_revision INTEGER NOT NULL,
    recipe_id   TEXT NOT NULL,
    recipe_version INTEGER NOT NULL,
    recipe_hash TEXT NOT NULL,
    recipe      TEXT NOT NULL,                 -- a recept pillanatképe (JSON)
    params      TEXT NOT NULL,
    input       TEXT NOT NULL,                 -- rögzített bemenet: tételek + hash-ek
    input_hash  TEXT NOT NULL,
    status      TEXT NOT NULL,                 -- queued | running | needs_review | done | failed | cancelled
    approval    TEXT,                          -- NULL | approved
    approved_by TEXT,
    approved_at TEXT,
    actor       TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_wp ON runs(workpackage_id, created_at);
-- 058: a csomag elrejtése, visszahozása, átnevezése és törlése (ki, mikor, mit); a törölt csomag nyoma is itt marad
-- 058: a forrásfájl ujjlenyomata méret + módosítási idő szerint megjegyezve (a csomag megnyitása ne hasheljen újra
-- minden fájlt); az indítás és a feldolgozó mindig teljesen ellenőriz
CREATE TABLE IF NOT EXISTS file_fingerprints (
    path        TEXT PRIMARY KEY,
    size        INTEGER NOT NULL,
    mtime_ns    INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    checked_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workpackage_events (
    workpackage_id TEXT NOT NULL,
    action      TEXT NOT NULL,                 -- archive | restore | rename | delete
    actor       TEXT NOT NULL,
    detail      TEXT,                          -- JSON
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_items (
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    item_id     TEXT NOT NULL,
    status      TEXT NOT NULL,                 -- done | failed | cancelled
    final_status TEXT,                         -- a folyamat végállapota (done | needs_review | needs_ocr | jev_unavailable ...)
    flow_run_id TEXT,
    error       TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, item_id)
);
""")


def _migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(workpackage_items)")}
    if cols and "parent_item_id" not in cols:  # 058 K5.2: a csatolmány a levelére mutat
        conn.execute("ALTER TABLE workpackage_items ADD COLUMN parent_item_id TEXT")
    wcols = {r[1] for r in conn.execute("PRAGMA table_info(workpackages)")}
    if wcols and "owner" not in wcols:  # 061: a csomag felelőse (a névlista egy neve)
        conn.execute("ALTER TABLE workpackages ADD COLUMN owner TEXT")


store.register_migration("work", _migrate)


class RevisionConflict(RuntimeError):
    """A kérés egy korábbi verzióra épült; a hívó töltse újra az állapotot (felületen: 409, a munkapéldány megmarad)."""


class NotReady(RuntimeError):
    def __init__(self, message: str, blockers: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.blockers = blockers or []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pinned_run(c: sqlite3.Connection, run_id: str) -> bool:
    """066 Á06 (döntés 2026-09-29): a még jóvá nem hagyott, meg nem szakított éles futás teendő-okai rögzítettek (másik
    futás nem veszi át, nem zárja le őket); a próbafutás okát továbbra is a legutóbbi futás viszi."""
    row = c.execute("SELECT 1 FROM runs WHERE run_id=? AND mode='apply' AND approval IS NULL AND status<>'cancelled'",
                    (run_id,)).fetchone()
    return row is not None


store.set_pinned_run_check(_pinned_run)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(path: Path, *, verify: bool = False) -> str:
    """A fájl tartalomhash-e. `verify=False`: ha a méret és a módosítási idő a legutóbbi számoláskor ugyanez volt, a
    megjegyzett érték (058: a csomag megnyitása gyors marad sok irattal is); `verify=True`: mindig teljes számolás."""
    st = path.stat()
    key = str(path.resolve())
    if not verify:
        with store.connect() as c:
            row = c.execute("SELECT sha256 FROM file_fingerprints WHERE path=? AND size=? AND mtime_ns=?",
                            (key, st.st_size, st.st_mtime_ns)).fetchone()
        if row is not None:
            return row["sha256"]
    digest = sha256_file(path)
    with store.connect() as c:
        c.execute("INSERT INTO file_fingerprints(path, size, mtime_ns, sha256, checked_at) VALUES (?,?,?,?,?) ON CONFLICT(path)"
                  " DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns, sha256=excluded.sha256, checked_at=excluded.checked_at",
                  (key, st.st_size, st.st_mtime_ns, digest, _now()))
    return digest


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


# --- receptek ---------------------------------------------------------------------------------------


def recipes() -> list[dict[str, Any]]:
    return list(cfg.load("recipes")["recipes"])


def recipe(recipe_id: str) -> dict[str, Any]:
    for r in recipes():
        if r["id"] == recipe_id:
            return r
    raise ValueError(f"unknown recipe {recipe_id!r}")


def recipe_hash(r: dict[str, Any]) -> str:
    return hashlib.sha256(_canon(r).encode("utf-8")).hexdigest()[:16]


def _validated_params(r: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    unknown = set(params) - set(r["params"])
    if unknown:
        raise ValueError(f"unknown params: {sorted(unknown)}")
    for name, spec in r["params"].items():
        value = params.get(name, spec.get("default"))
        allowed = spec.get("allowed") or (typepack.keys() if spec.get("allowed_from") == "typepacks" else None)
        if allowed is not None and value not in allowed:
            raise ValueError(f"param {name}={value!r} not in {sorted(allowed)}")
        out[name] = value
    return out


# --- munkacsomag -------------------------------------------------------------------------------------


def create_workpackage(*, name: str, source_kind: str, source_ref: str | None, owner: str | None = None) -> dict[str, Any]:
    """`owner` (065 döntés): az új csomag felelőse a létrehozó; név nélküli (gépi) létrehozásnál nincs felelős."""
    if not name.strip():
        raise ValueError("name required")
    wp_id = f"wp-{uuid.uuid4().hex[:12]}"
    with store.connect() as c:
        c.execute("INSERT INTO workpackages(id, name, source_kind, source_ref, revision, created_at, updated_at, owner) VALUES (?,?,?,?,0,?,?,?)",
                  (wp_id, name.strip(), source_kind, source_ref, _now(), _now(), owner))
    return get(wp_id)


def _bump(c, wp_id: str, expected_revision: int) -> int:
    row = c.execute("SELECT revision FROM workpackages WHERE id=?", (wp_id,)).fetchone()
    if row is None:
        raise KeyError(wp_id)
    if row["revision"] != expected_revision:
        raise RevisionConflict(f"workpackage {wp_id} is at revision {row['revision']}, not {expected_revision}")
    c.execute("UPDATE workpackages SET revision=revision+1, updated_at=? WHERE id=?", (_now(), wp_id))
    return expected_revision + 1


def _begin(c) -> None:
    store.begin_immediate(c)


def packaged_sources(paths: list[Path]) -> set[Path]:
    """063: a megadott fájlok közül azok, amelyek már valaha felkerültek egy munkacsomagra (az eltávolított tétel is
    számít). A levélletöltés ezzel ismeri fel a letöltött, de csomagba nem került levelet (pl. megszakadt letöltés)."""
    want = {str(Path(p).resolve()): Path(p) for p in paths}
    keys, found = list(want), set()
    with store.connect() as c:
        for n in range(0, len(keys), 500):  # az SQLite paraméterkorlátja alatt
            chunk = keys[n:n + 500]
            found |= {r["source_path"] for r in c.execute(
                f"SELECT DISTINCT source_path FROM workpackage_items WHERE source_path IN ({','.join('?' * len(chunk))})", chunk)}
    return {want[k] for k in found}


def add_documents(wp_id: str, paths: list[Path], *, expected_revision: int) -> dict[str, Any]:
    """Iratok felvétele egy verziólépésben. Azonos tartalmú irat egyszer szerepel; a tartalomhash a felvételkor rögzül."""
    return add_items(wp_id, paths, kind="document", expected_revision=expected_revision)


def add_items(wp_id: str, paths: list[Path], *, kind: str, expected_revision: int,
              parents: dict[Path, str] | None = None) -> dict[str, Any]:
    """Tételek felvétele egy verziólépésben (`document`: irat-fájl; `email`: a levél `message.json`-ja, 048 T2).
    A tétel azonosítója a fájl tartalomhash-e; azonos tartalom egyszer szerepel. `parents` (058 K5.2): fájlonként a
    szülő tétel azonosítója — a levél csatolmánya így a levélre mutat (a csatolmány eredete)."""
    if kind not in ("document", "email"):
        raise ValueError(f"unknown item kind: {kind}")
    parents = {Path(k).resolve(): v for k, v in (parents or {}).items()}
    resolved = []
    for p in paths:
        p = Path(p).resolve(strict=True)
        if not p.is_file():
            raise ValueError(f"not a file: {p}")
        resolved.append((p, sha256_file(p)))
    with store.connect() as c:
        _begin(c)
        rev = _bump(c, wp_id, expected_revision)
        for p, digest in resolved:
            c.execute("INSERT INTO workpackage_items(workpackage_id, item_id, kind, source_path, sha256, added_revision, parent_item_id)"
                      " VALUES (?,?,?,?,?,?,?) ON CONFLICT(workpackage_id, item_id) DO UPDATE SET removed_revision=NULL,"
                      " source_path=excluded.source_path, parent_item_id=COALESCE(workpackage_items.parent_item_id, excluded.parent_item_id)",
                      (wp_id, digest, kind, str(p), digest, rev, parents.get(p)))
    return get(wp_id)


def add_document(wp_id: str, path: Path, *, expected_revision: int) -> dict[str, Any]:
    return add_documents(wp_id, [path], expected_revision=expected_revision)


def remove_item(wp_id: str, item_id: str, *, expected_revision: int) -> dict[str, Any]:
    with store.connect() as c:
        _begin(c)
        rev = _bump(c, wp_id, expected_revision)
        c.execute("UPDATE workpackage_items SET removed_revision=? WHERE workpackage_id=? AND item_id=? AND removed_revision IS NULL",
                  (rev, wp_id, item_id))
    return get(wp_id)


def create_from_folder(folder: Path, *, name: str | None = None, suffixes: tuple[str, ...] = (".pdf",),
                       owner: str | None = None) -> dict[str, Any]:
    """Munkacsomag egy mappa közvetlen tartalmából (almappák nélkül), név szerinti sorrendben."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f"folder does not exist: {folder}")
    root = folder.resolve(strict=True)
    files = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in suffixes
                   and p.resolve().parent == root)  # a mappán kívülre mutató hivatkozás nem kerül be
    wp = create_workpackage(name=name or root.name, source_kind="folder", source_ref=str(root), owner=owner)
    return _fill_new(wp, lambda: add_documents(wp["id"], files, expected_revision=0)) if files else wp


def create_from_files(paths: list[Path], *, name: str, owner: str | None = None) -> dict[str, Any]:
    """Munkacsomag megadott fájlokból (több mappából is), egy verziólépésben (040 K3: élő próba, felületi kiválasztás)."""
    if not paths:
        raise ValueError("at least one file is required")
    wp = create_workpackage(name=name, source_kind="manual", source_ref=None, owner=owner)
    return _fill_new(wp, lambda: add_documents(wp["id"], list(paths), expected_revision=0))


def _fill_new(wp: dict[str, Any], fill: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """063: az új csomag feltöltése; ha a felvétel nem sikerül (pl. zárolt fájl), az üres csomag nem marad a listában."""
    try:
        return fill()
    except Exception:
        with store.connect() as c:
            c.execute("DELETE FROM workpackages WHERE id=? AND NOT EXISTS (SELECT 1 FROM workpackage_items WHERE workpackage_id=?)",
                      (wp["id"], wp["id"]))
        raise


def get(wp_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM workpackages WHERE id=?", (wp_id,)).fetchone()
        if row is None:
            raise KeyError(wp_id)
        items = [dict(r) for r in c.execute(
            "SELECT item_id, kind, source_path, sha256, added_revision, parent_item_id FROM workpackage_items"
            " WHERE workpackage_id=? AND removed_revision IS NULL ORDER BY source_path", (wp_id,))]
    for i in items:  # 058 K5.2: csak a csatolmánynak van szülője (a régi tételek alakja változatlan)
        parent = i.pop("parent_item_id")
        if parent:
            i["parent_item_id"] = parent
    return {**dict(row), "items": items, "assignment": current_assignment(wp_id)}


def list_workpackages(*, include_archived: bool = False) -> list[dict[str, Any]]:
    """A munkacsomagok listája; az elrejtett (archivált) csomag csak kérésre (058)."""
    where = "" if include_archived else " WHERE w.status <> 'archived'"
    with store.connect() as c:
        rows = c.execute(
            "SELECT w.*, (SELECT COUNT(*) FROM workpackage_items i WHERE i.workpackage_id=w.id AND i.removed_revision IS NULL) items,"
            " (SELECT recipe_id FROM recipe_assignments a WHERE a.workpackage_id=w.id ORDER BY revision DESC LIMIT 1) recipe_id,"
            " (SELECT run_id FROM runs r WHERE r.workpackage_id=w.id ORDER BY created_at DESC, rowid DESC LIMIT 1) last_run_id"
            f" FROM workpackages w{where} ORDER BY w.created_at DESC, w.rowid DESC").fetchall()
    return [dict(r) for r in rows]


# --- elrejtés, átnevezés, törlés (058) ---------------------------------------------------------------
# A név és az elrejtés nem része a futás bemenetének, ezért nem léptet verziót (a futások és a készenlét változatlan).


def _event(c, wp_id: str, action: str, actor: str, detail: dict[str, Any] | None = None) -> None:
    c.execute("INSERT INTO workpackage_events(workpackage_id, action, actor, detail, created_at) VALUES (?,?,?,?,?)",
              (wp_id, action, actor, _canon(detail) if detail else None, _now()))


def _set_wp(wp_id: str, action: str, actor: str, **fields: Any) -> dict[str, Any]:
    cols = ", ".join(f"{k}=?" for k in fields)
    with store.connect() as c:
        _begin(c)
        before = c.execute("SELECT name, status, owner FROM workpackages WHERE id=?", (wp_id,)).fetchone()
        if before is None:
            raise KeyError(wp_id)
        c.execute(f"UPDATE workpackages SET {cols}, updated_at=? WHERE id=?", (*fields.values(), _now(), wp_id))
        _event(c, wp_id, action, actor, {"before": dict(before), "after": fields})
    return get(wp_id)


def set_owner(wp_id: str, owner: str | None, *, actor: str) -> dict[str, Any]:
    """061: a csomag felelőse (None: nincs). Nem része a futás bemenetének, ezért nem léptet verziót; naplózva."""
    return _set_wp(wp_id, "owner", actor, owner=owner)


def archive_workpackage(wp_id: str, *, actor: str) -> dict[str, Any]:
    """Elrejtés a listából: a futások, a hívásnapló és az eredmények megmaradnak; a csomag közvetlenül megnyitható."""
    return _set_wp(wp_id, "archive", actor, status="archived")


def restore_workpackage(wp_id: str, *, actor: str) -> dict[str, Any]:
    return _set_wp(wp_id, "restore", actor, status="open")


def rename_workpackage(wp_id: str, name: str, *, actor: str) -> dict[str, Any]:
    name = name.strip()
    if not name or len(name) > 200:
        raise ValueError("name must be 1-200 characters")
    return _set_wp(wp_id, "rename", actor, name=name)


def workpackage_events(wp_id: str) -> list[dict[str, Any]]:
    with store.connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM workpackage_events WHERE workpackage_id=? ORDER BY rowid", (wp_id,))]


def delete_workpackage(wp_id: str, *, actor: str) -> None:
    """Végleges törlés csak futás nélküli csomagon (a futással rendelkező csak elrejthető, mert a hívásnapló és az
    eredmények rá hivatkoznak). A tételek forrásfájljai a helyükön maradnak."""
    with store.connect() as c:
        _begin(c)
        row = c.execute("SELECT name, source_kind, source_ref FROM workpackages WHERE id=?", (wp_id,)).fetchone()
        if row is None:
            raise KeyError(wp_id)
        if c.execute("SELECT 1 FROM runs WHERE workpackage_id=? LIMIT 1", (wp_id,)).fetchone() is not None:
            raise NotReady("a work package with runs can only be archived",
                           [{"code": "has_runs", "message": "A csomagnak van futása: csak elrejthető."}])
        items = c.execute("SELECT COUNT(*) n FROM workpackage_items WHERE workpackage_id=?", (wp_id,)).fetchone()["n"]
        for table in ("workpackage_items", "recipe_assignments"):
            c.execute(f"DELETE FROM {table} WHERE workpackage_id=?", (wp_id,))
        c.execute("DELETE FROM workpackages WHERE id=?", (wp_id,))
        _event(c, wp_id, "delete", actor, {**dict(row), "items": items})


# --- recept-hozzárendelés ------------------------------------------------------------------------------


def current_assignment(wp_id: str) -> dict[str, Any] | None:
    with store.connect() as c:
        row = c.execute("SELECT * FROM recipe_assignments WHERE workpackage_id=? ORDER BY revision DESC LIMIT 1", (wp_id,)).fetchone()
    return {**dict(row), "params": json.loads(row["params"])} if row else None


def assignment_history(wp_id: str) -> list[dict[str, Any]]:
    with store.connect() as c:
        rows = c.execute("SELECT * FROM recipe_assignments WHERE workpackage_id=? ORDER BY revision", (wp_id,)).fetchall()
    return [{**dict(r), "params": json.loads(r["params"])} for r in rows]


def assign_recipe(wp_id: str, recipe_id: str, *, params: dict[str, Any], expected_revision: int, actor: str,
                  note: str | None = None) -> dict[str, Any]:
    """A hozzárendelés saját verziót kap (a V4 `expected_revision` mintája); a korábbiak előzményként maradnak."""
    r = recipe(recipe_id)
    clean = _validated_params(r, params)
    with store.connect() as c:
        _begin(c)
        if c.execute("SELECT 1 FROM workpackages WHERE id=?", (wp_id,)).fetchone() is None:
            raise KeyError(wp_id)
        cur = c.execute("SELECT MAX(revision) m FROM recipe_assignments WHERE workpackage_id=?", (wp_id,)).fetchone()["m"] or 0
        if cur != expected_revision:
            raise RevisionConflict(f"assignment of {wp_id} is at revision {cur}, not {expected_revision}")
        c.execute("INSERT INTO recipe_assignments VALUES (?,?,?,?,?,?,?,?,?)",
                  (wp_id, cur + 1, recipe_id, r["version"], recipe_hash(r), _canon(clean), actor, note, _now()))
    return current_assignment(wp_id)


# --- készenlét ---------------------------------------------------------------------------------------


def _input_snapshot(wp: dict[str, Any]) -> dict[str, Any]:
    items = [{"item_id": i["item_id"], "kind": i["kind"], "source_path": i["source_path"], "sha256": i["sha256"],
              **({"parent_item_id": i["parent_item_id"]} if i.get("parent_item_id") else {})} for i in wp["items"]]
    return {"workpackage_id": wp["id"], "workpackage_revision": wp["revision"], "items": items}


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    """A befagyasztott bemenet azonosítója (a készenlét `input_hash`-e)."""
    return hashlib.sha256(_canon(snapshot).encode("utf-8")).hexdigest()[:16]


def item_budget(r: dict[str, Any], params: dict[str, Any], kind: str | None = None, arm: str | None = None) -> dict[str, Decimal]:
    """Egy tétel keretmaximuma. A több tétel-fajtát kezelő recept (058 K5.2) fajtánként ad keretet
    (`max_item_usd_by_kind`); karnélküli részen a `*` sor érvényes. `arm` (066 Á07): a tétel előre ismert tényleges
    kara; nélküle a kért kar sora (a kért S-kar egy csak G-karos típuson G-n fut, ehhez a G sora kell)."""
    table = (r.get("max_item_usd_by_kind") or {}).get(kind or "") or r["max_item_usd"]
    per = table.get(arm or params.get("arm", "*"), table.get(params.get("arm", "*"), table.get("*", {})))
    out = {provider: Decimal(v) for provider, v in per.items()}
    for extra in r.get("param_item_usd") or []:  # 058 K5.3: paraméterhez kötött többlet (pl. feladatjavaslat a levélen)
        if params.get(extra["param"]) == extra["value"] and extra.get("kind") in (None, kind):
            for provider, v in extra["usd"].items():
                out[provider] = out.get(provider, Decimal(0)) + Decimal(v)
    return out


def run_budget(r: dict[str, Any], params: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Decimal]:
    """A futás keretmaximuma: a tételek keretének összege (tétel-fajtánként, 058 K5.2).

    065 döntés: a foglalás a tényleges út szerint. Ahol a tétel útja előre ismert és S (jelöltkereső + JEV), ott nincs
    OpenAI-foglalás: a számla-recepten a megadott típusból, az irat-feldolgozáson a korábban már felismert részletes
    típusból. Az ismeretlen típusú iratnál a legrosszabb eset marad. Ha az út mégis G lesz (például más típust ismer fel),
    a GPT-hívás a keret miatt nem indul, és a tétel teendőt kap (`llm:failed:BudgetExceeded`)."""
    from jav import typepack

    packs, known = set(typepack.keys()), _known_detail_types(items)
    out: dict[str, Decimal] = {}
    for i in items:
        arm = _item_arm(r, params, i, known, packs)
        per = item_budget(r, params, i.get("kind"), arm=arm)
        if arm == "S":
            per.pop("openai", None)
        for provider, v in per.items():
            out[provider] = out.get(provider, Decimal(0)) + v
    return out


def _known_detail_types(items: list[dict[str, Any]]) -> dict[str, str]:
    """A már felismert iratok részletes típusa (tartalomhash → típus), a `documents` táblából (065)."""
    ids = [i["sha256"] for i in items if i.get("kind") == "document" and i.get("sha256")]
    out: dict[str, str] = {}
    with store.connect() as c:
        for k in range(0, len(ids), 500):
            chunk = ids[k:k + 500]
            out.update({row["doc_id"]: row["detail_type"] for row in c.execute(
                f"SELECT doc_id, detail_type FROM documents WHERE detail_type IS NOT NULL AND doc_id IN ({','.join('?' * len(chunk))})", chunk)})
    return out


def _item_arm(r: dict[str, Any], params: dict[str, Any], item: dict[str, Any], known: dict[str, str], packs: set[str]) -> str | None:
    """A tétel előre ismert útja (S / G), vagy None, ha a típus a futás előtt nem ismert (065)."""
    from jav import typepack

    flow = flow_for(r, item.get("kind"))
    doc_type = params.get("doc_type") if flow == "invoice" else known.get(item.get("sha256", "")) if flow == "document" else None
    return typepack.resolve_arm(doc_type, params.get("arm", "auto")) if doc_type in packs else None


def flow_for(r: dict[str, Any], kind: str | None) -> str:
    """A tétel folyamata: a több tétel-fajtát kezelő recept fajtánként választ (`flows`), különben a recept folyamata."""
    return (r.get("flows") or {}).get(kind or "", r["flow"])


def readiness(wp_id: str, *, verify: bool = False) -> dict[str, Any]:
    """Futtatás előtti vizsgálat: akadályok (nem indítható) és figyelmeztetések, a rögzítendő bemenet hash-ével.
    `verify=True` (indításkor): a forrásfájlok teljes újraellenőrzése, a megjegyzett ujjlenyomat nélkül."""
    wp = get(wp_id)
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    a = wp["assignment"]
    if not wp["items"]:
        blockers.append({"code": "no_items", "message": "A munkacsomagban nincs tétel."})
    if a is None:
        blockers.append({"code": "no_recipe", "message": "Nincs hozzárendelt recept."})
    r = recipe(a["recipe_id"]) if a else None
    if r is not None and recipe_hash(r) != a["recipe_hash"]:
        warnings.append({"code": "recipe_changed", "message": "A recept a hozzárendelés óta változott; új hozzárendelés ajánlott."})
    for i in wp["items"]:
        p = Path(i["source_path"])
        if r is not None and (i["kind"] not in r["input_kinds"] or p.suffix.lower() not in r.get("file_suffixes", [p.suffix.lower()])):
            blockers.append({"code": "unsupported_item", "message": f"A recept nem kezeli: {p.name}"})
        if not p.exists():
            blockers.append({"code": "source_missing", "message": f"Hiányzó forrás: {p.name}"})
        elif fingerprint(p, verify=verify) != i["sha256"]:
            blockers.append({"code": "source_changed", "message": f"A forrás tartalma a felvétel óta változott: {p.name}"})
    snapshot = _input_snapshot(wp)
    budget = run_budget(r, a["params"], wp["items"]) if r is not None else {}
    return {"workpackage_id": wp_id, "ready": not blockers, "blockers": blockers, "warnings": warnings,
            "counts": {"items": len(wp["items"])}, "budget": budget,
            "assignment_revision": a["revision"] if a else 0,
            "input_hash": _snapshot_hash(snapshot)}


# --- futtatás ----------------------------------------------------------------------------------------


def start_run(wp_id: str, *, mode: str, expected_assignment_revision: int, input_hash: str, actor: str,
              rerun_of: str | None = None) -> dict[str, Any]:
    """Idempotens indítás rögzített bemenettel: tételenként egy munkasor-feladat, futásszintű költségkerettel.

    Újrafuttatás (057): azonos bemenetre és receptre az indítás a meglévő futást adja; a `rerun_of` (a megismételt
    futás) új futást kér. Ugyanarra a `rerun_of`-ra ismételt kérés is csak egy új futást ad (dupla kattintás ellen);
    futó futás nem ismételhető."""
    if mode not in ("shadow", "apply"):
        raise ValueError("mode must be shadow or apply")
    if rerun_of is not None:
        prev = get_run(rerun_of)
        if prev["workpackage_id"] != wp_id:
            raise ValueError("rerun_of belongs to another workpackage")
        if prev["status"] in ("queued", "running"):
            raise ValueError("run is still active; stop it before rerunning")
    ready = readiness(wp_id, verify=True)
    if ready["assignment_revision"] != expected_assignment_revision:
        raise RevisionConflict(f"assignment is at revision {ready['assignment_revision']}, not {expected_assignment_revision}")
    if ready["input_hash"] != input_hash:
        raise RevisionConflict("workpackage input changed since readiness check")
    if not ready["ready"]:
        raise NotReady("workpackage is not ready", ready["blockers"])
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    with store.connect() as c:
        _begin(c)
        # 066 Á19: a befagyasztott bemenet az írási zár alatt olvasva (közben más nem írhat), és pontosan az, amit a
        # készenlét-ellenőrzés látott; egy közbeni szerkesztés ütközés, nem ellenőrizetlen bemenetű futás
        wp = get(wp_id)
        a = wp["assignment"]
        snapshot = _input_snapshot(wp)
        if a["revision"] != expected_assignment_revision or _snapshot_hash(snapshot) != input_hash:
            raise RevisionConflict("workpackage changed while the run was being started")
        r = recipe(a["recipe_id"])
        dedup = f"{wp_id}:{a['revision']}:{input_hash}:{mode}" + (f":rerun:{rerun_of}" if rerun_of else "")
        existing = c.execute("SELECT run_id, input FROM runs WHERE dedup_key=?", (dedup,)).fetchone()
        if not existing:
            c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version, recipe_hash,"
                      " recipe, params, input, input_hash, status, actor, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?)",
                      (run_id, wp_id, dedup, mode, a["revision"], r["id"], r["version"], recipe_hash(r), _canon(r), _canon(a["params"]),
                       _canon(snapshot), input_hash, actor, _now()))
    if existing:
        # 063: ha az előző indítás a futás sora után megszakadt, az ismételt indítás pótolja a keretet és a feladatokat
        _ensure_run_work(existing["run_id"], json.loads(existing["input"])["items"], ready["budget"], replace_budget=False)
        return {"run_id": existing["run_id"], "deduped": True}
    _ensure_run_work(run_id, snapshot["items"], ready["budget"], replace_budget=True)
    return {"run_id": run_id, "deduped": False}


def _ensure_run_work(run_id: str, items: list[dict[str, Any]], budget: dict[str, Decimal], *, replace_budget: bool) -> None:
    """A futás kerete és tételenként egy munkasor-feladat. Idempotens: a feladat a `dedup_key`-en egyszer jön létre,
    a meglévő keret pótláskor nem változik (063)."""
    for provider, amount in budget.items():
        (calls.set_budget if replace_budget else calls.ensure_budget)(run_id, provider, amount)
    for item in items:
        queue.enqueue(JOB_KIND, run_id=run_id, dedup_key=f"{run_id}:{item['item_id']}",
                      payload={"run_id": run_id, "item_id": item["item_id"]})


def get_run(run_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        items = [dict(r) for r in c.execute("SELECT * FROM run_items WHERE run_id=? ORDER BY item_id", (run_id,))]
    out = dict(row)
    for k in ("recipe", "params", "input"):
        out[k] = json.loads(out[k])
    out["items"] = items
    out["jobs"] = queue.counts(run_id=run_id)
    return out


def run_rows(wp_id: str | None = None) -> list[dict[str, Any]]:
    """Futások lista-sorként, egy lekérdezéssel, levágás nélkül (056 U1 adatkészlet): csomagnév, tételszám, a lefutott
    tételek és a futás saját nyitott teendő-okai (a tétel folyamat-azonosítója `<futás>:` kezdetű)."""
    sql = ("SELECT r.run_id, r.workpackage_id, w.name AS workpackage_name, r.recipe_id, r.recipe_version, r.mode, r.status,"
           " r.approval, r.approved_by, r.actor, r.created_at, r.finished_at,"
           " json_array_length(r.input, '$.items') AS items,"
           " (SELECT COUNT(*) FROM run_items i WHERE i.run_id=r.run_id) AS items_done,"
           " (SELECT COUNT(*) FROM review_reasons x WHERE x.status='open' AND x.run_id LIKE r.run_id || ':%') AS open_reasons"
           " FROM runs r JOIN workpackages w ON w.id=r.workpackage_id")
    args: tuple = ()
    if wp_id is not None:
        sql, args = sql + " WHERE r.workpackage_id=?", (wp_id,)
    with store.connect() as c:
        rows = [dict(r) for r in c.execute(sql + " ORDER BY r.created_at DESC, r.rowid DESC", args)]
    for r in rows:  # 058: a frissítés nélkül lezárt teendők után tárolt „teendő vár” valójában kész (a munkasor már üres)
        if r["status"] == "needs_review" and not r["open_reasons"]:
            r["status"] = "done"
    return rows


def runs(wp_id: str) -> list[dict[str, Any]]:
    with store.connect() as c:
        ids = [r["run_id"] for r in c.execute("SELECT run_id FROM runs WHERE workpackage_id=? ORDER BY created_at DESC, rowid DESC", (wp_id,))]
    return [get_run(i) for i in ids]


def record_item_result(run_id: str, item_id: str, *, status: str, final_status: str | None = None,
                       flow_run_id: str | None = None, error: str | None = None) -> None:
    with store.connect() as c:
        c.execute("INSERT INTO run_items(run_id, item_id, status, final_status, flow_run_id, error, updated_at) VALUES (?,?,?,?,?,?,?)"
                  " ON CONFLICT(run_id, item_id) DO UPDATE SET status=excluded.status, final_status=excluded.final_status,"
                  " flow_run_id=excluded.flow_run_id, error=excluded.error, updated_at=excluded.updated_at",
                  (run_id, item_id, status, final_status, flow_run_id, error, _now()))


def flow_run_id(run_id: str, item_id: str) -> str:
    """A tétel folyamat-azonosítója (a feldolgozó ezzel építi a Burr-alkalmazást; a teendők ezt kapják `run_id`-ként)."""
    return f"{run_id}:{item_id[:16]}"


def review_subject(item: dict[str, Any]) -> tuple[str, str]:
    """A tétel teendőinek alanya: iratnál a tartalomhash; levélnél az üzenet-azonosító (= a levél mappájának neve,
    ezt írja a fogadó és ezt használja a levél-folyamat, 048 T2)."""
    if item.get("kind") == "email":
        return "email", Path(item["source_path"]).parent.name
    return "document", item["item_id"]


def is_own_reason(reason: dict[str, Any], own: str) -> bool:
    """A teendő-ok a tétel ebben a futásban felvett oka-e: a tétel folyamat-azonosítója alatt, vagy egy lépcsőjéé
    (`<azonosító>-<lépcső>`, pl. az irat-feldolgozás felismerése: `-doc_detect`; 066 Á02: eddig „korábbinak” számított)."""
    rid = reason.get("run_id") or ""
    return rid == own or rid.startswith(own + "-")


def item_reasons(run_id: str, item_id: str, item: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Egy tétel nyitott teendő-okai kettéválasztva: ebben a futásban keletkezett (`run`) és korábbi (`earlier`).

    A korábbi okok (régi mérési vagy korábbi futások ugyanazon az iraton) az iraton nyitva maradnak és látszanak, de nem
    ennek a futásnak az eredményéről szólnak, ezért a futás állapotát és jóváhagyását nem befolyásolják (040 K3 élő próba)."""
    if item is None:
        item = next((i for i in get_run(run_id)["input"]["items"] if i["item_id"] == item_id), {"item_id": item_id})
    return items_reasons(run_id, [{**item, "item_id": item_id}])[item_id]


def items_reasons(run_id: str, items: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Az `item_reasons` több tételre, egy adattár-lekérdezéssel (061: a listanézetek tételenkénti lekérdezése helyett)."""
    by_subject = store.review_open_reasons_many([review_subject(i) for i in items])
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for i in items:
        own = flow_run_id(run_id, i["item_id"])
        split: dict[str, list[dict[str, Any]]] = {"run": [], "earlier": []}
        for r in by_subject[review_subject(i)]:
            split["run" if is_own_reason(r, own) else "earlier"].append(r)
        out[i["item_id"]] = split
    return out


def open_reasons_for_run(run_id: str) -> int:
    """A futás SAJÁT nyitott teendő-okai (a tételek folyamat-azonosítójával felvett okok)."""
    run = get_run(run_id)
    return sum(len(s["run"]) for s in items_reasons(run_id, run["input"]["items"]).values())


def refresh_run_status(run_id: str) -> str:
    """A futás állapota a munkasorból és a teendőkből: fut → hibás / teendő vár / kész."""
    run = get_run(run_id)
    jobs = run["jobs"]
    # 063: a feladat nélküli tétel (félbemaradt indítás) is függőben van — a futás addig nem lehet „kész”
    missing = max(0, len(run["input"]["items"]) - sum(jobs.values()))
    pending = jobs.get("queued", 0) + jobs.get("claimed", 0) + missing
    if run["status"] == "cancelled":
        status = "cancelled"
    elif pending:
        status = "running" if (jobs.get("claimed") or any(v for k, v in jobs.items() if k in ("done", "dead"))) else "queued"
    elif jobs.get("dead"):
        status = "failed"
    elif jobs.get("cancelled"):
        status = "cancelled"
    else:
        status = "needs_review" if open_reasons_for_run(run_id) else "done"
    with store.connect() as c:
        # 066 Á32: a számolás és az írás között megszakított futás megszakított marad (a feltétel az írásban, nem előtte)
        c.execute("UPDATE runs SET status=?, finished_at=CASE WHEN ? IN ('queued','running') THEN NULL ELSE COALESCE(finished_at, ?) END"
                  " WHERE run_id=? AND (status <> 'cancelled' OR ? = 'cancelled')", (status, status, _now(), run_id, status))
        return c.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()["status"]


def resolve_reason(reason_id: int, *, actor: str, resolution: dict[str, Any] | None, note: str | None) -> dict[str, Any]:
    """Egy teendő-ok emberi lezárása, utána a gazda-futás állapotának frissítése (058: az utolsó ok lezárása után a
    futás „kész”, a lista jelvénye nem marad „teendő vár”). A korábbi mérésből származó ok gazdája nem futás."""
    with store.connect() as c:
        row = c.execute("SELECT status, run_id FROM review_reasons WHERE id=?", (reason_id,)).fetchone()
    if row is None:
        raise KeyError(reason_id)
    if row["status"] != "open":
        raise RevisionConflict(f"review reason {reason_id} is already {row['status']}")
    store.review_resolve(reason_id, actor=actor, resolution=resolution, note=note)
    owner = (row["run_id"] or "").split(":", 1)[0]
    run_status = None
    with store.connect() as c:
        hit = c.execute("SELECT status FROM runs WHERE run_id=?", (owner,)).fetchone()
    if hit is not None and hit["status"] in ("needs_review", "done"):
        run_status = refresh_run_status(owner)
    return {"reason_id": reason_id, "status": "resolved", "actor": actor, "run_status": run_status}


def cancel_run(run_id: str, *, actor: str | None = None) -> dict[str, int]:
    """Sorban álló tételek azonnal leállnak, a futó a következő lépéshatáron. 066 Á35: a szerző (ha van) a csomag
    eseménynaplójába kerül."""
    with store.connect() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM jobs WHERE run_id=? AND status IN ('queued','claimed')", (run_id,))]
        if actor is not None:
            wp_row = c.execute("SELECT workpackage_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if wp_row is not None:
                _event(c, wp_row["workpackage_id"], "run_cancel", actor, {"run_id": run_id})
    out: dict[str, int] = {}
    for job_id in ids:
        res = queue.cancel(job_id)
        out[res] = out.get(res, 0) + 1
    if not out.get("cancel_requested"):
        with store.connect() as c:
            c.execute("UPDATE runs SET status='cancelled', finished_at=? WHERE run_id=?", (_now(), run_id))
    return out


def approve_run(run_id: str, *, actor: str) -> dict[str, Any]:
    """Éles futás jóváhagyása: csak lezárt tételekkel és nyitott teendő nélkül; ki és mikor hagyta jóvá, rögzül."""
    run = get_run(run_id)
    if run["mode"] != "apply":
        raise ValueError("only apply runs can be approved")
    status = refresh_run_status(run_id)
    if status != "done":
        raise NotReady(f"run is {status}; approval needs a finished run without open review reasons")
    done = {i["item_id"] for i in get_run(run_id)["items"] if i["status"] == "done"}
    if any(i["item_id"] not in done for i in run["input"]["items"]):  # 063: minden bemeneti tételnek lefutott eredménye van
        raise NotReady("run has input items without a finished result")
    with store.connect() as c:
        c.execute("UPDATE runs SET approval='approved', approved_by=?, approved_at=? WHERE run_id=? AND approval IS NULL",
                  (actor, _now(), run_id))
    return get_run(run_id)
