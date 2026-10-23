"""Command line, teaching a type (202, plan G-core-generalisation M3a; 197-199). Registered by `jav.cli`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _print_switches(switched: list) -> None:  # list[type_teaching.Switch]
    from jav.core import cfg

    for s in switched:
        line = f"{s.key} {s.version}: {'on' if s.detected else 'off'}"
        m = cfg.load(f"type:{s.key}")["meta"].get("taught", {}).get("measured") if s.detected else None
        if m:
            line += f" (its evaluation half: {m['right']}/{m['scored']} {m['unit']}, {m['receipt']} at {m['commit']})"
        print(line)
    print("\nThe running service and worker see it after they restart. Next: python -m jav.cli docs, and the family's "
          "golden runs on a clean working tree.")


def cmd_type_propose(args: argparse.Namespace) -> int:
    """197 (plan 197 K2): field proposals for teaching a type, from a held-out family's development half's general facts
    (`jav/type_teaching.py`); no AI call, names and counts only. Exit code 2: the half has no measured facts."""
    from jav import type_teaching

    try:
        report = type_teaching.proposal_report(args.family, min_documents=args.min_documents)
    except (type_teaching.TeachingError, KeyError) as exc:
        print(exc)
        return 2
    type_teaching.print_proposal(report)
    if args.shapes:
        print("\nThe written forms of the development half's expected values (a letter `a`, a digit `d`):")
        for field, shapes in type_teaching.expected_shapes(args.family).items():
            print(f"  {field}: " + ", ".join(f"{s} ({n})" for s, n in shapes.items()))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\nWritten: {args.out}")
    return 0


def cmd_type_candidate(args: argparse.Namespace) -> int:
    """197 (plan 197 K2b): the candidate type pack of an edited draft (`jav/type_teaching.py`): its pack, prompt, schema
    and verification call site, never picked by detection; then the shared registries' entries to add by hand. Exit
    code 2: no such draft, or a pack of that name that is not its candidate."""
    from pydantic import ValidationError

    from jav import type_teaching
    from jav.core.config import PROJECT_ROOT

    try:
        draft = type_teaching.load_draft(args.key)
        paths = type_teaching.write_candidate(draft)
    except (type_teaching.TeachingError, ValidationError) as exc:
        print(exc)
        return 2
    print("Written:\n" + "\n".join(f"  {p.relative_to(PROJECT_ROOT).as_posix()}" for p in paths))
    entries = type_teaching.registry_entries(draft)
    print("\nAdd by hand, each in its file's own layout:\n" + "\n".join(f"  - {e}" for e in entries) if entries
          else "\nThe shared registries know the candidate already.")
    return 0


def cmd_type_activate(args: argparse.Namespace) -> int:
    """199 (plan 197 K2d): detection may pick a type pack in its family from now on (`jav/type_teaching.py`); a taught
    pack only with a clean, complete measurement of its evaluation half on its current files. Exit code 2: refused,
    nothing written."""
    from jav import type_teaching

    try:
        switched = type_teaching.activate(args.key, replace=args.replace)
    except type_teaching.TeachingError as exc:
        print(exc)
        return 2
    _print_switches(switched)
    return 0


def cmd_type_withdraw(args: argparse.Namespace) -> int:
    """199 (plan 197 K2d): detection no longer picks a type pack; its files stay for its earlier results. Exit code 2:
    refused, nothing written."""
    from jav import type_teaching

    try:
        switched = type_teaching.withdraw(args.key, restore=args.restore)
    except type_teaching.TeachingError as exc:
        print(exc)
        return 2
    _print_switches(switched)
    return 0


def register(sub) -> None:
    p = sub.add_parser("type-propose", help="197: field proposals for teaching a type from a held-out family's "
                                            "development half's general facts (no AI call)")
    p.add_argument("family", help="a family of configs/golden_facts.json (a type pack's key)")
    p.add_argument("--min-documents", type=int, default=3, help="the fewest development documents a name recurs in")
    p.add_argument("--out", help="write the proposal as JSON (names and counts only)")
    p.add_argument("--shapes", action="store_true", help="also the written forms of the development half's expected "
                                                         "values (letters and digits masked)")
    p.set_defaults(fn=cmd_type_propose)
    p = sub.add_parser("type-candidate", help="197: a taught type's candidate pack from its edited draft "
                                              "(configs/type_drafts/<key>.json); never detected, no AI call")
    p.add_argument("key", help="the draft's key")
    p.set_defaults(fn=cmd_type_candidate)
    p = sub.add_parser("type-activate", help="199: detection may pick a type pack in its family (a taught one only "
                                             "with a measurement of its evaluation half); no AI call")
    p.add_argument("key", help="the type pack's key")
    p.add_argument("--replace", help="the family's pack it takes over; detection no longer picks that one")
    p.set_defaults(fn=cmd_type_activate)
    p = sub.add_parser("type-withdraw", help="199: detection no longer picks a type pack; its files stay; no AI call")
    p.add_argument("key", help="the type pack's key")
    p.add_argument("--restore", action="store_true", help="turn the pack it replaced back on")
    p.set_defaults(fn=cmd_type_withdraw)
