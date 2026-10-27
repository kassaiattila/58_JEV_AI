"""Command line, operations (202, plan G-core-generalisation M3a): the checks, the generated documents, the
store and its backup, the before/after comparison, the legacy import and the OCR cache. Registered by `jav.cli`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jav.cli.cli_options import budget_args


def _refresh_jev_version() -> None:
    """200: the daily backup looks where JEV's moving name points (one tiny probe a day); a failure never fails the
    backup. The pinned version keeps answering; a newer one is only reported (`jav/ai/jev_version.py`)."""
    import logging

    from jav.ai import jev_version

    try:
        st = jev_version.refresh()
    except Exception:  # noqa: BLE001 - the look is a side task of the backup; logged with its traceback
        logging.getLogger("jav.runtime.backup").exception("JEV version look failed")
        return
    logging.getLogger("jav.runtime.backup").info("JEV version: %s", jev_version.verdict(st)[1])


def _refresh_deps_audit() -> None:
    """075: the daily backup also renews the dependency audit once it is a week old; a failure never fails the backup."""
    import logging

    from jav.runtime import deps_audit

    try:
        fresh = deps_audit.refresh_if_stale()
    except Exception:  # noqa: BLE001 - the audit is a side task of the backup; logged with its traceback
        logging.getLogger("jav.runtime.backup").exception("dependency audit failed")
        return
    if fresh is not None:
        logging.getLogger("jav.runtime.backup").info("dependency audit: %s", deps_audit.verdict(deps_audit.status())[1])


def cmd_flows(args: argparse.Namespace) -> int:
    """Burr contracts: lint (contract <-> live graph <-> source) + FLOW.md / FLOW.mmd generation under docs/flows/."""
    from jav.devtools import admin
    from jav.flows import contract

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
    from jav.devtools import docsgen

    for p in docsgen.write_callsite_docs():
        print(f"  -> {p}")
    print(f"  -> {docsgen.write_bank_files_doc()}")
    args.check = False
    return cmd_flows(args)


def cmd_admin(args: argparse.Namespace) -> int:
    from jav.devtools.admin import admin_report, write_state

    if args.write:
        print(f"  -> {write_state()}")
        return 0
    print(admin_report())
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    from jav.devtools.preflight import preflight

    return preflight(skip_pytest=args.skip_pytest)


def cmd_test_worktree(args: argparse.Namespace) -> int:
    """231: the full test suite in the separate test worktree, so the main working tree stays free meanwhile."""
    from jav.devtools import test_worktree

    try:
        ok, lines, folder = test_worktree.run(ui=not args.no_ui)
    except test_worktree.WorktreeError as exc:
        print(f"no test run: {exc}")
        return 2
    for line in lines:
        print(line)
    print(f"log: {folder}")
    return 0 if ok else 1


def cmd_data_guard(args: argparse.Namespace) -> int:
    from jav.devtools import data_guard
    from jav.core.config import PROJECT_ROOT

    found = data_guard.scan_tracked(PROJECT_ROOT, data_guard.load_guard(PROJECT_ROOT))
    print(data_guard.report(found, "a kiadás") or "adatőr: a verziókövetett fájlokban nincs találat")
    if args.all:  # the locations of the tolerated known values too (masked)
        for f in found:
            if f.known:
                print(f.describe())
    return 1 if data_guard.blocking(found) else 0


def cmd_lang_guard(args: argparse.Namespace) -> int:
    """073 language guard: no tracked file may gain Hungarian lines; see jav/devtools/lang_guard.py."""
    from jav.devtools import lang_guard
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
    """075: known vulnerabilities in the pinned Python and UI packages (free; needs network); see jav/runtime/deps_audit.py."""
    from jav.runtime import deps_audit

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
    from jav.evals import before_after

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
    from jav.evals import before_after, before_after_replay

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
    from jav.evals import before_after

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
    from jav.app import package_release

    done = package_release.backfill(dry_run=args.dry_run)
    for e in done:
        print(f"{e['workpackage_id']}: {e['items']} items, approved by {e['released_by']} at {e['released_at']}"
              + (f" -> version {e['version']}" if "version" in e else " (dry run)"))
    print(f"packages: {len(done)}")
    return 0


def cmd_hooks_install(args: argparse.Namespace) -> int:
    from jav.devtools import data_guard
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

    from jav.legacy import legacy_import
    from jav.core.config import OLD_DATA_ROOT

    print(json.dumps(legacy_import.import_batches(Path(args.root) if args.root else OLD_DATA_ROOT / "output"), ensure_ascii=False))
    return 0


def cmd_legacy_compare(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav.legacy import legacy_import

    rep = legacy_import.compare()
    text = json.dumps(rep, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0


def cmd_reground(args: argparse.Namespace) -> int:
    from jav.app import reground

    for run_id in args.runs:
        print(run_id, json.dumps(reground.reground_run(run_id), ensure_ascii=False))
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    """218: the calculation snapshots - this process's, a stored one, a run's, the difference of two, a stored file."""
    from jav.app import work_runs
    from jav.core import rulebook, store

    with store.connect() as c:
        if args.restore:
            if not args.out:
                print("--restore needs --out")
                return 2
            data = rulebook.content_in(c, args.restore)
            if data is None:
                print(f"no stored file with fingerprint {args.restore}")
                return 1
            Path(args.out).write_bytes(data)
            print(f"{len(data)} bytes written to {args.out}")
            return 0
        if args.diff:
            a, b = (rulebook.get_in(c, s) for s in args.diff)
            if a is None or b is None:
                print("unknown snapshot")
                return 1
            print(json.dumps({"code": {k: [a[k], b[k]] for k in ("app_version", "commit", "dirty") if a[k] != b[k]},
                              "files": rulebook.changes(a, b)}, ensure_ascii=False, indent=2))
            return 0
        if args.run:
            print(json.dumps({**rulebook.of_run_in(c, args.run), "rule_changes": work_runs.rule_changes(args.run)},
                             ensure_ascii=False, indent=2))
            return 0
        sid = args.id or rulebook.current().snapshot_id
        snap = rulebook.get_in(c, sid)
        if snap is None and args.id is None:  # this process's, not linked to anything yet
            here = rulebook.current()
            snap = {"snapshot_id": sid, "stored": False, "app_version": here.app_version, "commit": here.commit,
                    "dirty": here.dirty, "files": here.files}
        if snap is None:
            print(f"unknown snapshot {sid}")
            return 1
        links = dict(c.execute("SELECT subject_kind, COUNT(*) FROM snapshot_links WHERE snapshot_id=? GROUP BY subject_kind",
                               (sid,)).fetchall())
    files = snap.pop("files", {})
    print(json.dumps({**snap, "files": len(files), "linked": links}, ensure_ascii=False, indent=2))
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    """218 (P3b): the decision trace - the registered decision points, or the trace rows of a subject, a run, a case or
    a point, each with its rule run again on its stored inputs (`same`: the stored outcome)."""
    from jav.core import trace

    if args.points:
        print(json.dumps([{"code": p.code, "what": p.what, "not_for": p.not_for, "owner": p.owner, "files": list(p.files)}
                          for p in trace.points()], ensure_ascii=False, indent=2))
        return 0
    subject = tuple(args.subject.split(":", 1)) if args.subject else None
    if subject is not None and len(subject) != 2:
        print("--subject is KIND:ID")
        return 2
    rows = trace.rows(point=args.point, subject=subject, run_id=args.run, case_id=args.case, last=args.last)
    for row in rows:
        known = any(p.code == row["point"] for p in trace.points())
        row["same"] = trace.replay(row) == row["outcome"] if known else None
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def cmd_rules_preview(args: argparse.Namespace) -> int:
    """224 (P3d): a rule file's candidate version tried on the decisions the trace holds (free, read only)."""
    from jav.evals import rules_preview

    from jav.evals.before_after import SnapshotError

    if args.replay and not (args.work and args.out_dir):
        print("no preview: --replay needs --work and --out-dir")
        return 2
    try:
        candidate = (Path(args.candidate).read_bytes() if args.candidate
                     else rules_preview.from_ref(args.ref, args.file))
        if args.replay:
            report = rules_preview.replay(args.file, candidate, baseline=Path(args.replay), work_dir=Path(args.work),
                                          out_dir=Path(args.out_dir), size=args.size,
                                          jev_cache=Path(args.jev_cache) if args.jev_cache else None)
        else:
            report = rules_preview.preview(args.file, candidate, store_path=Path(args.store) if args.store else None,
                                           point=args.point, examples=args.examples)
    except (OSError, SnapshotError, rules_preview.PreviewError) as exc:
        print(f"no preview: {exc}")
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for line in (rules_preview.replay_text(report) if args.replay else rules_preview.text(report)):
            print(line)
    if args.replay and not all(r["passed"] for r in report["replays"].values()):
        return 3  # a replay made a call that was not an earlier answer (the replay's own gate)
    return 0


