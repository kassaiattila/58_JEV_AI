"""Store backup (063, decision of 2026-09-29: operational basics): a consistent copy of the SQLite store, even while
the service and the worker are running.

A plain file copy of a WAL-mode store that is being written can produce a corrupt copy, so we use SQLite's own backup
procedure (`Connection.backup`), and the integrity check (`PRAGMA integrity_check`) runs on the copy. The backup goes
under `store/backups/<timestamp>/` (not in git: `store/`), with a `manifest.json` beside it (size, check). The latest
`keep` backups are kept and older ones are deleted (only our own timestamped folders).

064 (decision of 2026-09-29): a daily scheduled backup (`scheduled`, driven by the `backup` section of
`configs/service.json`); after the local backup, a copy goes to a second location (NAS); the copy is verified by content
hash, and there too the latest `keep` backups are kept. A copy failure does not invalidate the local backup, but it is
visible. The result of every run (failed ones too) is written to `backup-status.json`, which the UI shows
(Settings › System).

070 D-mentés (decision of 2026-09-30): the internal working documents (`jav/doc_scope.py`: handoffs, plans, reports,
backlog, decisions log…) have lived locally without version control since 2026-09-29, so with `with_docs` a compressed
archive is also written into the backup folder (`internal-docs.zip`, with names relative to the project root). The
archive's check decides the backup's validity just as the store's does; the hash check of the copy in the second
location covers it too.

Source instances (the unchanging copies of the documents added to work packages, `jav/source_instances.py`) go into
one shared `sources/` folder beside the timestamped backup folders, in the local root and in the second location alike:
each instance is copied once, checked against its content hash (its file name), and never pruned, because instances
never change. A damaged instance is not copied and is named in the manifest.

090 (audit of 2026-10-02, N05): the check starts from the instances the saved store copy refers to (`required`), not
only from the files found in the instance folder. A referenced instance that is missing or damaged in the store but
already verified in the backup is `preserved`; one that is in neither is `missing`, which fails the backup (it could
not be restored), names the instances in the status line and stops pruning in both locations. The store copy itself
is valid, so it still goes to the second location, without pruning there.

Restore (manual, after stopping the service and the worker): copy the saved `jav.sqlite` back under `store/`, and the
`sources/` folder back to `store/sources/`; details: `docs/guides/SETUP.md`, "Backup, restore and logs".
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from jav import cfg, doc_scope, source_instances, store
from jav.config import PROJECT_ROOT

KEEP = 7
STATUS_FILE = "backup-status.json"
DOCS_ARCHIVE = "internal-docs.zip"
SOURCES_DIR = "sources"
NATIVE_ARCHIVE = "native-artifacts.zip"
_STAMP = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
log = logging.getLogger("jav.backup")


def default_root() -> Path:
    """Root of the local backups: next to the store, `store/backups`."""
    return store.current_path().parent / "backups"


def backup(*, out_root: Path | None = None, with_burr: bool = False, keep: int | None = None,
           copy_to: Path | None = None, with_docs: bool = False, docs_root: Path | None = None) -> dict[str, Any]:
    """Back up the store (and, on request, the flow-state store and the internal working documents), with an optional
    copy to a second location. The manifest is kept both in the backup folder and in the status file; on failure the
    status file records the error.

    066: without `keep`, the daily backup's retention applies (`configured_keep`; previously a manual backup pruned to 7
    in the same folder where the daily one keeps 14). After a backup that fails its integrity check there is no pruning
    and no copying.
    070: `with_docs` also backs up the internal documents from under `docs_root` (the project root by default)."""
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
    elif manifest["store_ok"]:  # 090: a valid store copy goes there even with missing sources, but prunes nothing
        manifest["copy"] = _copy(Path(manifest["dir"]), Path(copy_to), keep, prune=manifest["ok"])
    else:  # a failed backup must not push out a good one in the second location either
        manifest["copy"] = {"dir": None, "ok": False, "verified": False, "skipped": True,
                            "error": "skipped: the local backup failed its integrity check"}
    _write_status(root, manifest)
    log.info("backup %s: ok=%s copy=%s", manifest["dir"], manifest["ok"], manifest["copy"])
    return manifest


def configured_keep() -> int:
    """Retention of the daily backup (`configs/service.json` → `backup.keep`), or `KEEP` if unset."""
    return int(cfg.load("service").get("backup", {}).get("keep", KEEP))


COPY_TO_ENV = "JAV_BACKUP_COPY_TO"


def configured_copy_to() -> str | None:
    """The second backup location: `configs/service.json` → `backup.copy_to`, or, since 076, the `JAV_BACKUP_COPY_TO`
    environment variable (`.env`), so that a machine-specific path stays out of the tracked config."""
    return cfg.load("service").get("backup", {}).get("copy_to") or os.environ.get(COPY_TO_ENV) or None


def scheduled(*, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """The daily scheduled backup, as configured (`configs/service.json` → `backup`, the second location also from the
    environment). An explicit `config` is used as given, without the environment."""
    c = config if config is not None else cfg.load("service").get("backup", {})
    copy_to = c.get("copy_to") if config is not None else configured_copy_to()
    return backup(keep=int(c.get("keep", KEEP)), copy_to=Path(copy_to) if copy_to else None, with_burr=bool(c.get("with_burr")),
                  with_docs=bool(c.get("with_docs")))


def status(root: Path | None = None) -> dict[str, Any] | None:
    """Result of the latest backup (from the status file); None if there has been no backup yet."""
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
        store_ok = all(x["integrity"] == "ok" for x in files)
        instances = source_instances.files()
        required = _referenced_instances(dest / src.name)
        if instances or required:
            files.append(_sync_sources(instances, source_instances.root(), root / SOURCES_DIR, required=required))
        native = _archive_native(dest / src.name, src.parent, dest / NATIVE_ARCHIVE)
        if native is not None:
            files.append(native)
        manifest = {"created_at": _now(), "dir": str(dest), "files": files, "store_ok": store_ok,
                    "ok": all(x["integrity"] == "ok" for x in files)}
        if not manifest["ok"]:  # 090: the status line says what failed (an integrity failure has no exception text)
            manifest["error"] = "; ".join(f"{x['file']}: {x['integrity']}" for x in files if x["integrity"] != "ok")
        (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)  # 066: remove a half-finished backup (it would not count for retention)
        raise
    manifest["removed"] = _prune(root, keep) if manifest["ok"] else []  # 066: no pruning after a failed backup
    return manifest


def _integrity(conn: sqlite3.Connection) -> str:
    """SQLite's integrity check on the saved copy: `ok`, or the first error line."""
    return conn.execute("PRAGMA integrity_check").fetchone()[0]


