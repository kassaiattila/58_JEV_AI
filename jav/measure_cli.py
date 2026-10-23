"""Command line, flows and measurements (202, plan G-core-generalisation M3a): running one document through a
flow, the golden sets and the measurements, the evaluation report. Registered by `jav.cli`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jav.cli_options import REFERENCE_TYPE, budget_args, engine_args, jev_on, s_without_jev, type_pack_help, under_budget


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


def cmd_run(args: argparse.Namespace) -> int:
    from jav.flow import run_one

    if s_without_jev(args):
        return 2
    with under_budget(args, "run"):
        state = run_one(args.pdf, case_id=args.case_id or "adhoc", arm=args.arm, tracker=not args.no_tracker,
                        use_cache=not args.no_cache, doc_type=args.type, jev=jev_on(args))
    print(f"\n=== {state.final_status} | route={state.route} | arm={state.arm} | type={state.doc_type}")
    if state.record:
        print(json.dumps(state.record.to_datapoints(), ensure_ascii=False, indent=2, default=str))
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
    from jav.core import store

    rows = store.ledger_for_run(state.run_id)
    print("--- ledger: " + "; ".join(f"{r['provider']}/{r['step']} {r['input_tokens'] or 0}tok ${r['cost_usd'] or 0:.4f}{' [cache]' if r['cached'] else ''}" for r in rows))
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    from jav.flow_detect import run_detect

    with under_budget(args, "detect"):
        st = run_detect(args.pdf, tracker=args.tracker, use_cache=not args.no_cache, jev=jev_on(args))
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

    import contextlib

    from jav import evals_detect
    from jav.core import store
    from jav.eval_report import report_budget_skips

    cases = evals_detect.load_case_file(args.cases) if args.cases else None
    # 122: a separate measurement store keeps the results, to-dos and call log of the measurement out of the work store
    with store.use_store(Path(args.store)) if args.store else contextlib.nullcontext():
        rows = evals_detect.detect_golden(use_cache=not args.no_cache, jev=jev_on(args), descriptions=not args.keys_only,
                                          budget_usd=Decimal(args.budget_usd) if args.budget_usd else None, cases=cases,
                                          label="cases" if cases is not None else "golden")
    # 123: exit code 3 = the budget left cases without a result
    return 3 if report_budget_skips(rows) else 0


def cmd_detect_determinism(args: argparse.Namespace) -> int:
    from jav.evals_detect import detect_determinism

    with under_budget(args, "detect-determinism", reuse=False):
        detect_determinism(n=args.n, limit=args.limit, jev=jev_on(args))
    return 0


def cmd_detect_corpus(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav.evals_detect import detect_corpus, print_corpus_report

    root = Path(args.root)
    if args.report_only:
        print_corpus_report(root)
    else:
        with under_budget(args, "detect-corpus"):
            detect_corpus(root, limit=args.limit, force=args.force, use_cache=not args.no_cache, redo_unknown=args.redo_unknown,
                          jev=jev_on(args))
    return 0


def cmd_detect_sample(args: argparse.Namespace) -> int:
    from pathlib import Path

    from jav.evals_detect import write_manual_sample

    out = write_manual_sample(Path(args.root), n=args.n, seed=args.seed)
    print(f"kézi ellenőrző lista: {out}")
    return 0


def cmd_email_golden(args: argparse.Namespace) -> int:
    from jav.evals_email import email_golden

    from decimal import Decimal

    jev_budget = getattr(args, "jev_budget_usd", None)
    email_golden(use_cache=not args.no_cache, limit=args.limit, jev=jev_on(args),
                 budget_usd=Decimal(args.budget_usd) if args.budget_usd else None,
                 jev_budget_usd=Decimal(jev_budget) if jev_budget else None)
    return 0


def cmd_email_inbox(args: argparse.Namespace) -> int:
    from jav.evals_email import email_inbox, print_inbox_report

    if args.report_only:
        print_inbox_report()
    else:
        with under_budget(args, "email-inbox"):
            email_inbox(args.root, limit=args.limit, force=args.force, use_cache=not args.no_cache, jev=jev_on(args))
    return 0


def cmd_email_sample(args: argparse.Namespace) -> int:
    from jav.evals_email import email_manual_sample

    email_manual_sample()
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

    with under_budget(args, "email-determinism", reuse=False):
        email_determinism(n=args.n, limit=args.limit, jev=jev_on(args))
    return 0


def cmd_email_injection_probe(args: argparse.Namespace) -> int:
    from jav.evals_email import email_injection_probe

    from decimal import Decimal

    email_injection_probe(limit=args.limit, use_cache=not args.no_cache, jev=jev_on(args),
                          budget_usd=Decimal(args.budget_usd) if args.budget_usd else None)
    return 0


def cmd_verifier_probe(args: argparse.Namespace) -> int:
    from jav.evals import verifier_probe

    from decimal import Decimal

    jev_budget = getattr(args, "jev_budget_usd", None)
    verifier_probe(use_cache=not args.no_cache, type_key=args.type, jev_budget_usd=Decimal(jev_budget) if jev_budget else None)
    return 0


def cmd_golden(args: argparse.Namespace) -> int:
    from jav.flow import run_one

    import contextlib
    from decimal import Decimal

    from jav import evals
    from jav.core import store
    from jav.eval_report import report_budget_skips

    # 122: a separate measurement store keeps the results, to-dos and call log of the measurement out of the work store
    with store.use_store(Path(args.store)) if args.store else contextlib.nullcontext():
        jev_budget = getattr(args, "jev_budget_usd", None)
        synthetic = getattr(args, "synthetic", False)
        local = getattr(args, "cases", None)
        cases = (evals.load_case_file(Path(local), args.type) if local
                 else evals.load_synthetic_cases(args.type) if synthetic else None)
        if (synthetic or local) and not cases:
            print(f"No case for {args.type} ({local or 'configs/golden_synthetic.json'}).")
            return 1
        if local:  # 151: a local list's expectations are reference values, so its score is an agreement
            print("Local cases: the scores compare with the list's reference values (agreement, not accuracy).")
        if s_without_jev(args):
            return 2
        rows = evals.golden(args.arm, run_one, cases=cases, tracker=args.tracker, use_cache=not args.no_cache,
                            type_key=args.type, jev=jev_on(args),
                            budget_usd=Decimal(args.budget_usd) if args.budget_usd else None,
                            jev_budget_usd=Decimal(jev_budget) if jev_budget else None,
                            label="local" if local else "synthetic" if synthetic else "golden")
    # 123: exit code 3 = the budget left cases without a result
    return 3 if report_budget_skips(rows) else 0


def cmd_measure(args: argparse.Namespace) -> int:
    """188 (plan 185 T3a): every golden set with one command (`jav/goldens.py`): the type packs' data points, the type
    recognition, the email intent and the logic packs' golden sets, each as its own command measures it. Without a
    budget only earlier answers count (free); a paid measurement names exactly one golden set. Exit code: 1 a set broke
    off or a code-only set failed a case, 3 a case without a result, 2 nothing measured or refused."""
    from decimal import Decimal

    from jav import goldens

    if args.list:
        for g in goldens.sets():
            print(f"{g.key:44} {g.layer:10} {'/'.join(g.engines) or 'code':8} {g.count():4} cases  {g.what}")
        return 0
    try:
        options = goldens.Options(engine=args.engine, use_cache=not args.no_cache,
                                  jev_budget_usd=Decimal(args.jev_budget_usd) if args.jev_budget_usd else None,
                                  budget_usd=Decimal(args.budget_usd) if args.budget_usd else None)
        result = goldens.measure_round(goldens.select(args.golden), options,
                                       store_path=Path(args.store) if args.store else None)
    except (goldens.UnknownGolden, goldens.RoundRefused) as exc:
        print(exc)
        return 2
    return result.exit_code


def cmd_determinism(args: argparse.Namespace) -> int:
    from jav.evals import determinism
    from jav.flow import run_one

    if s_without_jev(args):
        return 2
    with under_budget(args, "determinism", reuse=False):
        determinism(args.arm, args.n, run_one, type_key=args.type, jev=jev_on(args))
    return 0


def register(sub) -> None:
    type_help = type_pack_help()

    p = sub.add_parser("candidates")
    p.add_argument("pdf")
    p.add_argument("--lines", action="store_true", help="a rekonstruált sorok kiírása is")
    p.add_argument("--type", default=REFERENCE_TYPE, help=type_help)
    p.set_defaults(fn=cmd_candidates)
    p = sub.add_parser("recall")
    p.add_argument("--type", default=REFERENCE_TYPE, help=type_help)
    p.set_defaults(fn=cmd_recall)
    p = sub.add_parser("run")
    p.add_argument("pdf")
    p.add_argument("--arm", choices=["S", "G"], default="S")
    p.add_argument("--case-id", default=None)
    p.add_argument("--type", default=REFERENCE_TYPE, help=type_help)
    p.add_argument("--no-tracker", action="store_true")
    p.add_argument("--no-cache", action="store_true", help="Jev kérés-cache kihagyása (élő hívás)")
    budget_args(p)
    engine_args(p, measurement=False)
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("detect", help="M1: egy dokumentum kategorizálása Jevvel")
    p.add_argument("pdf")
    p.add_argument("--tracker", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    budget_args(p)
    engine_args(p, measurement=False)
    p.set_defaults(fn=cmd_detect)
    p = sub.add_parser("detect-golden", help="M1 golden: a régi doc-triage + doc-extract típus-címkéin")
    p.add_argument("--no-cache", action="store_true")
    engine_args(p, measurement=True)  # 086: GPT recognises the type
    p.add_argument("--keys-only", action="store_true", help="086: with --engine gpt, offer the types by their keys only")
    p.add_argument("--budget-usd", help="086/122: hard budget for the whole measurement, for the engine that answers "
                                        "(OpenAI with --engine gpt, JEV otherwise); the other providers and Azure get none")
    p.add_argument("--cases", help="122: a local case list (JSON, outside git) instead of the golden set")
    p.add_argument("--store", help="122: a separate measurement store (results, to-dos and call log stay out of the work store)")
    p.set_defaults(fn=cmd_detect_golden)
    p = sub.add_parser("detect-determinism", help="M1: ismételt futások cache nélkül a detect-goldenen, típus-flipek és conf-szórás")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--limit", type=int)
    budget_args(p)
    engine_args(p, measurement=True)
    p.set_defaults(fn=cmd_detect_determinism)
    p = sub.add_parser("detect-corpus", help="M1 bejárás egy mappán (rekurzív), folytatható; riport típus × év")
    p.add_argument("root")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--force", action="store_true", help="a már kategorizáltakat is újra")
    p.add_argument("--report-only", action="store_true")
    p.add_argument("--redo-unknown", action="store_true", help="csak az 'unknown' / bizonytalan dokumentumok újra")
    p.add_argument("--no-cache", action="store_true")
    budget_args(p)
    engine_args(p, measurement=False)
    p.set_defaults(fn=cmd_detect_corpus)
    p = sub.add_parser("detect-sample", help="M1 kézi ellenőrző Markdown-minta a kategorizált korpuszból")
    p.add_argument("root")
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(fn=cmd_detect_sample)
    p = sub.add_parser("email-golden", help="M3 golden: a régi 96 esetes intent-golden (10_AIFLOW_V4) Jev-Choice-szal")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--limit", type=int)
    engine_args(p, measurement=True)  # 089: GPT recognises the intent
    p.add_argument("--budget-usd", help="089: hard OpenAI budget for the whole measurement")
    p.add_argument("--jev-budget-usd", help="127: hard JEV budget for the whole measurement; with either budget, a provider "
                                            "without one (Azure always) cannot be called")
    p.set_defaults(fn=cmd_email_golden)
    p = sub.add_parser("email-inbox", help="M3: inbox/<mailbox>/<msgid>/ mappák bejárása (Outlook-lekérés után), folytatható")
    p.add_argument("root")
    p.add_argument("--limit", type=int)
    p.add_argument("--force", action="store_true", help="a már kategorizált levelek is újra")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--report-only", action="store_true", help="csak a store-riport, futtatás nélkül")
    budget_args(p)
    engine_args(p, measurement=False)
    p.set_defaults(fn=cmd_email_inbox)
    p = sub.add_parser("email-sample", help="M3: kézi címkéző Markdown-lista az élő levelekből (runs/*_email_manual_sample.md)")
    p.set_defaults(fn=cmd_email_sample)
    p = sub.add_parser("eval-report", help="közös eval-riport a nyers futásokból ($0): kérdésenkénti pontosság + sávok, kalibráció (ECE), top-prob vs. conf, policy-sáv újraértékelés, determinizmus")
    p.add_argument("paths", nargs="*", help="runs/*.jsonl fájlok; üresen: mintánként a legfrissebb")
    p.add_argument("--out", help="a Markdown célfájlja (alap: runs/<idő>_eval_report.md)")
    p.set_defaults(fn=cmd_eval_report)
    p = sub.add_parser("email-determinism", help="M3: ismételt futások cache nélkül, intent-flipek és conf-szórás")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--limit", type=int)
    budget_args(p)
    engine_args(p, measurement=True)
    p.set_defaults(fn=cmd_email_determinism)
    p = sub.add_parser("email-injection-probe", help="M3: beszúrt-utasítás (promptinjekció) szonda a golden levelek tiszta és elrontott változatain (runs/*_email_injection_probe.jsonl)")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--no-cache", action="store_true")
    engine_args(p, measurement=True)  # 089: GPT answers the injection question
    p.add_argument("--budget-usd", help="089: hard OpenAI budget for the whole probe (JEV and Azure get none)")
    p.set_defaults(fn=cmd_email_injection_probe)
    p = sub.add_parser("verifier-probe", help="Jev-ellenőrző kalibrációs szonda a golden kivonatokon (OpenAI nélkül); nyers futás runs/*_verifier_probe.jsonl")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--type", default=REFERENCE_TYPE, help=type_help)
    p.add_argument("--jev-budget-usd", help="127: hard JEV budget for the whole probe (no other provider can be called)")
    p.set_defaults(fn=cmd_verifier_probe)
    p = sub.add_parser("golden", help="M2 golden egy karra és típus-csomagra (runs/[<típus>_]golden_<kar>.jsonl)")
    p.add_argument("--arm", choices=["S", "G"], required=True)
    p.add_argument("--type", default=REFERENCE_TYPE, help=type_help)
    p.add_argument("--tracker", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    engine_args(p, measurement=True)  # 086: the G path verified by the code alone (runs/*_golden_G_nojev.jsonl)
    p.add_argument("--budget-usd", help="086: hard OpenAI budget for the whole measurement")
    p.add_argument("--jev-budget-usd", help="127: hard JEV budget for the whole measurement; with either budget, a provider "
                                            "without one (Azure always) cannot be called")
    p.add_argument("--synthetic", action="store_true", help="127: the synthetic golden cases of the type "
                                                             "(configs/golden_synthetic.json) instead of the legacy set")
    p.add_argument("--cases", help="151: a local case list (JSON, outside git) with reference values; the run file is "
                                   "named <type>_local_<arm> and its scores are an agreement, not an accuracy")
    p.add_argument("--store", help="122: a separate measurement store (results, to-dos and call log stay out of the work store)")
    p.set_defaults(fn=cmd_golden)
    p = sub.add_parser("measure", help="188: every golden set with one command (data points, types, intents, logic "
                                       "packs); without a budget only earlier answers count")
    p.add_argument("golden", nargs="*", help="golden sets by key or its first parts (datapoints:invoice_hu, types, "
                                             "reconcile); a whole key names its own set alone; none: every golden set")
    p.add_argument("--list", action="store_true", help="list the golden sets with their case counts, measure nothing")
    p.add_argument("--no-cache", action="store_true", help="ask again (live calls; needs a budget)")
    engine_args(p, measurement=True)
    budget_args(p)
    p.add_argument("--store", help="122: a separate measurement store (results, to-dos and call log stay out of the work store)")
    p.set_defaults(fn=cmd_measure)
    p = sub.add_parser("determinism")
    p.add_argument("--arm", choices=["S", "G"], required=True)
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--type", default=REFERENCE_TYPE, help=type_help)
    budget_args(p)
    engine_args(p, measurement=True)
    p.set_defaults(fn=cmd_determinism)
