"""Command line, the finance domain (202, plan G-core-generalisation M3a): duplicates, own tax numbers, the
reconciliation, bank statement tables and exchange rates. The finance domain names this module (`COMMANDS`).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from jav.cli_options import jev_on


def cmd_duplicates(args: argparse.Namespace) -> int:
    """126: the duplicate invoices already in the store (read only; counts and kinds, no values), and with --write the
    one-off to-do on the later document of each undecided pair in runs not yet approved (DECISIONS 126). Free."""
    from jav import checks

    result = checks.get("duplicate_scan").run(write=args.write)
    print(f"documents compared: {result['documents']}")
    print(f"groups: {result['groups']} ({result['files']} files; sizes {result['group_sizes']})")
    print(f"pairs by kind: {result['pairs']}")
    print(f"to-dos to open: {result['to_open']}; skipped: {result['skipped']}")
    if args.write:
        print(f"to-dos written: {result['written']}")
    return 0


def cmd_own_tax(args: argparse.Namespace) -> int:
    """157: the incoming invoices already in the store whose supplier tax number is an own party's (read only; counts
    only, no values), and with --write the one-off to-do of 134 on runs not yet approved. Free."""
    from jav import checks

    result = checks.get("own_tax_scan").run(write=args.write)
    print(f"incoming invoices checked: {result['documents']}")
    print(f"an own party's tax number as the supplier's: {result['flagged']}")
    print(f"to-dos to open: {result['to_open']}; skipped: {result['skipped']}")
    if args.write:
        print(f"to-dos written: {result['written']}")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    """128: invoice <-> bank statement line pairs proposed by code (read only; counts, no values), or with --golden the
    synthetic golden cases (configs/golden_reconcile.json). 137: the pairs are decided in a reconciliation package; the
    command opens no to-do. Free."""
    from jav.domains.finance import reconcile

    if args.golden:
        score = reconcile.golden_score()
        reconcile.print_golden_score(score)
        return 0 if not score["failures"] else 1
    r = reconcile.scan()
    print(f"statements: {r['statements']} (verified by their balances: {r['verified_statements']}), lines: {r['lines']}")
    print(f"invoices: {r['invoices']}; excluded by reason: {r['excluded_invoices']}")
    print(f"lines excluded by reason: {r['excluded_lines']}")
    print(f"proposed pairs: {r['proposed_pairs']} (with more than one candidate: {r['multiple_candidates']}); "
          f"same amount, no signal: {r['amount_only_pairs']}; signal with a different amount: {r['amount_differs_pairs']}")
    print(f"signals: {r['signals']}; names learnt from confirmations: {r['learned_names']}")
    print(f"invoice status: {r['invoice_status']}")
    print(f"lines without a proposed pair: {r['unpaired_lines']}")
    print(f"confirmed pairs: {r['confirmed_pairs']}; decisions: {r['decisions']}")
    print(f"amount relations: {r['relations']}; card pair rates known: {r['rates']}")
    print(f"engine {r['engine_version']}, config {r['config_hash']}")
    return 0


def cmd_reconcile_ai(args: argparse.Namespace) -> int:
    """134: AI proposals (JEV and/or GPT) for the lines a reconciliation package still has to decide: which preselected
    invoice a line pays and what kind of payment it is. Without a budget only the free estimate; with the owner's
    sub-budget (--jev-budget-usd, --budget-usd for OpenAI) the paid measurement: answers stored per line and engine,
    raw answers in runs/. 136: only the lines without an answer (--redo: all), the kind once per partner. 158: --golden
    measures the incoming money kind question on the invented lines instead. Counts only, no values printed."""
    from decimal import Decimal

    from jav.domains.finance import reconcile_ai

    # 160-D (Sz7): without --engine the proposals follow the application's AI engine (JEV and GPT: both engines, GPT
    # only: GPT alone); the golden measurement asks both unless told, as every measurement does
    engine = args.engine or ("both" if args.golden or jev_on(args) else "gpt")
    engines = list(reconcile_ai.ENGINES) if engine == "both" else [engine]
    limits = {}
    if args.jev_budget_usd:
        limits["jev"] = Decimal(args.jev_budget_usd)
    if args.budget_usd:
        limits["openai"] = Decimal(args.budget_usd)
    if args.golden:
        try:
            g = reconcile_ai.golden(engines=engines, limits=limits, use_cache=not args.no_cache)
        except ValueError as exc:
            print(f"{exc} (jev: --jev-budget-usd, gpt: --budget-usd)")
            return 2
        reconcile_ai.print_golden(g)
        return 0
    if not args.workpackage_id:
        print("a reconciliation package (wp-...) is needed, or --golden")
        return 2
    if args.evaluate:  # 135: free, read only - the stored answers against a person's decisions
        ev = reconcile_ai.evaluate(args.workpackage_id)
        print(f"lines a person decided (paired or marked) that have AI answers: {ev['lines_decided']}")
        for engine, t in ev["engines"].items():
            print(f"{engine}: invoice choice {t['pays']}; kind of payment {t['kind']}")
        return 0
    if not limits:
        est = reconcile_ai.estimate(args.workpackage_id, redo=args.redo, stale=args.stale, incoming_only=args.incoming)
        print(f"lines to ask about: {est['lines']}, with preselected invoices: {est['with_options']} ({est['options']} options)")
        for engine, plan in est["plan"].items():
            print(f"{engine}: answered already {plan['answered']}; requests {plan['requests']} (with invoices {plan['with_options']});"
                  f" taking a partner's answer over {plan['inherited']}")
        print(f"sum of the worst-case reservations (a measurement needs its actual cost plus one): {est['reservations_usd']}")
        print("free estimate only; a measurement needs --jev-budget-usd and/or --budget-usd (the owner's sub-budget)")
        return 0
    missing = [e for e in engines if {"jev": "jev", "gpt": "openai"}[e] not in limits]
    if missing:
        print(f"no budget for: {', '.join(missing)} (jev: --jev-budget-usd, gpt: --budget-usd)")
        return 2
    r = reconcile_ai.run(args.workpackage_id, engines=engines, limits=limits, max_lines=args.max_lines, use_cache=not args.no_cache,
                         redo=args.redo, stale=args.stale, incoming_only=args.incoming)
    print(f"lines asked: {r['lines']}; per engine: {r['counts']}")
    print(f"budget scope {r['scope']}: {r['usage']}")
    print(f"raw answers: {r['raw']}; config jev {r['jev_config']}, gpt {r['gpt_config']}")
    return 0


def cmd_statement_table(args: argparse.Namespace) -> int:
    """136 (E4): a bank's tabular statement export (a workbook or a CSV file) read by code, free: the accounts found
    with their line counts, dates and checks; account numbers only by their last four characters, no lines or
    balances printed."""
    from jav.domains.finance import statement_table

    try:
        reading = statement_table.read(Path(args.file))
    except (OSError, statement_table.StatementTableError) as exc:
        print(f"not readable as a statement table: {exc}")
        return 2
    survey = statement_table.survey(reading)
    print(f"profile {survey['profile']} ({survey['institution']}); repairs: {', '.join(survey['repairs']) or 'none'}")
    for n, a in enumerate(survey["accounts"], start=1):
        print(f"{n:>2}. {a['title']} ({a['currency']}) {a['account'] or '-'}: {a['lines']} lines {a['first'] or ''} - {a['last'] or ''};"
              f" period {a['period_start']} - {a['period_end']}; checks {'ok' if a['checks_ok'] else 'FAILED'}"
              + (f"; {a['problems']} unreadable lines" if a["problems"] else ""))
    return 0


def cmd_reconcile_versions_backfill(args: argparse.Namespace) -> int:
    """178 (plan 170 L4): the stored file of every approved reconciliation statement approved or reopened before 178,
    made now from its stored statement as the download made it (idempotent; --dry-run writes nothing)."""
    from jav.domains.finance import reconcile_statement

    done = reconcile_statement.backfill_files(dry_run=args.dry_run)
    for e in done:
        print(f"{e['workpackage_id']} version {e['version']} ({e['state']})" + (" (dry run)" if args.dry_run else ""))
    print(f"versions: {len(done)}")
    return 0


def cmd_fx_rates(args: argparse.Namespace) -> int:
    """130: the stored MNB exchange rates (counts and the latest attempts, no rates printed); with --fetch FROM TO one
    request for the span. Free; only the dates and the currency codes leave the machine."""
    from datetime import date

    from jav import cfg
    from jav.domains.finance import fx

    if args.fetch:
        start, end = (date.fromisoformat(d) for d in args.fetch)
        codes = [c.strip().upper() for c in (args.currency or ",".join(cfg.load("fx")["currencies"])).split(",") if c.strip()]
        try:
            print(f"published days received: {fx.fetch(start, end, codes)}")
        except (fx.FxUnavailableError, fx.FxRefusedError) as exc:
            print(f"fetch did not succeed: {exc}")
            return 1
    s = fx.status()
    for currency, row in s["currencies"].items():
        print(f"{currency}: {row['days']} published days, {row['first']} - {row['last']}")
    if not s["currencies"]:
        print("no stored rates")
    for a in s["attempts"]:
        print(f"attempt {a['fetched_at']}: {a['currencies']} {a['start_day']} - {a['end_day']} -> {a['status']}"
              f"{' (' + str(a['days']) + ' days)' if a['status'] == 'ok' else ''}{' ' + a['error'] if a['error'] else ''}")
    print(f"config {s['config_hash']}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("duplicates", help="126: duplicate invoices in the store (read only); --write opens the to-do on runs not yet approved")
    p.add_argument("--write", action="store_true", help="open the duplicate to-dos (once; a decided pair or an approved run is skipped)")
    p.set_defaults(fn=cmd_duplicates)
    p = sub.add_parser("own-tax", help="157: incoming invoices whose supplier tax number is an own party's (read only); --write opens the to-do on runs not yet approved")
    p.add_argument("--write", action="store_true", help="open the to-dos (once; an approved run or a command-line result is skipped)")
    p.set_defaults(fn=cmd_own_tax)
    p = sub.add_parser("reconcile", help="128: invoice <-> bank statement line pairs proposed by code (read only); --golden: the synthetic cases")
    p.add_argument("--golden", action="store_true", help="score the synthetic golden cases (configs/golden_reconcile.json)")
    p.set_defaults(fn=cmd_reconcile)
    p = sub.add_parser("reconcile-ai", help="134: AI proposals (JEV / GPT) for a reconciliation package's lines; without a budget only the free estimate")
    p.add_argument("workpackage_id", nargs="?", help="the reconciliation package (wp-...); not with --golden")
    p.add_argument("--engine", choices=["jev", "gpt", "both"],
                   help="160-D: default: both with the application's JEV and GPT, gpt with GPT only; --golden: both")
    p.add_argument("--no-jev", dest="engine", action="store_const", const="gpt", help="the same as --engine gpt")
    p.add_argument("--jev-budget-usd", help="the JEV sub-budget of the measurement (USD)")
    p.add_argument("--budget-usd", help="the OpenAI sub-budget of the measurement (USD)")
    p.add_argument("--max-lines", type=int, help="ask only the first N lines")
    p.add_argument("--no-cache", action="store_true", help="JEV: no cached answers (live calls)")
    p.add_argument("--redo", action="store_true", help="136: ask the lines that have an answer again (default: only the new ones)")
    p.add_argument("--stale", action="store_true", help="147: also ask the lines whose answer came from an older version of the question")
    p.add_argument("--incoming", action="store_true", help="158: ask about the incoming money alone")
    p.add_argument("--evaluate", action="store_true",
                   help="free: compare the stored answers with a person's decisions on the package's lines")
    p.add_argument("--golden", action="store_true",
                   help="158: the incoming money kind question on the invented golden lines (configs/golden_credit_kinds.json);"
                        " needs the sub-budget of each engine, stores nothing")
    p.set_defaults(fn=cmd_reconcile_ai)
    p = sub.add_parser("statement-table", help="136: a tabular bank statement export read by code (free): the accounts found and their checks;"
                                               " 141: also a statement printed as text (a CIB PDF or text export), a camt.053 XML statement or a folder of them")
    p.add_argument("file", help="the workbook (.xlsx), CSV, Excel 2003 XML, PDF or text file, or a folder")
    p.set_defaults(fn=cmd_statement_table)
    p = sub.add_parser("reconcile-versions-backfill", help="178: the stored file of every approved reconciliation statement"
                                                           " approved or reopened before v1.23.0 (idempotent)")
    p.add_argument("--dry-run", action="store_true", help="list the versions, write nothing")
    p.set_defaults(fn=cmd_reconcile_versions_backfill)
    p = sub.add_parser("fx-rates", help="130: the stored MNB exchange rates (counts); --fetch FROM TO: fetch a span (free)")
    p.add_argument("--fetch", nargs=2, metavar=("FROM", "TO"), help="fetch the published days of the span (YYYY-MM-DD)")
    p.add_argument("--currency", help="comma separated codes (default: configs/fx.json currencies)")
    p.set_defaults(fn=cmd_fx_rates)
