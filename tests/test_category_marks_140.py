"""140 (backlog F-category-signal; DECISIONS 140): a statement line's own category suggests a needs-no-invoice reason.

The Revolut export names a category for every line; an exchange between the own currency accounts ("Átváltás"), a
top-up from an own account ("Feltöltés") and a cash withdrawal ("ATM") need no invoice. The rules are data
(`configs/reconcile.json` `category_marks`, patterns on the accent-free description) and only suggest: a person still
saves the mark. Synthetic lines only; no AI call.
"""

from __future__ import annotations

import pytest

from jav import cfg
from jav.domains.finance import reconcile, reconcile_package as rp
from tests import test_reconcile_package_131 as p131

db = p131.db


@pytest.mark.parametrize(("description", "mark"), [
    ("Átváltás", "own_transfer"), ("ATVALTAS", "own_transfer"), ("Feltöltés", "own_transfer"), ("ATM", "cash"),
    ("Egyéb", None), ("Kereskedő", None), ("Kártya Használat", None), ("ATM díj visszatérítés", None), (None, None), ("", None),
])
def test_the_category_suggests_a_reason_only_for_its_own_words(description, mark):
    assert reconcile.category_mark({"description": description}) == mark


def test_every_rule_names_a_known_reason():
    conf = cfg.load("reconcile")
    assert {r["mark"] for r in conf["category_marks"]} <= set(conf["line_marks"])


def test_the_pairing_page_gets_the_categorys_reason_with_each_line(db):
    atm, shop = p131._line(amount="20000.00", memo="", description="ATM"), p131._line(amount="1500.00", memo="", description="Kereskedő")
    p131._stmt("revolut", atm, shop)
    ws = rp.workspace(p131._package())
    marks = {ln["description"]: ln["category_mark"] for ln in ws["lines"]}
    assert marks == {"ATM": "cash", "Kereskedő": None}
    assert all(ln["mark"] is None for ln in ws["lines"])  # a suggestion only: nothing is marked by itself