def cmd_store(args: argparse.Namespace) -> int:
    from jav.core import store

    print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    from jav.runtime import backup
    from jav.core import applog

    if args.scheduled:  # 064: the daily scheduled backup, per the `backup` section of configs/service.json
        applog.setup("backup")
        m = backup.scheduled()
        _refresh_deps_audit()
        _refresh_jev_version()
    else:
        m = backup.backup(out_root=Path(args.out) if args.out else None, with_burr=args.with_burr, keep=args.keep,
                          copy_to=Path(args.copy_to) if args.copy_to else None, with_docs=args.with_docs,
                          with_env=args.with_env)
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


def cmd_cases_adopt(args: argparse.Namespace) -> int:
    """231 (plan stage C, C1c): the packages made before a process was a pack, taken over as its cases (`adopts`);
    (C3b4) or each wrapped by a new case of it (`wraps`)."""
    from jav.app import process_runtime, registrations
    from jav.core import identity

    registrations.load_all()
    rows = process_runtime.adopt_all(actor=identity.machine("cases-adopt"), write=args.write)
    for r in rows:
        print(f"{r['pack']}: {r['workpackage_id']} ({r['name']}) -> {r['result']}" + (f": {r['error']}" if r.get("error") else ""))
    print(f"{len(rows)} package(s){'' if args.write else '; nothing changed (add --write to take them over)'}")
    return 1 if any(r["result"] == "refused" for r in rows) else 0  # C3a-1: a refused package is reported, not skipped silently


