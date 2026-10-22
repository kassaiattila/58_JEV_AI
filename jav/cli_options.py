"""The options and helpers the command-line modules share (202, plan G-core-generalisation M3a): the sub-budgets of a
command that can make paid calls, the AI engine, the reference type and the type packs' help line."""

from __future__ import annotations

import argparse
from contextlib import contextmanager



@contextmanager
def under_budget(args: argparse.Namespace, name: str, *, reuse: bool | None = None):
    """160 (review AI-8): a command that can make paid calls runs under the owner's sub-budget only: `--jev-budget-usd`,
    `--budget-usd` (OpenAI), Azure never. Without one only earlier answers count (the JEV cache): a live call is refused
    and becomes the item's to-do, so a forgotten budget cannot spend. 160-D: an earlier GPT answer to the same question
    is reused as the JEV cache is, unless `--no-cache`; a determinism measurement passes `reuse=False`."""
    from datetime import datetime
    from decimal import Decimal

    from jav.runtime import calls

    limits = {p: Decimal(v) for p, v in (("jev", getattr(args, "jev_budget_usd", None)),
                                         ("openai", getattr(args, "budget_usd", None))) if v}
    if not limits:
        print(calls.NO_BUDGET_NOTE)
    if reuse is None:
        reuse = not getattr(args, "no_cache", False)
    with calls.measurement(f"cli-{datetime.now():%Y%m%d_%H%M%S}-{name}", limits, reuse=reuse):
        yield


def budget_args(p: argparse.ArgumentParser) -> None:
    """160: the sub-budgets of a command that can make paid calls (`under_budget`)."""
    p.add_argument("--jev-budget-usd", help="160: hard JEV budget for the command; without any budget only earlier answers count")
    p.add_argument("--budget-usd", help="160: hard OpenAI budget for the command; Azure is never called from here")


def engine_args(p: argparse.ArgumentParser, *, measurement: bool) -> None:
    """160-D (plan F-csak-gpt Sz5): the AI engine of a command that asks AI; `--no-jev` stays as the alias of
    `--engine gpt`. A processing command follows the application's AI engine when it names none, as a work package
    does; a measurement measures JEV and GPT unless told otherwise, so that its run file says what it measured."""
    default = "the application's AI engine" if not measurement else "jev (a measurement does not follow the application)"
    p.add_argument("--engine", choices=["jev", "gpt"], default="jev" if measurement else None,
                   help=f"160-D: jev = JEV and GPT, gpt = GPT only, without JEV (paid OpenAI calls); default: {default}")
    p.add_argument("--no-jev", dest="engine", action="store_const", const="gpt", help="the same as --engine gpt")


def jev_on(args: argparse.Namespace) -> bool:
    engine = args.engine
    if engine is None:
        from jav import app_settings

        engine = app_settings.engine_default()
    return engine == "jev"


REFERENCE_TYPE = "invoice_hu"
"""202: the `--type` default of the commands that measure or run one type pack: the reference flow (the shared code
itself names the type everywhere)."""
S_NEEDS_JEV = "The S path needs JEV (JEV chooses among the candidates the code finds): use --arm G, or --engine jev."


def s_without_jev(args: argparse.Namespace) -> bool:
    """160-D: the S path without JEV is refused before anything runs."""
    if args.arm == "S" and not jev_on(args):
        print(S_NEEDS_JEV)
        return True
    return False


def type_pack_help() -> str:
    """The `--type` option's help: every type pack and the reference default."""
    from jav.typepack import keys as pack_keys

    return "típus-csomag (configs/types/<típus>.json): " + " | ".join(pack_keys()) + f" (alap: {REFERENCE_TYPE})"
