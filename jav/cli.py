"""Command line: `python -m jav.cli <command>`.

  candidates <pdf>            candidates by kind (no API)
  recall                      candidate recall on the golden set (no API) - the ceiling of the S path
  run <pdf> --arm S|G         runs one invoice through the Burr graph
  golden --arm S|G            golden eval for one path
  determinism --arm S --n 5   repeated runs, per-field agreement (no cache)
  store                       store statistics
  detect <pdf> | detect-golden | detect-determinism --n 3 | detect-corpus <folder> | detect-sample <folder>
                              M1 categorisation
  email <folder> | email-inbox <root> | email-golden | email-determinism --n 3   M3 email intent
  email-ingest-server [--port 8901] [--run]   receiver for the legacy 10_AIFLOW_V4 outlook_bridge.ps1
  eval-report [files]         shared eval report from runs/*.jsonl ($0): bands, calibration, policy re-evaluation,
                              determinism
  configs                     configs/*.json versions + config_hash (config as data)
  flows [--check]             Burr contract lint + FLOW.md generation (docs/flows/)
  docs                        generated docs: call-site catalogue + flow contracts
  admin [--write]             control screen: configs, models, lint, store, golden, review; --write -> docs/STATE.md
  preflight [--skip-pytest]   session-start check: pytest + lint + configs + handoff freshness + STATE.md
  recipes | wp-* | run-* | worker   work package → run (040 K1; details: jav/work_cli.py)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jav  # noqa: F401  - sets up UTF-8 output


def cmd_candidates(args: argparse.Namespace) -> int:
    from jav.candidates import find_all, find_currencies
    from jav.pdf import read_document

    from jav.typepack import get as get_pack

    pack = get_pack(args.type)
    profile = pack.candidate_profile
    pdf = read_document(args.pdf)  # text layer, or OCR (from the cache)
    print(f"{pdf.path}: {pdf.page_count} oldal, {len(pdf.lines)} sor, szövegréteg={pdf.has_text_layer}, szöveg-forrás={pdf.text_source}, jelölt-profil={profile}")
    if args.lines:
        for ln in pdf.layout:
            print(f"L{ln.no:02d}: {ln.text}")
        print()
    cands = find_all(pdf.layout, profile, text_labels=pack.text_labels)
    print(f"pénznem: {find_currencies(pdf.layout, profile)}")
    for kind, items in cands.items():
        print(f"\n## {kind} ({len(items)})")
        for c in items:
            amb = "  [ambiguous]" if c.ambiguous else ""
            occ = f"  x{c.occurrences}" if c.occurrences > 1 else ""
            print(f"  {c.label!r:45} raw={c.raw!r}{amb}{occ}   {c.context[:110]}")
    return 0


def cmd_recall(args: argparse.Namespace) -> int:
    from jav.evals import candidate_recall

    candidate_recall(type_key=args.type)
    return 0


def cmd_ocr(args: argparse.Namespace) -> int:
    """OCR on one PDF (or the engine status): text source, quality signals, lines. For diagnosis: what the flow sees
    on a scanned invoice."""
    from jav import ocr

    if not args.pdf:
        print(json.dumps(ocr.status(), ensure_ascii=False, indent=2))
        return 0
    from jav.pdf import read_document

    pdf = read_document(args.pdf) if not args.force else ocr.ocr_pdf(args.pdf, use_cache=False, psm=args.psm)
    print(f"{pdf.path}: {pdf.page_count} oldal, {len(pdf.lines)} sor, szövegréteg={pdf.has_text_layer}, szöveg-forrás={pdf.text_source}")
    if pdf.ocr:
        print("OCR: " + json.dumps(pdf.ocr, ensure_ascii=False))
    for ln in pdf.layout[: args.limit or None]:
        print(f"L{ln.no:03d} p{ln.page}: {ln.text}")
    return 0


def cmd_ocr_rekey(args: argparse.Namespace) -> int:
    """076: a one-off move of the OCR cache to the current key (`jav/ocr.py` `rekey_cache`); refuses if the older
    config differs in a setting that changes the recognised text."""
    import subprocess

    from jav import ocr
    from jav.config import PROJECT_ROOT

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


def cmd_run(args: argparse.Namespace) -> int:
    from jav.flow import run_one

    state = run_one(args.pdf, case_id=args.case_id or "adhoc", arm=args.arm, tracker=not args.no_tracker, use_cache=not args.no_cache, doc_type=args.type)
    print(f"\n=== {state.final_status} | route={state.route} | arm={state.arm} | type={state.doc_type}")
    if state.invoice:
        print(json.dumps(state.invoice.to_datapoints(), ensure_ascii=False, indent=2, default=str))
    if state.picks:
        print("\n--- picks")
        for f, p in state.picks.items():
            conf = "-" if p.confidence is None else f"{p.confidence:.2f}"  # 069: no verdict without a candidate
            present = "" if p.present_p is None else f" present={p.present_p:.2f}"
            print(f"  {f:18} {str(p.label)!r:40} conf={conf} n={p.n_options}{present} [{p.request_id}]")
    if state.verdicts:
        print("\n--- verdicts (P(flag)>0.3)")
        for f, flags in state.verdicts.flags.items():
            hot = {k: round(v, 2) for k, v in flags.items() if v > 0.3}
            if hot:
                print(f"  {f:18} {hot}")
        print(f"  doc_flags: { {k: round(v, 2) for k, v in state.verdicts.doc_flags.items()} }")
        if state.verdicts.unsupported:
            print(f"  unsupported: {state.verdicts.unsupported}")
    print("\n--- validation")
    for v in state.validation:
        print(f"  {'OK ' if v.ok else 'FAIL'} {v.name}: {v.code}" + (f" ({v.detail})" if v.detail else ""))
    print("\n--- review_reasons: " + ("; ".join(state.review_reasons) or "-"))
    print("--- jev_calls: " + "; ".join(
        f"{c.request_id}:{c.n_questions}q/{c.input_tokens}tok/{c.seconds}s{' [cache]' if c.cached else ''}" for c in state.jev_calls))
    print(f"--- run_id: {state.run_id}  doc_id: {state.doc_id[:12]}…")
    from jav import store

    rows = store.ledger_for_run(state.run_id)
    print("--- ledger: " + "; ".join(f"{r['provider']}/{r['step']} {r['input_tokens'] or 0}tok ${r['cost_usd'] or 0:.4f}{' [cache]' if r['cached'] else ''}" for r in rows))
    return 0


def cmd_verifier_probe(args: argparse.Namespace) -> int:
    from jav.evals import verifier_probe

    verifier_probe(use_cache=not args.no_cache, type_key=args.type)
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    from jav.flow_detect import run_detect

    st = run_detect(args.pdf, tracker=args.tracker, use_cache=not args.no_cache)
    print(f"=== {st.final_status}  doc_id={st.doc_id[:12]}…  run_id={st.run_id}")
    if st.result:
        r = st.result
        print(f"típus: {r.doc_type}  conf={r.confidence:.2f}  issuer_hu={r.issuer_hu:.2f}  nyelv={r.language} ({r.language_conf:.2f})")
        print("top3:", dict(sorted(r.probabilities.items(), key=lambda kv: -kv[1])[:3]))
        print("anchor_hits:", r.anchor_hits)
        print(f"jev: {r.call.n_questions}q/{r.call.input_tokens}tok/{r.call.seconds}s{' [cache]' if r.call.cached else ''}")
    return 0


def cmd_detect_golden(args: argparse.Namespace) -> int:
    from decimal import Decimal

    from jav.evals_detect import detect_golden

    detect_golden(use_cache=not args.no_cache, jev=not args.no_jev, descriptions=not args.keys_only,
                  budget_usd=Decimal(args.budget_usd) if args.budget_usd else None)
    return 0


def cmd_detect_determinism(args: argparse.Namespace) -> int:
    from jav.evals_detect import detect_determinism

    detect_determinism(n=args.n, limit=args.limit)
    return 0


def cmd_detect_corpus(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav.evals_detect import detect_corpus, print_corpus_report

    root = Path(args.root)
    if args.report_only:
        print_corpus_report(root)
    else:
        detect_corpus(root, limit=args.limit, force=args.force, use_cache=not args.no_cache, redo_unknown=args.redo_unknown)
    return 0


def cmd_detect_sample(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav.evals_detect import write_manual_sample

    out = write_manual_sample(Path(args.root), n=args.n, seed=args.seed)
    print(f"kézi ellenőrző lista: {out}")
    return 0


def cmd_legacy_import(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav import legacy_import
    from jav.config import OLD_DATA_ROOT

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
    from jav import store

    print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
    return 0


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


def cmd_backup(args: argparse.Namespace) -> int:
    from jav import backup
    from jav.runtime import applog

    if args.scheduled:  # 064: the daily scheduled backup, per the `backup` section of configs/service.json
        applog.setup("backup")
        m = backup.scheduled()
        _refresh_deps_audit()
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
    from jav.runtime import lock, persistence, queue, worker

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


def cmd_golden(args: argparse.Namespace) -> int:
    from jav.evals import golden
    from jav.flow import run_one

    from decimal import Decimal

    golden(args.arm, run_one, tracker=args.tracker, use_cache=not args.no_cache, type_key=args.type, jev=not args.no_jev,
           budget_usd=Decimal(args.budget_usd) if args.budget_usd else None)
    return 0


def cmd_determinism(args: argparse.Namespace) -> int:
    from jav.evals import determinism
    from jav.flow import run_one

    determinism(args.arm, args.n, run_one, type_key=args.type)
    return 0


def cmd_email(args: argparse.Namespace) -> int:
    from jav.flow_email import run_email

    st = run_email(args.folder, tracker=not args.no_tracker, use_cache=not args.no_cache)
    r, m = st.result, st.message
    assert r is not None and m is not None
    print(f"=== {m.message_id} | {m.sender} | {m.subject!r}")
    print(f"intent={r.intent} conf={r.confidence:.2f} next_flow={st.next_flow} uncertain={st.uncertain}")
    print("signals: " + ", ".join(f"{k}={v:.2f}" for k, v in r.signals.items()))
    print("top3: " + json.dumps(dict(sorted(r.probabilities.items(), key=lambda kv: -kv[1])[:3]), ensure_ascii=False))
    for a in m.attachments:
        print(f"  csatolmány {a.filename}: {a.status} {a.doc_type or ''} {'' if a.type_conf is None else f'{a.type_conf:.2f}'}")
    print(f"[{r.call.request_id}] {r.call.input_tokens} tok, ${r.call.cost_usd:.5f}, {r.call.seconds}s, cached={r.call.cached}")
    return 0


def cmd_email_golden(args: argparse.Namespace) -> int:
    from jav.evals_email import email_golden

    from decimal import Decimal

    email_golden(use_cache=not args.no_cache, limit=args.limit, jev=not args.no_jev,
                 budget_usd=Decimal(args.budget_usd) if args.budget_usd else None)
    return 0


def cmd_email_inbox(args: argparse.Namespace) -> int:
    from jav.evals_email import email_inbox, print_inbox_report

    if args.report_only:
        print_inbox_report()
    else:
        email_inbox(args.root, limit=args.limit, force=args.force, use_cache=not args.no_cache)
    return 0


def cmd_email_ingest_server(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav.ingest_server import INBOX_ROOT, serve

    serve(port=args.port, run_flow=args.run, inbox_root=Path(args.inbox) if args.inbox else INBOX_ROOT, token=args.token)
    return 0


def cmd_email_sample(args: argparse.Namespace) -> int:
    from jav.evals_email import email_manual_sample

    email_manual_sample()
    return 0


def cmd_flows(args: argparse.Namespace) -> int:
    """Burr contracts: lint (contract <-> live graph <-> source) + FLOW.md / FLOW.mmd generation under docs/flows/."""
    from jav import contract, flow, flow_detect, flow_email, flow_learning, flow_email_learning

    targets = [
        (flow, flow.build_app("lint.pdf", "lint", "S", tracker=False)),
        (flow_detect, flow_detect.build_app("lint.pdf", tracker=False)),
        (flow_email, flow_email.build_app(source_dir="lint", tracker=False)),
        (flow_learning, flow_learning.build_app()),
        (flow_email_learning, flow_email_learning.build_app()),
    ]
    all_ok = True
    for module, app in targets:
        result = contract.lint_flow(module.CONTRACT, app, module)
        all_ok &= result["passed"]
        print(contract.format_report(result))
        if not args.check:
            paths = contract.write_artifacts(module.CONTRACT)
            print(f"  -> {paths['md']}")
        print()
    return 0 if all_ok else 1


def cmd_docs(args: argparse.Namespace) -> int:
    """Generated docs: docs/flows (contracts) + docs/callsites (JEV call sites)."""
    from jav import docsgen

    for p in docsgen.write_callsite_docs():
        print(f"  -> {p}")
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
    from jav.config import PROJECT_ROOT

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
    from jav.config import PROJECT_ROOT

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


def cmd_hooks_install(args: argparse.Namespace) -> int:
    from jav import data_guard
    from jav.config import PROJECT_ROOT

    print(data_guard.install_hooks(PROJECT_ROOT))
    return 0


def cmd_configs(args: argparse.Namespace) -> int:
    from jav import cfg

    print("| konfig | verzió | hash | utolsó changelog |\n|---|---|---|---|")
    for r in cfg.report():
        print(f"| {r['name']} | {r['version']} | `{r['hash']}` | {r['last']} |")
    return 0


def cmd_eval_report(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav.eval_report import write_report

    md, out = write_report([Path(p) for p in args.paths] or None, out=Path(args.out) if args.out else None)
    print(md)
    print(f"Riport: {out}")
    return 0


def cmd_email_determinism(args: argparse.Namespace) -> int:
    from jav.evals_email import email_determinism

    email_determinism(n=args.n, limit=args.limit)
    return 0


def cmd_email_injection_probe(args: argparse.Namespace) -> int:
    from jav.evals_email import email_injection_probe

    from decimal import Decimal

    email_injection_probe(limit=args.limit, use_cache=not args.no_cache, jev=not args.no_jev,
                          budget_usd=Decimal(args.budget_usd) if args.budget_usd else None)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jav", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    from jav.learning_cli import register as register_learning
    register_learning(sub)
    from jav.work_cli import register as register_work

    register_work(sub)

    from jav.typepack import keys as pack_keys

    type_help = "típus-csomag (configs/types/<típus>.json): " + " | ".join(pack_keys()) + " (alap: invoice_hu)"

    p = sub.add_parser("candidates")
    p.add_argument("pdf")
    p.add_argument("--lines", action="store_true", help="a rekonstruált sorok kiírása is")
    p.add_argument("--type", default="invoice_hu", help=type_help)
    p.set_defaults(fn=cmd_candidates)

    p = sub.add_parser("recall")
    p.add_argument("--type", default="invoice_hu", help=type_help)
    p.set_defaults(fn=cmd_recall)

    p = sub.add_parser("run")
    p.add_argument("pdf")
    p.add_argument("--arm", choices=["S", "G"], default="S")
    p.add_argument("--case-id", default=None)
    p.add_argument("--type", default="invoice_hu", help=type_help)
    p.add_argument("--no-tracker", action="store_true")
    p.add_argument("--no-cache", action="store_true", help="Jev kérés-cache kihagyása (élő hívás)")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("detect", help="M1: egy dokumentum kategorizálása Jevvel")
    p.add_argument("pdf")
    p.add_argument("--tracker", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.set_defaults(fn=cmd_detect)

    p = sub.add_parser("detect-golden", help="M1 golden: a régi doc-triage + doc-extract típus-címkéin")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--no-jev", action="store_true", help="086: GPT recognises the type (paid OpenAI calls)")
    p.add_argument("--keys-only", action="store_true", help="086: with --no-jev, offer the types by their keys only")
    p.add_argument("--budget-usd", help="086: hard OpenAI budget for the whole measurement (JEV and Azure get none)")
    p.set_defaults(fn=cmd_detect_golden)

    p = sub.add_parser("detect-determinism", help="M1: ismételt futások cache nélkül a detect-goldenen, típus-flipek és conf-szórás")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--limit", type=int)
    p.set_defaults(fn=cmd_detect_determinism)

    p = sub.add_parser("detect-corpus", help="M1 bejárás egy mappán (rekurzív), folytatható; riport típus × év")
    p.add_argument("root")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true", help="a már kategorizáltakat is újra")
    p.add_argument("--report-only", action="store_true")
    p.add_argument("--redo-unknown", action="store_true", help="csak az 'unknown' / bizonytalan dokumentumok újra")
    p.add_argument("--no-cache", action="store_true")
    p.set_defaults(fn=cmd_detect_corpus)

    p = sub.add_parser("detect-sample", help="M1 kézi ellenőrző Markdown-minta a kategorizált korpuszból")
    p.add_argument("root")
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(fn=cmd_detect_sample)

    p = sub.add_parser("email", help="M3: egy levél (inbox/<mailbox>/<msgid>/ mappa) szándéka Jevvel")
    p.add_argument("folder")
    p.add_argument("--no-tracker", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.set_defaults(fn=cmd_email)

    p = sub.add_parser("email-golden", help="M3 golden: a régi 96 esetes intent-golden (10_AIFLOW_V4) Jev-Choice-szal")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--no-jev", action="store_true", help="089: GPT recognises the intent (paid OpenAI calls)")
    p.add_argument("--budget-usd", help="089: hard OpenAI budget for the whole measurement (JEV and Azure get none)")
    p.set_defaults(fn=cmd_email_golden)

    p = sub.add_parser("email-inbox", help="M3: inbox/<mailbox>/<msgid>/ mappák bejárása (Outlook-lekérés után), folytatható")
    p.add_argument("root")
    p.add_argument("--limit", type=int)
    p.add_argument("--force", action="store_true", help="a már kategorizált levelek is újra")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--report-only", action="store_true", help="csak a store-riport, futtatás nélkül")
    p.set_defaults(fn=cmd_email_inbox)

    p = sub.add_parser("email-ingest-server", help="M3: helyi fogadó a régi outlook_bridge.ps1 /ingest/email POST-jaihoz -> inbox/")
    p.add_argument("--port", type=int, default=8901)
    p.add_argument("--inbox", help="cél inbox-gyökér (alap: <projekt>/inbox)")
    p.add_argument("--run", action="store_true", help="a levél érkezésekor azonnal fusson az M3 gráf (szinkron)")
    p.add_argument("--token", help="kötelező Bearer-kulcs a bridge felé (alap: JAV_INGEST_TOKEN környezeti változó; a bridge -ApiToken-nel küldi)")
    p.set_defaults(fn=cmd_email_ingest_server)

    p = sub.add_parser("email-sample", help="M3: kézi címkéző Markdown-lista az élő levelekből (runs/*_email_manual_sample.md)")
    p.set_defaults(fn=cmd_email_sample)

    p = sub.add_parser("flows", help="Burr-kontraktok lintje + FLOW.md / FLOW.mmd generálás (docs/flows/)")
    p.add_argument("--check", action="store_true", help="csak lint, fájlírás nélkül")
    p.set_defaults(fn=cmd_flows)

    p = sub.add_parser("docs", help="generált doksik: docs/callsites/ (Jev-hívási helyek) + docs/flows/ (kontraktok)")
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

    p = sub.add_parser("hooks-install", help="071 adatőr: a verziózott git-horgok bekapcsolása (core.hooksPath = scripts/githooks)")
    p.set_defaults(fn=cmd_hooks_install)

    p = sub.add_parser("configs", help="konfig mint adat: configs/*.json verziók és config_hash-ek")
    p.set_defaults(fn=cmd_configs)

    p = sub.add_parser("eval-report", help="közös eval-riport a nyers futásokból ($0): kérdésenkénti pontosság + sávok, kalibráció (ECE), top-prob vs. conf, policy-sáv újraértékelés, determinizmus")
    p.add_argument("paths", nargs="*", help="runs/*.jsonl fájlok; üresen: mintánként a legfrissebb")
    p.add_argument("--out", help="a Markdown célfájlja (alap: runs/<idő>_eval_report.md)")
    p.set_defaults(fn=cmd_eval_report)

    p = sub.add_parser("email-determinism", help="M3: ismételt futások cache nélkül, intent-flipek és conf-szórás")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--limit", type=int)
    p.set_defaults(fn=cmd_email_determinism)

    p = sub.add_parser("email-injection-probe", help="M3: beszúrt-utasítás (promptinjekció) szonda a golden levelek tiszta és elrontott változatain (runs/*_email_injection_probe.jsonl)")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--no-jev", action="store_true", help="089: GPT answers the injection question (paid OpenAI calls)")
    p.add_argument("--budget-usd", help="089: hard OpenAI budget for the whole probe (JEV and Azure get none)")
    p.set_defaults(fn=cmd_email_injection_probe)

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
    p.add_argument("--with-docs", action="store_true", help="070: a belső munkaanyag (jav/doc_scope.py) is, internal-docs.zip")
    p.add_argument("--keep", type=int, default=None, help="ennyi legutóbbi mentés marad (alapból a napi mentésé: configs/service.json backup.keep)")
    p.add_argument("--copy-to", help="064: a kész mentés ellenőrzött másolata ide is (pl. NAS-mappa); ott is a --keep marad")
    p.add_argument("--scheduled", action="store_true", help="064: a napi ütemezett mentés a configs/service.json backup szakasza szerint")
    p.set_defaults(fn=cmd_backup)

    p = sub.add_parser("burr-prune", help="064: a folyamatállapot-tár ritkítása (folyamatonként csak az utolsó állapot) és tömörítése")
    p.add_argument("--no-vacuum", action="store_true", help="csak ritkítás, tömörítés nélkül (a fájl mérete ekkor nem csökken)")
    p.set_defaults(fn=cmd_burr_prune)

    p = sub.add_parser("verifier-probe", help="Jev-ellenőrző kalibrációs szonda a golden kivonatokon (OpenAI nélkül); nyers futás runs/*_verifier_probe.jsonl")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--type", default="invoice_hu", help=type_help)
    p.set_defaults(fn=cmd_verifier_probe)

    p = sub.add_parser("golden", help="M2 golden egy karra és típus-csomagra (runs/[<típus>_]golden_<kar>.jsonl)")
    p.add_argument("--arm", choices=["S", "G"], required=True)
    p.add_argument("--type", default="invoice_hu", help=type_help)
    p.add_argument("--tracker", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--no-jev", action="store_true", help="086: the G path verified by the code alone (runs/*_golden_G_nojev.jsonl)")
    p.add_argument("--budget-usd", help="086: hard OpenAI budget for the whole measurement (JEV and Azure get none)")
    p.set_defaults(fn=cmd_golden)

    p = sub.add_parser("determinism")
    p.add_argument("--arm", choices=["S", "G"], required=True)
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--type", default="invoice_hu", help=type_help)
    p.set_defaults(fn=cmd_determinism)

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

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