def cmd_cases_kept(args: argparse.Namespace) -> int:
    """231 (stage D0, D0-e): before a release, the open cases whose kept copy of a rule file (as they started) the code
    here does not read, being of another main version: their steps that read it would stop with why. Run it with the
    code to release on a copy of the live store (`--store`). 0: none; 1: some, listed; 2: no store there."""
    from contextlib import nullcontext
    from pathlib import Path

    from jav.app import process_runtime, registrations
    from jav.core import store

    if args.store and not Path(args.store).is_file():
        print(f"no store at {args.store}")
        return 2
    registrations.load_all()
    with store.use_store(Path(args.store)) if args.store else nullcontext(), store.read_only():
        rows = process_runtime.unfit_cases()
    for r in rows:
        print(f"{r['case']} ({r['name']}): {r['why']}")
    print(f"{len(rows)} open case(s) would stop" if rows else "every open case reads the rule files it keeps")
    return 1 if rows else 0


def cmd_invented_services(args: argparse.Namespace) -> int:
    """231 (stage D, D-d5): the invented company register and sanctions list as a local web service on this machine
    (127.0.0.1), answering from `configs/golden_registers.json` until stopped (Ctrl+C)."""
    from jav.devtools import invented_services

    print(f"invented registers on http://127.0.0.1:{args.port} (company, sanctions); Ctrl+C stops them")
    try:
        invented_services.serve(args.port)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_product_set(args: argparse.Namespace) -> int:
    """231 (stage D, D-c5): a product set kept as data (`configs/<name>.json`): whether it holds together and its
    reference cases give what they expect (free: no AI call); with `--install`, its things into the store as drafts by
    `--maker`, made active by `--approver` when given. 0: in order; 1: problems or differences, listed; 2: refused."""
    from contextlib import nullcontext
    from pathlib import Path

    from jav.app import product_sets
    from jav.core import store

    product_set = product_sets.load(args.name)
    found = product_sets.problems(product_set)
    for p in found:
        print(f"problem: {p}")
    differing = 0
    for case in product_set.cases if not found else ():
        differences = product_sets.case_differences(product_set, case)
        differing += bool(differences)
        print(f"case {case.id}: " + ("as expected" if not differences else "; ".join(differences)))
    print(f"{len(product_set.documents)} document(s), {len(product_set.rules)} rule(s), {len(product_set.tariffs)} "
          f"tariff(s), {len(product_set.products)} product(s), {len(product_set.cases)} case(s); "
          f"{len(found)} problem(s), {differing} case(s) differing")
    if args.write_pdfs:  # D-c7a: the condition documents as PDFs, as a rule proposal reads them
        written = product_sets.write_documents(product_set, Path(args.write_pdfs))
        print(f"wrote {len(written)} condition document(s) as PDFs into {args.write_pdfs}")
    if not args.install:
        return 1 if found or differing else 0
    if not args.maker:
        print("--install needs --maker (and --approver to make the things active)")
        return 2
    if args.store and not Path(args.store).is_file():
        print(f"no store at {args.store}")
        return 2
    with store.use_store(Path(args.store)) if args.store else nullcontext():
        try:
            refs = product_sets.install(product_set, maker=args.maker, approver=args.approver)
        except product_sets.SetRefused as exc:
            for p in exc.problems:
                print(f"refused: {p}")
            return 2
    print(f"installed {len(refs)} thing(s)" + (f", made active by {args.approver}" if args.approver else " as drafts"))
    return 0


