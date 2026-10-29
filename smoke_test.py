"""Smoke test: the venv, the key and a live call to the TypeSafe API in one go.

Run:  .venv/Scripts/python.exe smoke_test.py
"""

from __future__ import annotations

import sys

from typesafe_sdk import Choice, Noul, Score, TypeSafeAuthenticationError, TypeSafeError

from jav.core.config import ENV_FILE, MissingAPIKeyError, get_api_key, make_client


def main() -> int:
    print(f"Python : {sys.version.split()[0]}  ({sys.executable})")
    print(f".env   : {ENV_FILE}  ({'present' if ENV_FILE.exists() else 'MISSING'})")

    try:
        key = get_api_key()
    except MissingAPIKeyError as exc:
        print(f"\n[HIBA] {exc}")
        return 1
    print(f"Kulcs  : {key[:6]}…{key[-4:]}  ({len(key)} karakter)")

    print("\nA live System One call…")
    try:
        with make_client() as client:
            response = client.system_one(
                state={"document": "Kétszer vontátok le a díjat. Kérem javítsák sürgősen!"},
                questions={
                    "billing": Noul(instructions="Számlázásról szól ez a ticket?"),
                    "tone": Choice(
                        instructions="Milyen az ügyfél hangneme?",
                        criteria={"nyugodt": None, "frusztrált": None, "dühös": None},
                    ),
                    "urgency": Score(
                        instructions="Mennyire sürgős ez a ticket?",
                        criteria=["ráér", "ezen a héten", "ma"],
                    ),
                },
            )
    except TypeSafeAuthenticationError as exc:
        print(f"[ERROR] The API refused the key: {exc}")
        return 1
    except TypeSafeError as exc:
        print(f"[ERROR] The TypeSafe call failed: {type(exc).__name__}: {exc}")
        return 1

    billing = response.nouls["billing"]
    tone = response.choices["tone"]
    urgency = response.scores["urgency"]

    print(f"  billing : {billing.noul}")
    print(f"  tone    : {tone.choice}")
    print(f"  urgency : {urgency.score}")
    print("\nOK - the environment works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