def _referenced_instances(saved_store: Path) -> set[str]:
    """090 (N05): the source instances the saved store copy refers to (relative paths), read from the copy, so an
    instance added after the copy was taken is not required by it. A store without work packages refers to none."""
    with closing(sqlite3.connect(str(saved_store))) as c:
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workpackage_items'").fetchone() is None:
            return set()
        refs = {r[0] for r in c.execute("SELECT DISTINCT instance FROM workpackage_items WHERE instance IS NOT NULL")}
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone():
            for row in c.execute("SELECT input FROM runs"):
                refs.update(item["instance"] for item in json.loads(row[0])["items"] if item.get("instance"))
        return refs


def _archive_docs(docs_root: Path, target: Path) -> dict[str, Any] | None:
    """070: the internal documents into one compressed archive; None if there are none (fresh clone)."""
    docs = doc_scope.internal_doc_files(docs_root)
    if not docs:
        log.info("backup: no internal docs under %s", docs_root)
        return None
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in docs:
            z.write(p, p.relative_to(docs_root).as_posix())
    return {"file": target.name, "source": f"{docs_root / 'docs'} (belső munkaanyag)", "bytes": target.stat().st_size,
            "entries": len(docs), "integrity": _zip_integrity(target)}


def _archive_native(saved_store: Path, source_root: Path, target: Path) -> dict[str, Any] | None:
    """Archive the complete immutable reader artifacts referenced by the saved database snapshot."""
    from jav import native_results

    try:
        with closing(sqlite3.connect(str(saved_store))) as c:
            c.row_factory = sqlite3.Row
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_readings'").fetchone():
                return None
            refs = native_results.referenced_artifacts(c)
    except (OSError, ValueError) as exc:
        return {"file": target.name, "source": str(source_root), "bytes": 0, "entries": 0,
                "integrity": f"{type(exc).__name__}: {exc}", "artifacts": []}
    if not refs:
        return None
    manifest = [ref.model_dump(mode="json") for ref in refs]
    total = 0
    try:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for ref in refs:
                relative = Path(ref.relative_path)
                source = (source_root / relative).resolve()
                if relative.is_absolute() or ".." in relative.parts or not source.is_relative_to(source_root.resolve()):
                    raise ValueError("Native artifact reference escapes the store")
                data = source.read_bytes()
                if len(data) != ref.byte_size or hashlib.sha256(data).hexdigest() != ref.sha256:
                    raise ValueError(f"Native artifact is damaged: {ref.relative_path}")
                archive.writestr(relative.as_posix(), data)
                total += len(data)
        integrity = _zip_integrity(target)
    except (OSError, ValueError) as exc:
        integrity = f"{type(exc).__name__}: {exc}"
    return {"file": target.name, "source": str(source_root), "bytes": total, "entries": len(refs),
            "integrity": integrity, "artifacts": manifest}


