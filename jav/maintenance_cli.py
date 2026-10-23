"""Command line, operations (202, plan G-core-generalisation M3a): the checks, the generated documents, the
store and its backup, the before/after comparison, the legacy import and the OCR cache. Registered by `jav.cli`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _refresh_jev_version() -> None:
    """200: the daily backup looks where JEV's moving name points (one tiny probe a day); a failure never fails the
    backup. The pinned version keeps answering; a newer one is only reported (`jav/jev_version.py`)."""
    import logging

    from jav import jev_version

    try:
        st = jev_version.refresh()
    except Exception:  # noqa: BLE001 - the look is a side task of the backup; logged with its traceback
        logging.getLogger("jav.backup").exception("JEV version look failed")
        return
    logging.getLogger("jav.backup").info("JEV version: %s", jev_version.verdict(st)[1])


def _refresh_deps_audit() -> None:
    """075: the daily backup also renews the dependency audit once it is a week old; a failure never fails the backup."""
    import logging

    from jav import deps_audit

    try:
        fresh = deps_audit.refresh_if_stale()
    except Exception:  # noqa: BLE001 - the audit is a side task of the backup; logged with its traceback
        logging.getLogger("jav.backup").exception("dependency audit failed")
        return
    if fresh is not None:
        logging.getLogger("jav.backup").info("dependency audit: %s", deps_audit.verdict(deps_audit.status())[1])


def cmd_flows(args: argparse.Namespace) -> int:
    """Burr contracts: lint (contract <-> live graph <-> source) + FLOW.md / FLOW.mmd generation under docs/flows/."""
    from jav import admin, contract

    all_ok = True
    for module, app in admin.flow_lint_targets():
        result = contract.lint_flow(module.CONTRACT, app, module)
        all_ok &= result["passed"]
        print(contract.format_report(result))
        if not args.check:
            paths = contract.write_artifacts(module.CONTRACT)
            print(f"  -> {paths['md']}")
        print()
    return 0 if all_ok else 1


def cmd_docs(args: argparse.Namespace) -> int:
    """Generated docs: docs/flows (contracts) + docs/callsites (JEV call sites) + docs/BANK_FILES.md (146)."""
    from jav import docsgen

    for p in docsgen.write_callsite_docs():
        print(f"  -> {p}")
    print(f"  -> {docsgen.write_bank_files_doc()}")
    args.check = False
    return cmd_flows(args)


def cmd_admin(args: argparse.Namespace) -> int:
    from jav.admin import admin_report, write_state

    if args.write:
        print(f"  -> {write_state()}")
        return 0
    print(admin_report())
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    from jav.preflight import preflight

    return preflight(skip_pytest=args.skip_pytest)


def cmd_data_guard(args: argparse.Namespace) -> int:
    from jav import data_guard
    from jav.core.config import PROJECT_ROOT

    found = data_guard.scan_tracked(PROJECT_ROOT, data_guard.load_guard(PROJECT_ROOT))
    print(data_guard.report(found, "a kiadás") or "adatőr: a verziókövetett fájlokban nincs találat")
    if args.all:  # the locations of the tolerated known values too (masked)
        for f in found:
            if f.known:
                print(f.describe())
    return 1 if data_guard.blocking(found) else 0


def cmd_lang_guard(args: argparse.Namespace) -> int:
    """073 language guard: no tracked file may gain Hungarian lines; see jav/lang_guard.py."""
    from jav import lang_guard
    from jav.core.config import PROJECT_ROOT

    if args.same_code:
        changed = lang_guard.changed_python_code(PROJECT_ROOT, args.same_code)
        for rel in changed:
            print(f"code changed: {rel}")
        print(f"{len(changed)} Python file(s) differ from {args.same_code} beyond comments and docstrings")
        return 1 if changed else 0
    guard = lang_guard.load_guard(PROJECT_ROOT)
    counts = lang_guard.scan(PROJECT_ROOT, guard)
    if args.init:
        if guard.baseline:
            print("the baseline is not empty; use --update (lower) or --accept PATH (raise one file)")
            return 1
        lang_guard.write_baseline(PROJECT_ROOT, counts)
        guard = lang_guard.load_guard(PROJECT_ROOT)
        print(f"baseline initialised: {sum(counts.values())} Hungarian lines in {len(counts)} files")
    elif args.update or args.accept:
        new = lang_guard.lowered_baseline(counts, guard, tuple(args.accept))
        lang_guard.write_baseline(PROJECT_ROOT, new)
        print(f"baseline: {sum(guard.baseline.values())} -> {sum(new.values())} Hungarian lines in {len(new)} files"
              + (f"; accepted: {', '.join(args.accept)}" if args.accept else ""))
        guard = lang_guard.load_guard(PROJECT_ROOT)
    over = lang_guard.excess(counts, guard)
    for e in over:
        print(f"{e.path}: {e.lines} Hungarian lines (allowed {e.limit})")
    print(f"language guard: {sum(counts.values())} Hungarian lines in {len(counts)} files, {len(over)} file(s) over the baseline")
    return 1 if over else 0


def cmd_deps_audit(args: argparse.Namespace) -> int:
    """075: known vulnerabilities in the pinned Python and UI packages (free; needs network); see jav/deps_audit.py."""
    from jav import deps_audit

    if not args.show:
        deps_audit.run()
    current = deps_audit.status()
    for f in [f for part in ("python", "npm") for f in ((current or {}).get(part) or {}).get("findings") or []]:
        print(f"{f['ecosystem']}: {f['package']} {f['version']} - {f['advisory']}"
              + (f" [{f['severity']}]" if f.get("severity") else "") + (f" (fix: {f['fix']})" if f.get("fix") else ""))
    ok, line = deps_audit.verdict(current)
    print(f"dependency audit: {line}")
    return 0 if ok and current is not None and not current["errors"] else 1


def cmd_before_after_snapshot(args: argparse.Namespace) -> int:
    """171 (plan 170, E0): the service's read views on a fresh copy of a backed-up store, written to a JSON-lines file
    (free: no AI call, no network). The file holds personal data: keep it outside git."""
    from jav import before_after

    try:
        counts = before_after.static_snapshot(Path(args.baseline), Path(args.work), Path(args.out),
                                              items=not args.no_items, matches=args.matches)
    except before_after.SnapshotError as exc:
        print(f"no snapshot: {exc}")
        return 2
    print(f"views read: {sum(counts.values())} ({', '.join(f'{k} {v}' for k, v in sorted(counts.items()))})")
    print(f"written: {args.out}")
    return 0


def cmd_before_after_replay(args: argparse.Namespace) -> int:
    """173 (plan 170, E0b): a sample of the backed-up store's items processed again on a fresh copy, from earlier
    answers only (free: placeholder keys, closed network, no budget); exit code 3 if a replayed run made a live call."""
    from jav import before_after, before_after_replay

    try:
        result = before_after_replay.running_snapshot(Path(args.baseline), Path(args.work), Path(args.out),
                                                      size=args.size, jev_cache=Path(args.jev_cache) if args.jev_cache else None)
    except before_after.SnapshotError as exc:
        print(f"no replay: {exc}")
        return 2
    print(f"replayed: {result['units']} units, {result['items']} items, {result['strata']} strata "
          f"({result['answered_strata']} with every earlier answer in the first round); {result['views']} views")
    print(f"answers missing (a to-do instead of a call): {result['missing_answers']}; "
          f"items ending as their original: {result['same_as_original']} of {result['items']}")
    unregistered = result["unregistered_todos"]  # 177: named, not a gate (the owner's decision)
    print(f"to-do kinds not in configs/todo_kinds.json: {', '.join(sorted(unregistered.values())) or 'none'}")
    print(f"written: {args.out}")
    if not result["passed"]:
        print(f"GATE FAILED: {result['live_calls']} calls were not earlier answers")
        for call in result["live"]:
            print(f"- {call['source']}: {call['run_id']} {call['step']} {call['provider']} {call['status']}")
        return 3
    print("gate passed: no live call")
    return 0


def cmd_before_after_diff(args: argparse.Namespace) -> int:
    """171 (plan 170, E0): the views missing on one side or differing between two snapshots; exit code 1 if any."""
    from jav import before_after

    differences = before_after.diff(Path(args.before), Path(args.after), limit=args.places)
    if not differences:
        print("no difference")
        return 0
    for kind, counts in sorted(before_after.summary(differences).items()):
        print(f"{kind}: {', '.join(f'{k} {v}' for k, v in sorted(counts.items()))}")
    for d in differences[: args.show]:
        print(f"- {d.key} [{d.kind}]")
        for place in d.places:
            print(f"    {place}")
    if len(differences) > args.show:
        print(f"... and {len(differences) - args.show} more views")
    return 1


def cmd_package_versions_backfill(args: argparse.Namespace) -> int:
    """171 (DECISIONS 171): the first released version of every package approved before v1.20.0, recorded now from its
    approved results and marked as recorded afterwards (idempotent; --dry-run writes nothing)."""
    from jav import package_release

    done = package_release.backfill(dry_run=args.dry_run)
    for e in done:
        print(f"{e['workpackage_id']}: {e['items']} items, approved by {e['released_by']} at {e['released_at']}"
              + (f" -> version {e['version']}" if "version" in e else " (dry run)"))
    print(f"packages: {len(done)}")
    return 0


def cmd_hooks_install(args: argparse.Namespace) -> int:
    from jav import data_guard
    from jav.core.config import PROJECT_ROOT

    print(data_guard.install_hooks(PROJECT_ROOT))
    return 0


def cmd_configs(args: argparse.Namespace) -> int:
    from jav.core import cfg

    print("| konfig | verzió | hash | utolsó changelog |\n|---|---|---|---|")
    for r in cfg.report():
        print(f"| {r['name']} | {r['version']} | `{r['hash']}` | {r['last']} |")
    return 0


def cmd_legacy_import(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav import legacy_import
    from jav.core.config import OLD_DATA_ROOT

    print(json.dumps(legacy_import.import_batches(Path(args.root) if args.root else OLD_DATA_ROOT / "output"), ensure_ascii=False))
    return 0


def cmd_legacy_compare(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav import legacy_import

    rep = legacy_import.compare()
    text = json.dumps(rep, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0


def cmd_reground(args: argparse.Namespace) -> int:
    from jav import reground

    for run_id in args.runs:
        print(run_id, json.dumps(reground.reground_run(run_id), ensure_ascii=False))
    return 0


def cmd_store(args: argparse.Namespace) -> int:
    from jav.core import store

    print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    from jav import backup
    from jav.core import applog

    if args.scheduled:  # 064: the daily scheduled backup, per the `backup` section of configs/service.json
        applog.setup("backup")
        m = backup.scheduled()
        _refresh_deps_audit()
        _refresh_jev_version()
    else:
        m = backup.backup(out_root=Path(args.out) if args.out else None, with_burr=args.with_burr, keep=args.keep,
                          copy_to=Path(args.copy_to) if args.copy_to else None, with_docs=args.with_docs)
    for f in m["files"]:
        entries = f" ({f['entries']} fájl)" if "entries" in f else ""
        print(f"{f['file']}{entries}: {f['bytes'] / 1e6:.1f} MB, ellenőrzés: {f['integrity']}")
    print(f"Mentés: {m['dir']}" + (f" (törölt régi mentések: {', '.join(m['removed'])})" if m.get("removed") else ""))
    copy = m.get("copy")
    if copy:
        print(f"Másolat: {copy['dir']} - " + ("ellenőrizve" if copy["ok"] else f"HIBA: {copy.get('error')}"))
    if not m["ok"]:
        return 1
    return 2 if copy and not copy["ok"] else 0


def cmd_burr_prune(args: argparse.Namespace) -> int:
    from jav.runtime import persistence, worker
    from jav.core import lock, queue

    path = worker.persister_path()
    active = queue.active_run_ids()
    before = path.stat().st_size if path.is_file() else 0
    out = persistence.prune_to_last(path, skip_prefixes=tuple(f"{r}:" for r in active))
    print(f"Ritkítva: {out['deleted']} köztes állapotsor törölve; kihagyott futó futás: {len(active)}.")
    if args.no_vacuum or not path.is_file():
        return 0
    if lock.is_held(worker.lock_path()):
        print("A feldolgozó fut: a tömörítés (a hely visszaadása a lemeznek) kimarad. "
              "Állítsd le (.\\scripts\\dev.ps1 stop), és futtasd újra a parancsot.")
        return 0
    v = persistence.vacuum(path)
    print(f"Tömörítve: {before / 1e6:.1f} MB -> {v['bytes_after'] / 1e6:.1f} MB")
    return 0


def cmd_ocr(args: argparse.Namespace) -> int:
    """OCR on one PDF (or the engine status): text source, quality signals, lines. For diagnosis: what the flow sees
    on a scanned invoice."""
    from jav.documents import ocr

    if not args.pdf:
        print(json.dumps(ocr.status(), ensure_ascii=False, indent=2))
        return 0
    from jav.documents.pdf import read_document

    pdf = read_document(args.pdf) if not args.force else ocr.ocr_pdf(args.pdf, use_cache=False, psm=args.psm)
    print(f"{pdf.path}: {pdf.page_count} oldal, {len(pdf.lines)} sor, szövegréteg={pdf.has_text_layer}, szöveg-forrás={pdf.text_source}")
    if pdf.ocr:
        print("OCR: " + json.dumps(pdf.ocr, ensure_ascii=False))
    for ln in pdf.layout[: args.limit or None]:
        print(f"L{ln.no:03d} p{ln.page}: {ln.text}")
    return 0


def cmd_ocr_rekey(args: argparse.Namespace) -> int:
    """076: a one-off move of the OCR cache to the current key (`jav/documents/ocr.py` `rekey_cache`); refuses if the older
    config differs in a setting that changes the recognised text."""
    import subprocess

    from jav.documents import ocr
    from jav.core.config import PROJECT_ROOT

    shown = subprocess.run(["git", "show", f"{args.from_rev}:configs/ocr.json"], capture_output=True, text=True,
                           encoding="utf-8", cwd=PROJECT_ROOT, check=False)
    if shown.returncode != 0:
        print(f"no configs/ocr.json at {args.from_rev}: {shown.stderr.strip()}")
        return 2
    try:
        moved = ocr.rekey_cache(json.loads(shown.stdout))
    except ValueError as exc:
        print(f"refused: {exc}")
        return 1
    print(f"OCR cache: {moved} file(s) moved to the key {ocr.CACHE_HASH}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("flows", help="Burr-kontraktok lintje + FLOW.md / FLOW.mmd generálás (docs/flows/)")
    p.add_argument("--check", action="store_true", help="csak lint, fájlírás nélkül")
    p.set_defaults(fn=cmd_flows)
    p = sub.add_parser("docs", help="generated docs: docs/callsites/ (JEV call sites) + docs/flows/ (contracts) + docs/BANK_FILES.md (bank files)")
    p.set_defaults(fn=cmd_docs)
    p = sub.add_parser("admin", help="egy képernyő: konfigok, modellek, flow-lint, store, utolsó golden-eredmények, review-sor")
    p.add_argument("--write", action="store_true", help="a képernyő fájlba: docs/STATE.md (generált állapot-pillanatkép)")
    p.set_defaults(fn=cmd_admin)
    p = sub.add_parser("preflight", help="session-indító ellenőrzés API nélkül: pytest, kontrakt-lint, konfigok, handoff-frissesség, STATE.md")
    p.add_argument("--skip-pytest", action="store_true")
    p.set_defaults(fn=cmd_preflight)
    p = sub.add_parser("data-guard", help="071 adatőr: a verziókövetett fájlok átnézése (személyes adat, kulcs, belső anyag)")
    p.add_argument("--all", action="store_true", help="a tűrt ismert értékek helyét is kiírja (maszkolva)")
    p.set_defaults(fn=cmd_data_guard)
    p = sub.add_parser("lang-guard", help="073 language guard: tracked files may not gain Hungarian lines (baseline: configs/lang_guard.json)")
    p.add_argument("--init", action="store_true", help="take the current counts as the first baseline (only when it is empty)")
    p.add_argument("--update", action="store_true", help="lower the baseline to the current counts after a conversion step")
    p.add_argument("--accept", action="append", default=[], metavar="PATH",
                   help="raise one file to its current count (document vocabulary, test data); repeatable")
    p.add_argument("--same-code", metavar="REV", help="list .py files whose code differs from REV beyond comments and docstrings")
    p.set_defaults(fn=cmd_lang_guard)
    p = sub.add_parser("deps-audit", help="075: known vulnerabilities in the pinned Python and UI packages (pip-audit, npm audit; needs network)")
    p.add_argument("--show", action="store_true", help="only show the last result (runs/deps-audit.json), without a new audit")
    p.set_defaults(fn=cmd_deps_audit)
    p = sub.add_parser("before-after-snapshot", help="171: the service's read views on a fresh copy of a backed-up store, "
                                                     "for the before/after comparison of a refactoring step (free)")
    p.add_argument("baseline", help="a backup folder (python -m jav.cli backup) or a store file")
    p.add_argument("--work", required=True, help="the folder of the fresh copy (replaced; outside git)")
    p.add_argument("--out", required=True, help="the snapshot file to write (JSON lines; personal data, outside git)")
    p.add_argument("--no-items", action="store_true", help="leave out the item results of every run (faster)")
    p.add_argument("--matches", action="store_true", help="also the proposed pairs of every reconciliation line (slow)")
    p.set_defaults(fn=cmd_before_after_snapshot)
    p = sub.add_parser("before-after-replay", help="173: a sample of the backed-up store's items processed again on a fresh copy, "
                                                   "from earlier answers only, for the before/after comparison (free)")
    p.add_argument("baseline", help="a backup folder (python -m jav.cli backup) or a store file")
    p.add_argument("--work", required=True, help="the folder of the fresh copy (replaced; outside git; the same for both replays)")
    p.add_argument("--out", required=True, help="the replay file to write (JSON lines; personal data, outside git)")
    p.add_argument("--size", type=int, default=150, help="about how many units to replay (default 150; every stratum at least once)")
    p.add_argument("--jev-cache", help="the JEV answer cache to read (default: runs/cache)")
    p.set_defaults(fn=cmd_before_after_replay)
    p = sub.add_parser("before-after-diff", help="171: the views that differ between two snapshots (exit code 1 if any)")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--show", type=int, default=30, help="the number of differing views listed (default 30)")
    p.add_argument("--places", type=int, default=8, help="the differing places listed per view (default 8)")
    p.set_defaults(fn=cmd_before_after_diff)
    p = sub.add_parser("package-versions-backfill", help="171: the first released version of every package approved before"
                                                         " v1.20.0, recorded afterwards (idempotent)")
    p.add_argument("--dry-run", action="store_true", help="list the packages, write nothing")
    p.set_defaults(fn=cmd_package_versions_backfill)
    p = sub.add_parser("hooks-install", help="071 adatőr: a verziózott git-horgok bekapcsolása (core.hooksPath = scripts/githooks)")
    p.set_defaults(fn=cmd_hooks_install)
    p = sub.add_parser("configs", help="konfig mint adat: configs/*.json verziók és config_hash-ek")
    p.set_defaults(fn=cmd_configs)
    p = sub.add_parser("legacy-import", help="047: a régi projekt köteg-exportjai (csak olvasva) a legacy_results táblába, ujjlenyomat szerint")
    p.add_argument("--root", help="a régi data/output mappa (alap: JAV_LEGACY_ROOT/data/output)")
    p.set_defaults(fn=cmd_legacy_import)
    p = sub.add_parser("legacy-compare", help="047: az új és a régi eredmény összevetése (egyezés, nem pontosság)")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_legacy_compare)
    p = sub.add_parser("reground", help="053: a futás(ok) forráshelyének újraszámolása (mező- és tételsor-keretek; AI-hívás nélkül)")
    p.add_argument("runs", nargs="+")
    p.set_defaults(fn=cmd_reground)
    p = sub.add_parser("store", help="adattár statisztika (documents, datapoints, review_queue, ledger)")
    p.set_defaults(fn=cmd_store)
    p = sub.add_parser("backup", help="063: az adattár mentése futás közben is (SQLite-mentés + sértetlenség-ellenőrzés), store/backups/ alá")
    p.add_argument("--out", help="a mentések gyökere (alapból store/backups)")
    p.add_argument("--with-burr", action="store_true", help="a folyamat-állapotok tára (store/burr_state.sqlite, nagy) is")
    p.add_argument("--with-docs", action="store_true", help="070: a belső munkaanyag (jav/core/doc_scope.py) is, internal-docs.zip")
    p.add_argument("--keep", type=int, default=None, help="ennyi legutóbbi mentés marad (alapból a napi mentésé: configs/service.json backup.keep)")
    p.add_argument("--copy-to", help="064: a kész mentés ellenőrzött másolata ide is (pl. NAS-mappa); ott is a --keep marad")
    p.add_argument("--scheduled", action="store_true", help="064: a napi ütemezett mentés a configs/service.json backup szakasza szerint")
    p.set_defaults(fn=cmd_backup)
    p = sub.add_parser("burr-prune", help="064: a folyamatállapot-tár ritkítása (folyamatonként csak az utolsó állapot) és tömörítése")
    p.add_argument("--no-vacuum", action="store_true", help="csak ritkítás, tömörítés nélkül (a fájl mérete ekkor nem csökken)")
    p.set_defaults(fn=cmd_burr_prune)
    p = sub.add_parser("ocr", help="OCR-lánc: egy PDF felismert szövege és minőségjelei (gyorsítótárból, --force: újra), PDF nélkül a motor állapota")
    p.add_argument("pdf", nargs="?")
    p.add_argument("--force", action="store_true", help="gyorsítótár nélkül újra OCR-ezi (a cache-t nem írja)")
    p.add_argument("--psm", type=int, default=None, help="tesseract oldalfelbontási mód (alap: configs/ocr.json)")
    p.add_argument("--limit", type=int, default=0, help="csak az első N sor")
    p.set_defaults(fn=cmd_ocr)
    p = sub.add_parser("ocr-rekey", help="076: move the OCR cache written under an older configs/ocr.json to the current "
                                         "key, if the older file's output settings are the same (no new OCR)")
    p.add_argument("--from-rev", required=True, help="git revision holding the older configs/ocr.json (e.g. v1.1.0)")
    p.set_defaults(fn=cmd_ocr_rekey)
