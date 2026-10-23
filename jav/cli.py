"""Command line: `python -m jav.cli <command>`.

  candidates <pdf>            candidates by kind (no API)
  recall                      candidate recall on the golden set (no API) - the ceiling of the S path
  run <pdf> --arm S|G         runs one invoice through the Burr graph
  golden --arm S|G            golden eval for one path
  measure [golden ...] [--list]   188: every golden set with one command (data points, types, intents, logic packs)
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
import importlib
import sys

import jav  # noqa: F401  - sets up UTF-8 output

# 202 (plan G-core-generalisation M3a): the shared command modules, each with its `register(sub)`; a domain names its
# own (`COMMANDS` in its domain module), so this module imports no domain's code
SHARED_COMMANDS = ("jav.work_cli", "jav.measure_cli", "jav.maintenance_cli", "jav.outputs_cli",
                   "jav.type_teaching_cli")


def command_modules() -> tuple[str, ...]:
    """The shared command modules, then each domain's in `DOMAINS` order."""
    from jav.domains import DOMAINS

    return SHARED_COMMANDS + tuple(name for domain in DOMAINS for name in getattr(importlib.import_module(domain), "COMMANDS", ()))


def main(argv: list[str] | None = None) -> int:
    from jav.app import registrations

    registrations.load_all()  # 173 (plan 170 E2): every command, the worker included, with all the registrations
    ap = argparse.ArgumentParser(prog="jav", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in command_modules():
        importlib.import_module(name).register(sub)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
