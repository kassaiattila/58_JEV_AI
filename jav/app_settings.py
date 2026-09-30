"""Beállítások (057, döntés 2026-09-28): felhasználói névlista és figyelt munkamappák.

**Felhasználók:** a „Ki dolgozik?” választéka. Csak a helyi adattárban (a név személyes adat, gitbe nem kerül).

**Figyelt munkamappák** — a régi V4 „Figyelt mappák” működése szerint (`orchestrator/framework/intakeconfig.py`,
`scripts/intake_bridge.ps1`, csak olvasva): mappánként név, útvonal, bekapcsolt-e, almappák is, csomagolás
(`folder` = egy közös csomag, `daily` = napi csomagok), opcionális recept, átnézési gyakoriság. A feldolgozó
időközönként átnézi a mappát (`tick`), az új iratokból csomag lesz vagy a meglévő csomag bővül. Eltérések a régitől:
- az útvonal csak az engedélyezett gyökerek alatt lehet (a régi mentéskor nem ellenőrizte);
- a forrásmappa csak olvasva (nem mozgat, nem töröl), a még íródó fájl kimarad, amíg két átnézés között változik
  (a régi `watch.py` várakozása); a már látott fájl (útvonal + méret + módosítás ideje) nem hashelődik újra;
- a csomagból kézzel eltávolított irat nem kerül vissza; fizetős futás nem indul magától (a recept csak hozzárendelődik,
  mint a postafiókból érkező csomagnál, 048-as döntés).
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from jav import store, work
from jav.runtime import lock

log = logging.getLogger("jav.folders")

store.register_schema("app_settings", """
CREATE TABLE IF NOT EXISTS app_users (
    name        TEXT PRIMARY KEY COLLATE NOCASE,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watched_folders (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    path        TEXT NOT NULL,
    enabled     INTEGER NOT NULL,
    recursive   INTEGER NOT NULL,
    batch_mode  TEXT NOT NULL,                 -- folder | daily
    recipe_id   TEXT,
    params      TEXT NOT NULL,                 -- JSON
    interval_min INTEGER NOT NULL,
    next_at     TEXT,
    last_at     TEXT,
    last_status TEXT,                          -- ok | error
    last_result TEXT,                          -- JSON
    updated_at  TEXT NOT NULL
);
-- a mappa csomagjai: vödör = 'folder' vagy a nap (ÉÉÉÉ-HH-NN)
CREATE TABLE IF NOT EXISTS watched_packages (
    folder_id   TEXT NOT NULL,
    bucket      TEXT NOT NULL,
    workpackage_id TEXT NOT NULL,
    PRIMARY KEY (folder_id, bucket)
);
-- a már látott fájlok (útvonal + méret + módosítás ideje), hogy ne kelljen mindent újra hashelni
CREATE TABLE IF NOT EXISTS watched_seen (
    folder_id   TEXT NOT NULL,
    path        TEXT NOT NULL,
    size        INTEGER NOT NULL,
    mtime_ns    INTEGER NOT NULL,
    sha256      TEXT,
    PRIMARY KEY (folder_id, path)
);
""")

SUFFIXES = (".pdf",)
SETTLE_S = 10  # ennél frissebb módosítású fájl még íródhat: a következő átnézésre marad
DEFAULT_INTERVAL_MIN = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat(timespec="seconds")


# --- felhasználók -------------------------------------------------------------------------------------------


def users() -> list[str]:
    with store.connect() as c:
        return [r["name"] for r in c.execute("SELECT name FROM app_users ORDER BY name COLLATE NOCASE")]


def canonical_user(name: str) -> str | None:
    """061 (aktív felhasználó): a név a névlistán szereplő alakjában (kis-nagybetűtől és a szóközök számától
    függetlenül); a listán nem szereplő név None. Üres listánál bármely név elfogadott (első beállítás: a lista még nincs
    kitöltve, de a szerzőség akkor is kötelező)."""
    wanted = " ".join(name.split()).casefold()
    listed = users()
    if not listed:
        return " ".join(name.split())
    return next((u for u in listed if u.casefold() == wanted), None)


# A szerző-név szabálya (a helyi szolgáltatás `X-Actor` fejléce és a névlista közös szabálya, 066 Á25): betű (ékezettel
# is), szám, szóköz, pont, @ és kötőjel, legfeljebb 64 karakter.
ACTOR_RE = re.compile(r"^[\w.@ -]{1,64}$")


def save_users(names: list[str]) -> list[str]:
    """A teljes névlista cseréje. Üres és ismétlődő (kis-nagybetűtől függetlenül) név kimarad; 066 Á25: a szerző-szabálynak
    nem megfelelő név (amellyel utána semmit nem lehetne tenni) hiba, a lista nem változik."""
    clean: dict[str, str] = {}
    bad: list[str] = []
    for n in names:
        n = " ".join(str(n).split())
        if not n:
            continue
        if not ACTOR_RE.match(n):
            bad.append(n[:80])
            continue
        clean.setdefault(n.casefold(), n)
    if bad:
        raise ValueError("user names may contain letters, digits, space, dot, @ or hyphen (max 64): " + ", ".join(bad))
    if len(clean) > 200:
        raise ValueError("at most 200 users")
    with store.connect() as c:
        c.execute("DELETE FROM app_users")
        c.executemany("INSERT INTO app_users(name, created_at) VALUES (?,?)", [(n, _iso(_now())) for n in clean.values()])
    return users()


# --- figyelt munkamappák ------------------------------------------------------------------------------------


class WatchedFolder(BaseModel):
    """Egy figyelt mappa beállítása (a felület ezt küldi és kapja)."""

    id: str | None = Field(default=None, max_length=40)
    name: str = Field(default="", max_length=160)
    path: str = Field(min_length=1, max_length=1024)
    enabled: bool = True
    recursive: bool = False
    batch_mode: Literal["folder", "daily"] = "folder"
    recipe_id: str | None = Field(default=None, max_length=100)
    params: dict[str, str] = Field(default_factory=dict, max_length=20)
    interval_min: int = Field(default=DEFAULT_INTERVAL_MIN, ge=5, le=7 * 24 * 60)


def _folder_row(r: Any) -> dict[str, Any]:
    d = dict(r)
    d["enabled"], d["recursive"] = bool(d["enabled"]), bool(d["recursive"])
    d["params"] = json.loads(d["params"])
    d["last_result"] = json.loads(d["last_result"]) if d["last_result"] else None
    return d


def folders() -> list[dict[str, Any]]:
    with store.connect() as c:
        return [_folder_row(r) for r in c.execute("SELECT * FROM watched_folders ORDER BY name COLLATE NOCASE")]


def save_folders(items: list[WatchedFolder], *, check_dir: Callable[[str], Path]) -> list[dict[str, Any]]:
    """A teljes lista cseréje (a régi V4 PUT-ja szerint). `check_dir`: a szolgáltatás útvonal-ellenőrzése (engedélyezett
    gyökér alatt, létező mappa) — hibánál semmi nem mentődik. A megmaradó mappa átnézési ideje és eredménye megmarad."""
    if len(items) > 50:
        raise ValueError("at most 50 watched folders")
    known = {f["id"]: f for f in folders()}
    rows = []
    for f in items:
        p = check_dir(f.path)
        recipe_id = f.recipe_id or None
        if recipe_id is not None:
            work.recipe(recipe_id)  # ismeretlen recept: ValueError → 422
        fid = f.id if f.id in known else f"wf-{uuid.uuid4().hex[:10]}"
        prev = known.get(fid)
        name = " ".join(f.name.split()) or p.name
        rows.append((fid, name, str(p), int(f.enabled), int(f.recursive), f.batch_mode, recipe_id, json.dumps(f.params, ensure_ascii=False),
                     f.interval_min, (prev or {}).get("next_at") or _iso(_now()), (prev or {}).get("last_at"),
                     (prev or {}).get("last_status"), json.dumps((prev or {}).get("last_result")) if prev and prev.get("last_result") else None,
                     _iso(_now())))
    with store.connect() as c:
        c.execute("DELETE FROM watched_folders")
        c.executemany("INSERT INTO watched_folders(id, name, path, enabled, recursive, batch_mode, recipe_id, params, interval_min,"
                      " next_at, last_at, last_status, last_result, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return folders()


def _bucket(folder: dict[str, Any], now: datetime) -> str:
    return now.astimezone().strftime("%Y-%m-%d") if folder["batch_mode"] == "daily" else "folder"


def _package_for(folder: dict[str, Any], bucket: str) -> str | None:
    """A mappa (vagy a nap) élő csomagja. Az elrejtett vagy törölt csomagba nem kerül új irat (058): ilyenkor új csomag
    készül; a korábban látott fájlok a látott-listában maradnak, ezért nem kerülnek újra feldolgozásra."""
    with store.connect() as c:
        row = c.execute("SELECT p.workpackage_id FROM watched_packages p JOIN workpackages w ON w.id = p.workpackage_id"
                        " WHERE p.folder_id=? AND p.bucket=? AND w.status <> 'archived'", (folder["id"], bucket)).fetchone()
    return row["workpackage_id"] if row else None


def _new_files(folder: dict[str, Any], now: datetime) -> tuple[list[tuple[Path, str, os.stat_result]], int, int]:
    """(új fájlok tartalomhash-sel és állapottal, a még íródó fájlok száma, az olvashatatlan fájlok száma). A látott fájl
    nem hashelődik újra. 063: a „látott” jelölés itt nem íródik — csak a sikeres felvétel után (`_mark_seen`), és az
    olvashatatlan (pl. zárolt) fájl kimarad, nem szakítja meg az átnézést; mindkettő a következő átnézésre marad."""
    root = Path(folder["path"])
    walk = root.rglob("*") if folder["recursive"] else root.iterdir()
    out, settling, unreadable = [], 0, 0
    with store.connect() as c:
        seen = {r["path"]: r for r in c.execute("SELECT * FROM watched_seen WHERE folder_id=?", (folder["id"],))}
    for p in sorted(walk):
        if not p.is_file() or p.suffix.lower() not in SUFFIXES:
            continue
        rp = p.resolve()
        if not (rp == root or rp.is_relative_to(root)):  # a mappán kívülre mutató hivatkozás nem kerül be
            continue
        st = p.stat()
        if now.timestamp() - st.st_mtime < SETTLE_S:
            settling += 1
            continue
        prev = seen.get(str(rp))
        if prev and prev["size"] == st.st_size and prev["mtime_ns"] == st.st_mtime_ns:
            continue
        try:
            digest = work.sha256_file(rp)
        except OSError as exc:
            log.warning("watched folder %s: cannot read %s: %s", folder["id"], rp, exc)
            unreadable += 1
            continue
        out.append((rp, digest, st))
    return out, settling, unreadable


def _mark_seen(folder_id: str, files: list[tuple[Path, str, os.stat_result]]) -> None:
    with store.connect() as c:
        c.executemany("INSERT INTO watched_seen(folder_id, path, size, mtime_ns, sha256) VALUES (?,?,?,?,?) ON CONFLICT(folder_id, path)"
                      " DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns, sha256=excluded.sha256",
                      [(folder_id, str(rp), st.st_size, st.st_mtime_ns, digest) for rp, digest, st in files])


def scan(folder_id: str, *, now: datetime | None = None, actor: str = "figyelt mappa") -> dict[str, Any]:
    """Egy mappa átnézése most: az új iratok a mappa (vagy a nap) csomagjába kerülnek. Az eredmény a mappánál is rögzül.
    063: egy mappát egyszerre egy folyamat néz át (a „most” gomb és az ütemezett átnézés nem hozhat két csomagot)."""
    now = now or _now()
    folder = next((f for f in folders() if f["id"] == folder_id), None)
    if folder is None:
        raise KeyError(folder_id)
    with lock.try_exclusive(store.current_path().with_name(f"watch-{folder_id}.lock")) as got:
        if not got:
            return {"status": "busy", "error": "Az átnézés éppen folyamatban van; néhány másodperc múlva próbáld újra."}
        return _scan(folder, now, actor)


def _scan(folder: dict[str, Any], now: datetime, actor: str) -> dict[str, Any]:
    try:
        files, settling, unreadable = _new_files(folder, now)
        bucket = _bucket(folder, now)
        wp_id = _package_for(folder, bucket)
        existing = set()
        if wp_id:
            with store.connect() as c:  # a kézzel eltávolított irat is „ismert”: nem kerül vissza
                existing = {r["item_id"] for r in c.execute("SELECT item_id FROM workpackage_items WHERE workpackage_id=?", (wp_id,))}
        fresh = [p for p, digest, _st in files if digest not in existing]
        fresh = list(dict.fromkeys(fresh))
        if fresh:
            if wp_id is None:
                name = folder["name"] if bucket == "folder" else f"{folder['name']} — {bucket}"
                # 065: a „most” gombbal átnéző ember a felelős; az ütemezett átnézésnél nincs mentett név, ott üres marad
                wp = work.create_workpackage(name=name, source_kind="watch", source_ref=folder["path"],
                                             owner=None if actor == "figyelt mappa" else actor)
                wp_id = wp["id"]
                with store.connect() as c:
                    c.execute("INSERT INTO watched_packages(folder_id, bucket, workpackage_id) VALUES (?,?,?) ON CONFLICT(folder_id, bucket)"
                              " DO UPDATE SET workpackage_id=excluded.workpackage_id", (folder["id"], bucket, wp_id))
                if folder["recipe_id"]:
                    work.assign_recipe(wp_id, folder["recipe_id"], params=folder["params"], expected_revision=0, actor=actor,
                                       note="figyelt mappa")
            wp = work.get(wp_id)
            work.add_documents(wp_id, fresh, expected_revision=wp["revision"])
        _mark_seen(folder["id"], files)  # 063: csak a sikeres felvétel után „látott”
        result = {"new": len(fresh), "settling": settling, "unreadable": unreadable,
                  "workpackage": wp_id if fresh else _package_for(folder, bucket)}
        status = "ok"
    except (OSError, ValueError) as exc:
        result, status = {"error": str(exc)}, "error"
    except Exception as exc:  # noqa: BLE001 - 063: pl. egyidejű csomag-módosítás; a hiba a mappánál látszik, a fájlok maradnak
        log.exception("watched folder %s scan failed", folder["id"])
        result, status = {"error": f"{type(exc).__name__}: {exc}"}, "error"
    with store.connect() as c:
        c.execute("UPDATE watched_folders SET last_at=?, last_status=?, last_result=?, next_at=? WHERE id=?",
                  (_iso(now), status, json.dumps(result, ensure_ascii=False), _iso(now + timedelta(minutes=folder["interval_min"])), folder["id"]))
    return {"status": status, **result}


def tick(now: datetime | None = None) -> list[str]:
    """A feldolgozó körönként hívja: az esedékes, bekapcsolt mappák átnézése. Visszaadja az átnézett mappák azonosítóit."""
    now = now or _now()
    due = [f["id"] for f in folders() if f["enabled"] and (f["next_at"] or "") <= _iso(now)]
    for fid in due:
        scan(fid, now=now)
    return due


__all__ = ["WatchedFolder", "folders", "save_folders", "save_users", "scan", "tick", "users"]