def _zip_integrity(path: Path) -> str:
    """Check of the compressed archive (the CRC of every member): `ok`, or the first bad member."""
    try:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
    except zipfile.BadZipFile as exc:
        return f"bad archive: {exc}"
    return "ok" if bad is None else f"bad member: {bad}"


def _copy(src_dir: Path, target_root: Path, keep: int, *, prune: bool = True) -> dict[str, Any]:
    """064: copy of the finished local backup to the second location (e.g. NAS), verified by content hash; there too
    the latest `keep` backups are kept. On failure the local backup stays valid and the error goes into the manifest.
    090: without `prune` (the local backup misses a referenced source instance) nothing is deleted there."""
    target = target_root / src_dir.name
    try:
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_dir, target)
        verified = all(_sha256(f) == _sha256(target / f.name) for f in src_dir.iterdir() if f.is_file())
        if not verified:
            raise OSError(f"copy verification failed: {target}")
        local_sources = src_dir.parent / SOURCES_DIR
        instances = _instance_files(local_sources)
        sources = _sync_sources(instances, local_sources, target_root / SOURCES_DIR) if instances else None
        if sources is not None and sources["integrity"] != "ok":
            raise OSError(sources["integrity"])
        return {"dir": str(target), "ok": True, "verified": True, "removed": _prune(target_root, keep) if prune else [],
                "sources": sources}
    except OSError as exc:
        log.warning("backup copy to %s failed: %s", target_root, exc)
        return {"dir": str(target), "ok": False, "verified": False, "error": f"{type(exc).__name__}: {exc}"}