def cmd_rule_propose(args: argparse.Namespace) -> int:
    """231 (stage D, D-c7e): rules proposed from a condition document's file, at once: by GPT within `--budget-usd`
    (and, with `--verify`, judged by JEV within `--jev-budget-usd`; without a budget only earlier answers count), or by
    the stand-in (`--stand-in SET`, free). 0: done; 1: the run failed; 2: refused."""
    from decimal import Decimal

    from jav.app import rule_proposal_runs
    from jav.core import calls

    limits = {p: Decimal(v) for p, v in (("openai", args.budget_usd), ("jev", args.jev_budget_usd)) if v}
    proposer = f"stand_in:{args.stand_in}" if args.stand_in else "gpt"
    if proposer == "gpt" and not limits:
        print(calls.NO_BUDGET_NOTE)
    try:
        started = rule_proposal_runs.start(args.document, args.pdf, catalogue=args.catalogue, actor=args.maker,
                                           product=args.product, proposer=proposer, limits=limits, verify=args.verify,
                                           enqueue=False)
    except rule_proposal_runs.ProposalError as exc:
        print(f"refused: {exc}")
        return 2
    done = rule_proposal_runs.process(started["run_id"])
    _print_run(done)
    return 0 if done["state"] == "done" else 1


def _print_run(run: dict) -> None:
    print(f"run {run['run_id']} ({run['state']}): {run['document_ref']} from {run['file']}, {run['proposer']}"
          + (f"; pages left out: {run['skipped']}" if run.get("skipped") else "") + (f"; error: {run['error']}" if run["error"] else ""))
    for p in run.get("proposals", []):
        mark = p["support"]["mark"] if p["support"] else "-"
        print(f"  #{p['id']} [{p['state']}, {p['readiness']}, JEV {mark}] {p['title']} ({p['kind']}, page {p['page']},"
              f" clause {p['clause']})" + (f" -> {p['rule_ref']}" if p["rule_ref"] else ""))


def cmd_rule_proposals(args: argparse.Namespace) -> int:
    """231 (D-c7e): the proposal runs (of one document version), or one run with its proposals."""
    from jav.app import rule_proposal_runs

    if args.run:
        _print_run(rule_proposal_runs.run(args.run))
        return 0
    for r in rule_proposal_runs.runs(args.document):
        print(f"{r['run_id']} {r['state']} {r['document_ref']} {r['file']} {r['proposer']} {r['counts']}")
    return 0


def cmd_rule_proposal_decide(args: argparse.Namespace) -> int:
    """231 (D-c7e): a person's decision on one proposal: accept (confirming the numbers the document does not print),
    correct (a rule file in its place) or reject (with a reason). 0: done; 2: refused."""
    import json
    from pathlib import Path

    from jav.app import rule_proposal_runs
    from jav.core import decisions

    confirmed = [v.strip() for v in (args.confirm or "").split(",") if v.strip()]
    try:
        state = next(p["decision_state"] for r in rule_proposal_runs.runs() for p in rule_proposal_runs.run(r["run_id"])["proposals"]
                     if p["id"] == args.proposal)
    except StopIteration:
        print(f"no proposal #{args.proposal}")
        return 2
    try:
        if args.action == "accept":
            done = rule_proposal_runs.accept(args.proposal, actor=args.maker, expected_state=state, confirmed=confirmed, ident=args.ident)
        elif args.action == "correct":
            rule = json.loads(Path(args.rule_file).read_text(encoding="utf-8"))
            done = rule_proposal_runs.correct(args.proposal, rule, actor=args.maker, expected_state=state, confirmed=confirmed,
                                              ident=args.ident)
        else:
            done = rule_proposal_runs.reject(args.proposal, args.reason or "", actor=args.maker, expected_state=state)
    except rule_proposal_runs.ProposalRefused as exc:
        for p in exc.problems:
            print(f"refused: {p}")
        return 2
    except (rule_proposal_runs.ProposalError, decisions.RevisionConflict) as exc:
        print(f"refused: {exc}")
        return 2
    print(f"#{done['id']} {done['state']}" + (f" -> {done['rule_ref']} (a draft rule)" if done["rule_ref"] else ""))
    return 0


