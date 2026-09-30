"""Füstteszt: a venv, a kulcs és a TypeSafe API élő hívása egyben.

Futtatás:  .venv/Scripts/python.exe smoke_test.py
"""

from __future__ import annotations

import sys

from typesafe_sdk import Choice, Noul, Score, TypeSafeAuthenticationError, TypeSafeError

from jav.config import ENV_FILE, MissingAPIKeyError, get_api_key, make_client


def main() -> int:
    print(f"Python : {sys.version.split()[0]}  ({sys.executable})")
    print(f".env   : {ENV_FILE}  ({'megvan' if ENV_FILE.exists() else 'HIÁNYZIK'})")

    try:
        key = get_api_key()
    except MissingAPIKeyError as exc:
        print(f"\n[HIBA] {exc}")
        return 1
    print(f"Kulcs  : {key[:6]}…{key[-4:]}  ({len(key)} karakter)")

    print("\nÉlő System One hívás…")
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
        print(f"[HIBA] A kulcsot elutasította az API: {exc}")
        return 1
    except TypeSafeError as exc:
        print(f"[HIBA] TypeSafe hívás sikertelen: {type(exc).__name__}: {exc}")
        return 1

    billing = response.nouls["billing"]
    tone = response.choices["tone"]
    urgency = response.scores["urgency"]

    print(f"  billing : {billing.noul}")
    print(f"  tone    : {tone.choice}")
    print(f"  urgency : {urgency.score}")
    print("\nOK - a környezet működik.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