def _instance_files(root: Path) -> list[Path]:
    """The instance files of a `sources/` folder (a half-written `.part` file is not one)."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("??/*") if p.is_file() and not p.name.endswith(".part"))


def _sync_sources(instances: list[Path], src_root: Path, dest_root: Path, *, required: set[str] | None = None) -> dict[str, Any]:
    """Copies the source instances not yet in `dest_root` (shared by every backup there, never pruned). A new copy is
    checked against the content hash in its name before it takes its place. 085 (re-audit A02): a copy already there
    is checked by its content hash too (not only by its size); a damaged one is replaced from the intact source
    instance (`repaired`). A damaged source instance is not copied and is named (`damaged`); if the copy in the backup
    is damaged as well, nothing intact is left there, so the entry's integrity is an error. A copy failure is an error
    too. 090 (N05): every `required` instance (relative path) must end up intact in `dest_root`: one not among the
    files found but already intact there is `preserved`; one in neither place is `missing`, an error as well."""
    added, total, damaged, repaired, lost = 0, 0, [], [], []
    safe: set[str] = set()  # relative paths with an intact copy in `dest_root`
    try:
        for f in instances:
            rel = f.relative_to(src_root)
            target = dest_root / rel
            size = f.stat().st_size
            digest = f.name.split(".", 1)[0]
            present = target.is_file()
            if present and source_instances.intact(target, digest):
                total += size
                safe.add(rel.as_posix())
                continue
            if not source_instances.intact(f, digest):
                damaged.append(f.name)
                if present:
                    lost.append(f.name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".part")
            shutil.copyfile(f, part)
            if _sha256(part) != digest:
                part.unlink(missing_ok=True)
                raise OSError(f"copy verification failed: {target}")
            os.replace(part, target)
            if present:
                repaired.append(f.name)
                log.warning("backup: the saved copy %s was damaged; replaced from the intact source instance", target)
            else:
                added += 1
            total += size
            safe.add(rel.as_posix())
        preserved, missing = _check_required(required or set(), safe, dest_root)
        problems = [f"damaged copy without an intact source: {', '.join(lost)}"] if lost else []
        if missing:
            problems.append(f"referenced source instances missing: {len(missing)} ({', '.join(missing)})")
            log.warning("backup: %d referenced source instance(s) are neither in the store nor in %s", len(missing), dest_root)
        integrity = "; ".join(problems) or "ok"
    except OSError as exc:
        log.warning("backup of the source instances to %s failed: %s", dest_root, exc)
        integrity = f"copy failed: {type(exc).__name__}: {exc}"
        preserved, missing = [], []
    return {"file": SOURCES_DIR, "source": str(src_root), "bytes": total, "entries": len(instances) - len(damaged),
            "added": added, "repaired": repaired, "damaged": damaged, "required": len(required or ()),
            "preserved": preserved, "missing": missing, "integrity": integrity}


def _check_required(required: set[str], safe: set[str], dest_root: Path) -> tuple[list[str], list[str]]:
    """090 (N05): the referenced instances without a verified copy from this run: (`preserved`, intact in `dest_root`
    from an earlier backup; `missing`, intact nowhere). A recorded path of a foreign shape counts as missing."""
    preserved, missing = [], []
    for rel in sorted(required - safe):
        try:
            source_instances.path_of(rel)  # only the store's own shape (it cannot point outside the folder)
        except ValueError:
            missing.append(rel)
            continue
        if source_instances.intact(dest_root / rel, Path(rel).name.split(".", 1)[0]):
            preserved.append(rel)
        else:
            missing.append(rel)
    return preserved, missing


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
    """The latest `keep` backups are kept; only our own timestamp-named folders may be deleted. A backup that failed its
    integrity check (066) does not count and is not deleted (it is kept for investigating the failure)."""
    dirs = sorted((p for p in root.iterdir() if p.is_dir() and _STAMP.match(p.name) and not _failed(p)), key=lambda p: p.name)
    removed = []
    for old in dirs[:-keep]:
        shutil.rmtree(old)
        removed.append(old.name)
    return removed


def _failed(backup_dir: Path) -> bool:
    """The backup's manifest says the integrity check failed (an old folder without a manifest: not failed)."""
    m = backup_dir / "manifest.json"
    if not m.is_file():
        return False
    try:
        return json.loads(m.read_text(encoding="utf-8")).get("ok") is False
    except (OSError, ValueError):
        return True  # unreadable manifest: not necessarily a good backup, so it does not count


__all__ = ["DOCS_ARCHIVE", "KEEP", "backup", "configured_keep", "default_root", "scheduled", "status"]
