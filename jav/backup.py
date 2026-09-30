"""Adattár-mentés (063, döntés 2026-09-29: üzemi alapok): az SQLite-adattár konzisztens másolata, futó szolgáltatás és
feldolgozó mellett is.

A sima fájlmásolás WAL-módú, éppen írt adattárról hibás másolatot adhat, ezért az SQLite saját mentő eljárását
(`Connection.backup`) használjuk, és a másolaton lefut a sértetlenség-ellenőrzés (`PRAGMA integrity_check`). A mentés a
`store/backups/<időbélyeg>/` alá kerül (gitben nincs: `store/`), mellette `manifest.json` (méret, ellenőrzés). A
legutóbbi `keep` mentés marad, a régebbiek törlődnek (csak a saját időbélyeges mappák).

064 (döntés 2026-09-29): napi ütemezett mentés (`scheduled`, a `configs/service.json` `backup` szakasza szerint), a helyi
mentés után másolat a második helyre (NAS); a másolat tartalomhash-sel ellenőrzött, ott is a legutóbbi `keep` marad. A
másolás hibája nem érvényteleníti a helyi mentést, de látszik. Minden futás eredménye (a hibás is) a
`backup-status.json`-ba kerül, ezt mutatja a felület (Beállítások › Rendszer).

070 D-mentés (döntés 2026-09-30): a belső munkaanyag (`jav/doc_scope.py`: átadók, tervek, jelentések, teendőlista,
döntésnapló…) 2026-09-29 óta verziókövetés nélkül él helyben, ezért `with_docs` mellett a mentés mappájába egy
tömörített fájl is kerül (`internal-docs.zip`, a projektgyökérhez viszonyított nevekkel). A tömörített fájl
ellenőrzése ugyanúgy dönt a mentés érvényességéről, mint az adattáré; a második helyre készült másolat hash-e is lefedi.

Visszaállítás (kézi, a szolgáltatás és a feldolgozó leállítása után): a mentett `jav.sqlite` visszamásolása a
`store/` alá; részletek: `docs/guides/SETUP.md`, „Mentés, visszaállítás és napló”.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from jav import cfg, doc_scope, store
from jav.config import PROJECT_ROOT

KEEP = 7
STATUS_FILE = "backup-status.json"
DOCS_ARCHIVE = "internal-docs.zip"
_STAMP = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
log = logging.getLogger("jav.backup")


def default_root() -> Path:
    """A helyi mentések gyökere: az adattár mellett, `store/backups`."""
    return store.current_path().parent / "backups"


def backup(*, out_root: Path | None = None, with_burr: bool = False, keep: int | None = None,
           copy_to: Path | None = None, with_docs: bool = False, docs_root: Path | None = None) -> dict[str, Any]:
    """Az adattár (és kérésre a folyamat-állapotok tára és a belső munkaanyag) mentése, kérésre másolat a második
    helyre. A leírás (manifest) a mentés mappájában és az állapotfájlban is megmarad; hibánál az állapotfájl a hibát
    rögzíti.

    066: `keep` nélkül a napi mentés megőrzése (`configured_keep`; eddig a kézi mentés 7-re ritkított ugyanabban a
    mappában, ahol a napi 14-et tart). A sértetlenség-ellenőrzésen elbukott mentés után nincs ritkítás és másolás.
    070: `with_docs` a belső dokumentumokat is menti a `docs_root` (alapból a projektgyökér) alól."""
    root = Path(out_root) if out_root else default_root()
    keep = keep if keep is not None else configured_keep()
    try:
        manifest = _local(root, with_burr=with_burr, keep=keep, docs_root=(docs_root or PROJECT_ROOT) if with_docs else None)
    except Exception as exc:
        _write_status(root, {"created_at": _now(), "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        log.exception("backup failed")
        raise
    if not copy_to:
        manifest["copy"] = None
    elif manifest["ok"]:
        manifest["copy"] = _copy(Path(manifest["dir"]), Path(copy_to), keep)
    else:  # a hibás mentés ne szorítson ki jó mentést a második helyen sem
        manifest["copy"] = {"dir": None, "ok": False, "verified": False, "skipped": True,
                            "error": "skipped: the local backup failed its integrity check"}
    _write_status(root, manifest)
    log.info("backup %s: ok=%s copy=%s", manifest["dir"], manifest["ok"], manifest["copy"])
    return manifest


def configured_keep() -> int:
    """A napi mentés megőrzése (`configs/service.json` → `backup.keep`), ennek híján `KEEP`."""
    return int(cfg.load("service").get("backup", {}).get("keep", KEEP))


def scheduled(*, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """A napi, ütemezett mentés a beállítás szerint (`configs/service.json` → `backup`)."""
    c = config if config is not None else cfg.load("service").get("backup", {})
    copy_to = c.get("copy_to")
    return backup(keep=int(c.get("keep", KEEP)), copy_to=Path(copy_to) if copy_to else None, with_burr=bool(c.get("with_burr")),
                  with_docs=bool(c.get("with_docs")))


def status(root: Path | None = None) -> dict[str, Any] | None:
    """A legutóbbi mentés eredménye (az állapotfájlból); még nem volt mentés: None."""
    p = (Path(root) if root else default_root()) / STATUS_FILE
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _local(root: Path, *, with_burr: bool, keep: int, docs_root: Path | None = None) -> dict[str, Any]:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    src = store.current_path()
    if not src.is_file():
        raise ValueError(f"no store at {src}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = root / stamp
    n = 1
    while dest.exists():
        n += 1
        dest = root / f"{stamp}-{n}"
    dest.mkdir(parents=True)
    sources = [src]
    if with_burr:
        from jav.runtime import worker

        burr = worker.persister_path()
        if burr.is_file():
            sources.append(burr)
    files = []
    try:
        for f in sources:
            target = dest / f.name
            with closing(sqlite3.connect(str(f), timeout=30)) as s, closing(sqlite3.connect(str(target))) as d:
                s.backup(d)
                check = _integrity(d)
            files.append({"file": f.name, "source": str(f), "bytes": target.stat().st_size, "integrity": check})
        if docs_root is not None:
            docs = _archive_docs(docs_root, dest / DOCS_ARCHIVE)
            if docs:
                files.append(docs)
        manifest = {"created_at": _now(), "dir": str(dest), "files": files, "ok": all(x["integrity"] == "ok" for x in files)}
        (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)  # 066: félbemaradt mentés ne maradjon (a megőrzésbe sem számítana bele)
        raise
    manifest["removed"] = _prune(root, keep) if manifest["ok"] else []  # 066: hibás mentés után a jók megmaradnak
    return manifest


def _integrity(conn: sqlite3.Connection) -> str:
    """Az SQLite sértetlenség-ellenőrzése a mentett másolaton: `ok`, vagy az első hibasor."""
    return conn.execute("PRAGMA integrity_check").fetchone()[0]


def _archive_docs(docs_root: Path, target: Path) -> dict[str, Any] | None:
    """070: a belső dokumentumok egy tömörített fájlba; nincs belső dokumentum (friss klón): None."""
    docs = doc_scope.internal_doc_files(docs_root)
    if not docs:
        log.info("backup: no internal docs under %s", docs_root)
        return None
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in docs:
            z.write(p, p.relative_to(docs_root).as_posix())
    return {"file": target.name, "source": f"{docs_root / 'docs'} (belső munkaanyag)", "bytes": target.stat().st_size,
            "entries": len(docs), "integrity": _zip_integrity(target)}


def _zip_integrity(path: Path) -> str:
    """A tömörített fájl ellenőrzése (minden tag CRC-je): `ok`, vagy az első hibás tag."""
    try:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
    except zipfile.BadZipFile as exc:
        return f"bad archive: {exc}"
    return "ok" if bad is None else f"bad member: {bad}"


def _copy(src_dir: Path, target_root: Path, keep: int) -> dict[str, Any]:
    """064: a kész helyi mentés másolata a második helyre (pl. NAS), tartalomhash-sel ellenőrizve; ott is a legutóbbi
    `keep` marad. Hiba esetén a helyi mentés érvényes marad, a hiba a leírásba kerül."""
    target = target_root / src_dir.name
    try:
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_dir, target)
        verified = all(_sha256(f) == _sha256(target / f.name) for f in src_dir.iterdir() if f.is_file())
        if not verified:
            raise OSError(f"copy verification failed: {target}")
        return {"dir": str(target), "ok": True, "verified": True, "removed": _prune(target_root, keep)}
    except OSError as exc:
        log.warning("backup copy to %s failed: %s", target_root, exc)
        return {"dir": str(target), "ok": False, "verified": False, "error": f"{type(exc).__name__}: {exc}"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_status(root: Path, data: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / (STATUS_FILE + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(root / STATUS_FILE)


def _prune(root: Path, keep: int) -> list[str]:
    """A legutóbbi `keep` mentés marad; csak a saját, időbélyeg-nevű mappák törölhetők. A sértetlenség-ellenőrzésen
    elbukott mentés (066) nem számít bele és nem törlődik (a hiba vizsgálatához megmarad)."""
    dirs = sorted((p for p in root.iterdir() if p.is_dir() and _STAMP.match(p.name) and not _failed(p)), key=lambda p: p.name)
    removed = []
    for old in dirs[:-keep]:
        shutil.rmtree(old)
        removed.append(old.name)
    return removed


def _failed(backup_dir: Path) -> bool:
    """A mentés leírása szerint a sértetlenség-ellenőrzés hibát jelzett (leírás nélküli régi mappa: nem hibás)."""
    m = backup_dir / "manifest.json"
    if not m.is_file():
        return False
    try:
        return json.loads(m.read_text(encoding="utf-8")).get("ok") is False
    except (OSError, ValueError):
        return True  # olvashatatlan leírás: nem biztos, hogy jó mentés, ezért nem számít bele


__all__ = ["DOCS_ARCHIVE", "KEEP", "backup", "configured_keep", "default_root", "scheduled", "status"]
