"""The command line is put together from its command modules (202, plan G-core-generalisation M3a).

Plain-language summary: the command line used to be one long function that named every command, the finance and email
domains' among them. Now each theme has its own module with a `register(sub)` function, and a domain names its own
command module in its domain module (`COMMANDS`), as it names its service addresses (`SERVICE`). `jav.cli` only puts
them together and imports no domain's code. The commands are the same 83 as before the split, each with the same
arguments, defaults and help (checked once against a dump of the old parser); this test keeps the list and shows where
each command lives. 204 (R1b): the seven learning commands left with the archived learning branches (76). 218: the
calculation snapshots' `snapshot` (77).

No AI call, no store.
"""

from __future__ import annotations

import argparse
import importlib

from jav import cli
from jav.domains import DOMAINS

COMMANDS = {
    "admin", "backup", "before-after-diff", "before-after-replay", "before-after-snapshot", "burr-prune",
    "calls-resolve", "calls-uncertain", "candidates", "configs", "data-guard", "deps-audit", "detect", "detect-corpus",
    "detect-determinism", "detect-golden", "detect-sample", "determinism", "docs", "duplicates", "email",
    "email-determinism", "email-golden", "email-inbox", "email-ingest-server", "email-injection-probe", "email-sample",
    "eval-report", "flows", "fx-rates", "golden", "hooks-install", "lang-guard", "legacy-compare", "legacy-import",
    "measure", "ocr", "ocr-rekey",
    "output-template-activate", "output-template-add", "output-template-choose", "output-template-preview",
    "output-template-retire", "output-templates", "own-tax", "package-versions-backfill", "preflight",
    "processing-migrate", "recall", "recipes", "reconcile", "reconcile-ai", "reconcile-versions-backfill", "reground",
    "run", "run-approve", "run-cancel", "run-list", "run-names", "run-show", "run-start", "serve", "snapshot", "statement-table",
    "store", "type-activate", "type-candidate", "type-propose", "type-withdraw",
    "verifier-probe", "worker", "worker-status", "worker-stop", "wp-assign", "wp-create", "wp-list", "wp-show",
}


def _registered() -> dict[str, dict[str, argparse.ArgumentParser]]:
    """Each command module's commands, registered on a parser of its own."""
    out = {}
    for name in cli.command_modules():
        sub = argparse.ArgumentParser().add_subparsers()
        importlib.import_module(name).register(sub)
        out[name] = dict(sub.choices)
    return out


def test_the_command_line_has_the_same_commands_as_before_the_split():
    registered = _registered()
    names = [c for commands in registered.values() for c in commands]
    assert len(names) == len(set(names)) == 77
    assert set(names) == COMMANDS


def test_each_command_is_handled_in_the_module_that_registers_it():
    for module, commands in _registered().items():
        for command, parser in commands.items():
            assert parser.get_default("fn").__module__ == module, command


def test_a_domain_names_its_own_commands():
    domains = {name: importlib.import_module(name) for name in DOMAINS}
    assert domains["jav.domains.finance"].COMMANDS == ("jav.domains.finance.finance_cli",)
    assert domains["jav.domains.email"].COMMANDS == ("jav.domains.email.email_cli",)
    finance = _registered()["jav.domains.finance.finance_cli"]
    assert set(finance) == {"duplicates", "own-tax", "reconcile", "reconcile-ai", "statement-table",
                            "reconcile-versions-backfill", "fx-rates"}
    assert set(_registered()["jav.domains.email.email_cli"]) == {"email", "email-ingest-server"}
    assert cli.command_modules()[: len(cli.SHARED_COMMANDS)] == cli.SHARED_COMMANDS
