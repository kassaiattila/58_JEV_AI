"""Smoke test: the venv and the key, and with a budget one live call to the TypeSafe API.

Run:  .venv/Scripts/python.exe smoke_test.py                          # the venv and the key; nothing is sent
      .venv/Scripts/python.exe smoke_test.py --jev-budget-usd 0.01    # and one live JEV call under that budget

265 (code review TOOL-14): the key is named only by its length, never by any of its characters, and the live call goes
through `ask()` under a command's budget (`calls.measurement`): it is in the ledger and the call log like any other.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from typesafe_sdk import Choice, Noul, Score

from jav.core.config import ENV_FILE, MissingAPIKeyError, get_api_key

# a sample ticket in the documents' language, the questions in English (JEV playbook)
STATE = {"document": "Kétszer vontátok le a díjat. Kérem javítsák sürgősen!"}
QUESTIONS = {
    "billing": Noul(instructions="Is this ticket about billing?"),
    "tone": Choice(instructions="What is the customer's tone?", criteria={"calm": None, "frustrated": None, "angry": None}),
    "urgency": Score(instructions="How urgent is this ticket?", criteria=["it can wait", "this week", "today"]),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jev-budget-usd", help="a hard JEV budget for one live call; without it nothing is sent")
    args = ap.parse_args(argv)
    print(f"Python : {sys.version.split()[0]}  ({sys.executable})")
    print(f".env   : {ENV_FILE}  ({'present' if ENV_FILE.exists() else 'MISSING'})")
    try:
        key = get_api_key()
    except MissingAPIKeyError as exc:
        print(f"\n[ERROR] {exc}")
        return 1
    print(f"Key    : present ({len(key)} characters)")
    if not args.jev_budget_usd:
        print("\nNo live call: give --jev-budget-usd (for example 0.01) to send one under that budget.")
        return 0

    from jav.ai import jev
    from jav.core import calls

    print("\nA live System One call…")
    with calls.measurement("smoke-test", {"jev": Decimal(args.jev_budget_usd)}):
        try:
            result = jev.get_adapter().ask("smoke_test", STATE, QUESTIONS, run_id="smoke-test", use_cache=False)
        except jev.JevUnavailableError as exc:
            print(f"[ERROR] The JEV call failed: {exc.reason}")
            return 1
    response = result.response
    print(f"  billing : {response.nouls['billing'].noul}")
    print(f"  tone    : {response.choices['tone'].choice}")
    print(f"  urgency : {response.scores['urgency'].score}")
    print(f"  cost    : {result.call.cost_usd:.6f} USD")
    print("\nOK - the environment works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
