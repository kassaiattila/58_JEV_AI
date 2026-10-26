"""231 (stage D, D-d2): a person's field check of the assessed units, frozen as the step's own version.

Two invented steps offer facts. The field check makes the units they name (a policyholder, its site, the site's asset
group, each by the offering step's key and its parent's), fills the facts still missing, and leaves a value that
differs from one already there to the person as a conflict; a unit whose parent is not there goes nowhere. Each claim
is placed once and traced. The person corrects a fact and freezes the units with the day cover starts: the checked
input becomes the step's version, the step is done with it, and a page showing an older state of the units is refused.
Reopened, the step waits for a new freeze. Invented data; no paid call.
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import assessed_units, capabilities, field_check, package_release, process_runtime, product_sets
from jav.core import cfg, decisions, store, trace
from jav.core.process import engine, kinds

PACK = "invented_field_check"
ANNA, BELA = "Minta Anna", "Minta Bela"
SRC = {"item": "invented-document", "page": 1}


def _claim(unit: str, level: str, fact: str, value, parent: str | None = None, reading: str = "invented_reading@1") -> dict:
    return {"unit": unit, "level": level, "parent": parent, "fact": fact, "value": value, "source": SRC, "reading": reading}


FIRST = [_claim("holder", "holder", "activity_code", "4719"), _claim("holder", "holder", "claims_5y_count", 1),
         _claim("site:1", "site", "country", "HU", parent="holder"),
         _claim("asset:1", "asset_group", "asset_group", "stock", parent="site:1"),
         _claim("asset:1", "asset_group", "sum_insured", {"amount": "12000000", "currency": "HUF"}, parent="site:1"),
         _claim("site:9", "site", "country", "AT", parent="nowhere")]
SECOND = [_claim("holder", "holder", "activity_code", "2562", reading="invented_register@1"),
          _claim("holder", "holder", "activity_code", "4719", reading="invented_other@1")]


class _Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[dict]


@pytest.fixture()
def case(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    capabilities.register(capabilities.Capability(
        name="invented_offer", version=1, module="tests.synthetic", kind="machine", summary="Invented.", params=_Offer,
        run=lambda ctx, p: kinds.Done({"claims": p.claims}), state="step", output=capabilities.Result))
    data = {"meta": {"name": f"process:{PACK}", "version": "1.0.0"}, "id": PACK, "title": "Invented field check",
            "intake": [{"on": "manual", "starts": "manual"}], "resources": {"product": "inv_business_property"},
            "needs_at_start": ["product"],
            "steps": [{"id": "read", "uses": "invented_offer@1", "params": {"claims": FIRST}},
                      {"id": "register", "uses": "invented_offer@1", "params": {"claims": SECOND}},
                      {"id": "check", "uses": "field_check@1", "params": {"catalogue": "property", "product": "@product"},
                       "after": ["read", "register"]}],
            "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]}}
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data if name == f"process:{PACK}" else real(name))
    with store.use_store(tmp_path / "field-check.sqlite"):
        product_sets.install(product_sets.load(), maker=ANNA, approver=BELA)
        case_id = process_runtime.start_case(PACK, {}, name="Invented field check", actor=ANNA)
        engine.turn(case_id)
        yield case_id


def _later(case_id: str, seconds: float = 10) -> None:
    engine.turn(case_id, now=time.time() + seconds)


def _by_level(view: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for u in view["units"]:
        out.setdefault(u["level"], []).append(u)
    return out


def test_the_offered_facts_make_the_units_fill_what_is_missing_and_leave_a_conflict_to_the_person(case) -> None:
    view = field_check.view(case, "check")
    levels = _by_level(view)
    [holder], [site], [asset] = levels["holder"], levels["site"], levels["asset_group"]
    assert holder["facts"] == {"activity_code": "4719", "claims_5y_count": 1}
    assert site["parent_id"] == holder["unit_id"] and asset["parent_id"] == site["unit_id"]
    assert asset["facts"] == {"asset_group": "stock", "sum_insured": {"amount": "12000000", "currency": "HUF"}}
    assert holder["sources"]["activity_code"]["interpretation"]["reading"] == "invented_reading@1"
    placed = {(c["from_step"], c["unit_key"], c["fact"], str(c["value"])): c["placement"] for c in view["claims"]}
    assert placed[("register", "holder", "activity_code", "2562")] == "conflict"
    assert placed[("register", "holder", "activity_code", "4719")] == "agrees"
    assert placed[("read", "site:9", "country", "AT")] == "unplaced"
    assert [c["open"] for c in view["claims"] if c["placement"] == "conflict"] == [True]
    _later(case)  # placed once: a later turn adds nothing
    assert len(field_check.view(case, "check")["claims"]) == len(view["claims"])
    rows = [r for r in trace.rows(case_id=case) if r["point"] == field_check.POINT]
    assert len(rows) == len(view["claims"]) and all(trace.replay(r) == r["outcome"] for r in rows)


def test_a_frozen_check_is_the_steps_version_and_a_stale_page_is_refused(case) -> None:
    view = field_check.view(case, "check")
    holder = _by_level(view)["holder"][0]
    assessed_units.save(case, "check", "property", holder["unit_id"], facts={**holder["facts"], "activity_code": "2562"},
                        actor=ANNA, expected_state=holder["state"], note="the register is right")
    assert not any(c["open"] for c in field_check.view(case, "check")["claims"])
    with pytest.raises(decisions.RevisionConflict):
        field_check.freeze(case, "check", cover_start="2027-01-01", expected_state=view["state"], actor=ANNA)
    frozen = field_check.freeze(case, "check", cover_start="2027-01-01", expected_state=field_check.view(case, "check")["state"],
                                actor=ANNA)
    _later(case)
    result = engine.state(case)["steps"]["check"]
    assert result["state"] == "done"
    assert (result["result"]["version"], result["result"]["product"], result["result"]["cover_start"]) == (
        frozen["version"], "inv_business_property@1", "2027-01-01")
    content = package_release.own_version(case, frozen["version"], step="check")["content"]
    assert [u["facts"].get("activity_code") for u in content["units"] if u["level"] == "holder"] == ["2562"]
    # a later correction does not change the frozen version
    holder = assessed_units.unit(case, "check", holder["unit_id"])
    assessed_units.save(case, "check", "property", holder["unit_id"], facts={**holder["facts"], "claims_5y_count": 3},
                        actor=ANNA, expected_state=holder["state"])
    assert package_release.own_version(case, frozen["version"], step="check")["content"] == content


def test_reopened_the_check_waits_for_a_new_freeze(case) -> None:
    field_check.freeze(case, "check", cover_start="2027-01-01", expected_state=None, actor=ANNA)
    _later(case)
    assert engine.state(case)["steps"]["check"]["state"] == "done"
    field_check.reopen(case, "check", note="a site is missing", actor=ANNA)
    _later(case, 20)
    assert engine.state(case)["steps"]["check"]["state"] != "done"
    again = field_check.freeze(case, "check", cover_start="2027-02-01", expected_state=None, actor=BELA)
    _later(case, 30)
    step = engine.state(case)["steps"]["check"]
    assert step["state"] == "done" and step["result"]["version"] == again["version"] and step["result"]["cover_start"] == "2027-02-01"


def test_nothing_to_freeze_is_refused(monkeypatch, case) -> None:
    for u in assessed_units.units(case, "check"):
        assessed_units.remove(case, "check", u["unit_id"], reason="invented", actor=ANNA, expected_state=u["state"])
    with pytest.raises(field_check.FieldCheckError, match="no unit to freeze"):
        field_check.freeze(case, "check", cover_start="2027-01-01", expected_state=None, actor=ANNA)
