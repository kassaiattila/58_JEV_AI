"""231 (plan stage C, C2b): the reconciliation engine's whole answer on the golden cases, pinned.

The golden check (`reconcile --golden`) compares the fields each case names; this fingerprint covers everything
`propose` returns for every case (its rules' fingerprint left out, as a rule file's wording changes it without changing a
pair), so moving the engine's code between modules is proven to change no answer. A change meant to change the engine's
answer updates the pinned value in the same commit, beside its engine version.
"""

from __future__ import annotations

import hashlib
import json

from jav.domains.finance import reconcile

CASES = 100
FINGERPRINT = "5c79736fdc7aa9adb91029e3fa09ddfd1b914b3f52023a3bd28e8cb067e4a937"


def fingerprint() -> tuple[int, str]:
    answers = []
    for case in reconcile.golden_cases():
        answer = reconcile.propose(case["snapshot"])
        answer.pop("config_hash")
        answers.append([case["id"], answer])
    text = json.dumps(answers, sort_keys=True, ensure_ascii=False, default=str)
    return len(answers), hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_engine_answers_every_golden_case_as_before():
    assert fingerprint() == (CASES, FINGERPRINT), (
        "the reconciliation engine answers a golden case otherwise: if that is meant, bump ENGINE_VERSION and pin the new"
        " value; `python -m jav.cli reconcile --golden` shows the named fields that differ")