def cmd_burr_prune(args: argparse.Namespace) -> int:
    from jav.runtime import worker
    from jav.flows import persistence
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
    p = sub.add_parser("cases-adopt", help="231: the packages made before a process was a process pack, taken over as its cases (the pack's adopts) or wrapped by new ones (its wraps)")
    p.add_argument("--write", action="store_true", help="take them over (without it: only list them)")
    p.set_defaults(fn=cmd_cases_adopt)
    p = sub.add_parser("cases-kept", help="231 D0-e: before a release, the open cases whose rule files as they started "
                                          "the code here does not read (another main version); read only")
    p.add_argument("--store", help="a store copy to read instead of the active store (read only)")
    p.set_defaults(fn=cmd_cases_kept)
    p = sub.add_parser("product-set", help="231 D-c5: a product set kept as data (condition documents, rules, products, "
                                           "tariffs, reference cases): checked, its cases compared (free); --install puts it into the store")
    p.add_argument("name", nargs="?", default="golden_products", help="the set's config (default: golden_products, the invented insurer)")
    p.add_argument("--install", action="store_true", help="add its things as drafts (a thing there with the same content is kept)")
    p.add_argument("--maker", help="the person adding them")
    p.add_argument("--approver", help="another person, making them active (a product needs a second person)")
    p.add_argument("--store", help="a store file to install into instead of the active store")
    p.add_argument("--write-pdfs", metavar="DIR", help="231 D-c7a: write the set's condition documents as PDFs into DIR")
    p.set_defaults(fn=cmd_product_set)
    p = sub.add_parser("invented-services", help="231 D-d5: the invented company register and sanctions list as a local "
                                                 "web service (127.0.0.1), for the trial; the tests answer them inside the process")
    p.add_argument("--port", type=int, default=8941, help="the port the connectors name (default 8941)")
    p.set_defaults(fn=cmd_invented_services)
    p = sub.add_parser("rule-propose", help="231 D-c7e: rules proposed from a condition document's file (GPT within --budget-usd, "
                                            "JEV with --verify within --jev-budget-usd; or --stand-in SET, free), kept for a person")
    p.add_argument("document", help="the document version the rules cite (<id>@<n>)")
    p.add_argument("--pdf", required=True, help="the document's file (local)")
    p.add_argument("--catalogue", default="property", help="the fact catalogue (configs/facts_<id>.json)")
    p.add_argument("--product", help="the product whose cover modules the proposer is told (its active version)")
    p.add_argument("--stand-in", metavar="SET", help="answer from a product set's rules instead of GPT (free)")
    p.add_argument("--verify", action="store_true", help="have JEV judge each proposal code found nothing blocking in")
    p.add_argument("--maker", required=True, help="the person asking")
    budget_args(p)
    p.set_defaults(fn=cmd_rule_propose)
    p = sub.add_parser("rule-proposals", help="231 D-c7e: the rule proposal runs, or one run with its proposals")
    p.add_argument("--document", help="only the runs of this document version")
    p.add_argument("--run", help="one run with its proposals")
    p.set_defaults(fn=cmd_rule_proposals)
    p = sub.add_parser("rule-proposal-decide", help="231 D-c7e: accept, correct or reject one proposal (an accepted one becomes a draft rule)")
    p.add_argument("proposal", type=int)
    p.add_argument("action", choices=("accept", "correct", "reject"))
    p.add_argument("--maker", required=True, help="the person deciding")
    p.add_argument("--confirm", help="the numbers you confirm, comma separated (those the document does not print)")
    p.add_argument("--rule-file", help="correct: the corrected rule (JSON)")
    p.add_argument("--reason", help="reject: why")
    p.add_argument("--ident", help="the draft rule's identifier (default: <document>.<clause>.<kind>)")
    p.set_defaults(fn=cmd_rule_proposal_decide)
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
    p = sub.add_parser("test-worktree", help="231: the full test suite (pytest + UI) in a separate git worktree, with the uncommitted changes, so the main working tree stays free meanwhile")
    p.add_argument("--no-ui", action="store_true", help="pytest only")
    p.set_defaults(fn=cmd_test_worktree)
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
    p.add_argument("--work", required=True, help="the folder of the fresh copy (a new or empty one, or an earlier copy of this tool, which is replaced; outside git)")
    p.add_argument("--out", required=True, help="the snapshot file to write (JSON lines; personal data, outside git)")
    p.add_argument("--no-items", action="store_true", help="leave out the item results of every run (faster)")
    p.add_argument("--matches", action="store_true", help="also the proposed pairs of every reconciliation line (slow)")
    p.set_defaults(fn=cmd_before_after_snapshot)
    p = sub.add_parser("before-after-replay", help="173: a sample of the backed-up store's items processed again on a fresh copy, "
                                                   "from earlier answers only, for the before/after comparison (free)")
    p.add_argument("baseline", help="a backup folder (python -m jav.cli backup) or a store file")
    p.add_argument("--work", required=True, help="the folder of the fresh copy (a new or empty one, or an earlier copy of this tool, which is replaced; outside git; the same for both replays)")
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
    p = sub.add_parser("snapshot", help="218: calculation snapshots - the code and the rules a run, an item, a case or an"
                                        " approval was computed with (without an option: this process's)")
    p.add_argument("--id", help="a stored snapshot")
    p.add_argument("--run", help="a run's snapshots and what changed during it")
    p.add_argument("--diff", nargs=2, metavar=("A", "B"), help="the files and the code that differ between two snapshots")
    p.add_argument("--restore", metavar="SHA256", help="write a stored rule file's content (with --out)")
    p.add_argument("--out", help="where --restore writes")
    p.set_defaults(fn=cmd_snapshot)
    p = sub.add_parser("trace", help="218: the decision trace - which rule decided, with what, in which version (the latest"
                                     " 20 rows without a filter)")
    p.add_argument("--points", action="store_true", help="the registered decision points")
    p.add_argument("--point", help="one decision point's rows")
    p.add_argument("--subject", metavar="KIND:ID", help="the rows about one subject (e.g. workflow_step:wf-...:invoices)")
    p.add_argument("--run", help="the rows made in one run")
    p.add_argument("--case", help="the rows made in one case")
    p.add_argument("--last", type=int, default=20, help="only the latest this many rows (default 20)")
    p.set_defaults(fn=cmd_trace)
    p = sub.add_parser("rules-preview", help="224: a rule file's candidate version tried on the decisions the trace holds: "
                                             "how many would change, and which to-dos would open or close (free, read only)")
    p.add_argument("file", help="the rule file under configs/ (e.g. policy.json, types/invoice_hu.json)")
    which = p.add_mutually_exclusive_group(required=True)
    which.add_argument("--candidate", help="a file with the candidate content")
    which.add_argument("--ref", help="a git reference whose configs/<file> is the candidate (e.g. a branch or a commit)")
    p.add_argument("--store", help="a store copy to read instead of the active store (read only)")
    p.add_argument("--point", help="only this decision point")
    p.add_argument("--examples", type=int, default=5, help="the changed decisions shown per point (default 5)")
    p.add_argument("--json", action="store_true", help="the whole report as JSON")
    p.add_argument("--replay", metavar="BACKUP", help="instead: a sample of this backup's items replayed twice (with the "
                                                      "rules in use now and with the candidate) and the views that differ")
    p.add_argument("--work", help="with --replay: the folder of the fresh copy (a new or empty one, or an earlier copy of this tool, which is replaced; outside git)")
    p.add_argument("--out-dir", help="with --replay: where the two replays are written (outside git)")
    p.add_argument("--size", type=int, default=150, help="with --replay: about how many units (default 150)")
    p.add_argument("--jev-cache", help="with --replay: the JEV answer cache to read (default: runs/cache)")
    p.set_defaults(fn=cmd_rules_preview)
    p = sub.add_parser("store", help="adattár statisztika (documents, datapoints, review_queue, ledger)")
    p.set_defaults(fn=cmd_store)
    p = sub.add_parser("backup", help="063: az adattár mentése futás közben is (SQLite-mentés + sértetlenség-ellenőrzés), store/backups/ alá")
    p.add_argument("--out", help="a mentések gyökere (alapból store/backups)")
    p.add_argument("--with-burr", action="store_true", help="a folyamat-állapotok tára (store/burr_state.sqlite, nagy) is")
    p.add_argument("--with-docs", action="store_true", help="070: a belső munkaanyag (jav/core/doc_scope.py) is, internal-docs.zip")
    p.add_argument("--with-env", action="store_true", help="231: the local settings (.env, with the keys) too, into local-env.zip")
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
