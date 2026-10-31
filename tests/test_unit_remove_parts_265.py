"""265 (code review APPR-10): a unit with sub-units still in place is not removed.

Removing a holder left its sites in place without a parent; a later correction of a site was then refused with a
message about a missing parent. The removal is now refused while sub-units are in place; once they are removed, the
holder goes too. Invented units; no AI.
"""

from __future__ import annotations

import pytest

from jav.app import assessed_units
from tests.test_assessed_units_231 import ACTOR, CASE, STEP, _shop, db  # noqa: F401 (the fixture)


def _remove(unit_id: str) -> None:
    assessed_units.remove(CASE, STEP, unit_id, reason="sold", actor=ACTOR,
                          expected_state=assessed_units.unit(CASE, STEP, unit_id)["state"])


def test_a_holder_with_a_site_is_not_removed(db) -> None:  # noqa: F811
    holder, site = _shop()
    with pytest.raises(assessed_units.UnitHasParts, match="1 sub-unit"):
        _remove(holder)
    assert assessed_units.unit(CASE, STEP, holder)["removed"] is False
    _remove(site)
    _remove(holder)
    assert assessed_units.units(CASE, STEP) == []
