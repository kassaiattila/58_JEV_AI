"""231 (stage D, D-b4; the reassessment after D0 of 2026-10-26, P06, P10): the units a case's step assesses.

A step keeps its assessed units (a policyholder, its sites, their asset groups) with durable ids: a correction keeps
the id, and every change is a row of the decision journal, so the earlier value and its source stay visible. A change
made on an older state is refused (the page reloads), a removed unit stays visible and takes no correction, and a fact
that does not fit the catalogue writes nothing. The units list page by page from the store (a case's summary carries
a reference to the list, never its rows), and the checked input frozen from them does not change with a later
correction. Invented data; no paid call.
"""

from __future__ import annotations

import pytest

from jav.app import assessed_units, datasets, facts
from jav.app.tablequery import Query
from jav.core import decisions, store
from jav.core.measures import Quantity

CASE, STEP, ACTOR = "wp-00000000d0b4", "units", "Synthetic reviewer"


@pytest.fixture()
def db(tmp_path):
    with store.use_store(tmp_path / "units.sqlite"):
        yield


def _claim(original: str, page: int = 1) -> dict:
    return {"value": original, "original": original, "source": {"item": "it-1", "file": "request.pdf", "page": page},
            "interpretation": {"reading": "type:property_request@1.0.0"}}


def _shop() -> tuple[str, str]:
    holder = assessed_units.add(CASE, STEP, "property", level="holder", parent_id=None,
                                facts={"activity_code": "4719"}, actor=ACTOR)
    site = assessed_units.add(CASE, STEP, "property", level="site", parent_id=holder,
                              facts={"country": "HU", "floor_area": {"value": "420", "unit": "m2"}},
                              sources={"floor_area": _claim("420 m2")}, actor=ACTOR)
    return holder, site


def test_a_correction_keeps_the_unit_and_its_history(db) -> None:
    holder, site = _shop()
    assert holder.startswith("u-") and len(holder) == 12
    unit = assessed_units.unit(CASE, STEP, site)
    assessed_units.save(CASE, STEP, "property", site, facts={**unit["facts"], "floor_area": {"value": "410", "unit": "m2"}},
                        sources={"floor_area": _claim("41O m2", page=2)}, actor=ACTOR, expected_state=unit["state"],
                        note="read again from page 2")
    now = assessed_units.unit(CASE, STEP, site)
    assert now["unit_id"] == site and now["facts"]["floor_area"] == {"value": "410", "unit": "m2"}
    history = assessed_units.history(CASE, STEP, site)
    assert [h["value"]["facts"]["floor_area"]["value"] for h in history] == ["420", "410"]
    assert history[0]["value"]["sources"]["floor_area"]["original"] == "420 m2" and history[1]["note"] == "read again from page 2"


def test_a_change_on_an_older_state_is_refused(db) -> None:
    _holder, site = _shop()
    old = assessed_units.unit(CASE, STEP, site)["state"]
    assessed_units.save(CASE, STEP, "property", site, facts={"country": "HU"}, actor=ACTOR, expected_state=old)
    with pytest.raises(decisions.RevisionConflict):
        assessed_units.save(CASE, STEP, "property", site, facts={"country": "AT"}, actor=ACTOR, expected_state=old)


def test_a_fact_that_does_not_fit_writes_nothing(db) -> None:
    holder, _site = _shop()
    before = len(assessed_units.units(CASE, STEP))
    with pytest.raises(facts.FactError, match="floor_area is in m2, not m3"):
        assessed_units.add(CASE, STEP, "property", level="site", parent_id=holder,
                           facts={"floor_area": {"value": "1", "unit": "m3"}}, actor=ACTOR)
    assert len(assessed_units.units(CASE, STEP)) == before


def test_a_removed_unit_stays_visible_and_takes_no_correction(db) -> None:
    _holder, site = _shop()
    state = assessed_units.unit(CASE, STEP, site)["state"]
    assessed_units.remove(CASE, STEP, site, reason="the site was sold", actor=ACTOR, expected_state=state)
    assert site not in {u["unit_id"] for u in assessed_units.units(CASE, STEP)}
    shown = {u["unit_id"]: u for u in assessed_units.units(CASE, STEP, include_removed=True)}
    assert shown[site]["removed"] is True
    with pytest.raises(assessed_units.UnitRemoved):
        assessed_units.save(CASE, STEP, "property", site, facts={"country": "HU"}, actor=ACTOR,
                            expected_state=assessed_units.unit(CASE, STEP, site)["state"])


def test_the_units_list_page_by_page_and_a_summary_carries_a_reference(db) -> None:
    holder, site = _shop()
    for n in range(28):
        assessed_units.add(CASE, STEP, "property", level="asset_group", parent_id=site,
                           facts={"asset_group": "equipment", "sum_insured": {"amount": str(1000 * (n + 1)), "currency": "HUF"}},
                           actor=ACTOR)
    scope = {"case_id": CASE, "step_id": STEP}
    page = datasets.query("assessed_units", scope, Query(offset=20, limit=20))
    assert page["total"] == 30 and len(page["rows"]) == 10
    ref = assessed_units.reference(CASE, STEP)
    assert ref.dataset == "assessed_units" and ref.scope == scope and ref.version == str(assessed_units.state(CASE, STEP))


def test_a_frozen_checked_input_does_not_follow_a_later_correction(db) -> None:
    _holder, site = _shop()
    frozen = assessed_units.checked_input(CASE, STEP, "property", product="invented_property@1", cover_start="2026-12-01")
    dumped = frozen.model_dump(mode="json")
    unit = assessed_units.unit(CASE, STEP, site)
    assessed_units.save(CASE, STEP, "property", site, facts={**unit["facts"], "floor_area": {"value": "999", "unit": "m2"}},
                        actor=ACTOR, expected_state=unit["state"])
    assert frozen.model_dump(mode="json") == dumped
    site_unit = next(u for u in frozen.units if u.unit_id == site)
    assert site_unit.facts["floor_area"] == Quantity(value="420", unit="m2")
