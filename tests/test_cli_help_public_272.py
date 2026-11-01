"""272 (K6, the rest of X-24): the command line's help says nothing of the development process.

265 (X-24) took the round numbers out of 64 help texts but left those starting with a three-digit round ("071 data
guard: ...", "089: hard OpenAI budget ...") and a stage code in the usage list ("040 K1"). Every help text a person
can print (each command's, each option's, and the usage list) is now checked with the public documents' patterns.
No command runs.
"""

from __future__ import annotations

import argparse
import importlib

import jav.cli as cli
from jav.app import registrations
from tests.test_public_docs_076 import _hits


def _parser() -> argparse.ArgumentParser:
    registrations.load_all()
    ap = argparse.ArgumentParser(prog="jav", description=cli.__doc__)
    sub = ap.add_subparsers(dest="cmd")
    for name in cli.command_modules():
        importlib.import_module(name).register(sub)
    return ap


def _texts(ap: argparse.ArgumentParser) -> list[str]:
    out = [ap.description or ""]
    for action in ap._actions:
        out.append(action.help or "")
        if isinstance(action, argparse._SubParsersAction):
            out += [choice.help or "" for choice in action._choices_actions]
            for child in action.choices.values():
                out += _texts(child)
    return out


def test_no_help_text_names_a_round_a_stage_or_a_plan() -> None:
    found = [hit for text in _texts(_parser()) for hit in _hits(text)]
    assert found == []


def test_every_command_is_read() -> None:
    texts = _texts(_parser())
    assert len(texts) > 200 and any("data guard" in t for t in texts)
