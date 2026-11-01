"""265 (code review APPR-03, APPR-04): the evaluation stops a premium when the cover modules or the conditions do not fit.

- APPR-03: a module's "requires" and "excludes" were checked only against the product's own modules, never against
  the modules a case asks for: an extension without its base was priced and printed. Now each is a blocker.
- APPR-04: the condition documents' validity was never compared with the day cover starts, and a document could end
  before it began. Now a document not in force on that day is a blocker, and its validity must be in order.
Invented data (the invented product set of `test_evaluation_steps_231`); no paid call.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from jav.app import capabilities, evaluation_steps, product_rules, product_sets
from jav.core import cfg, store
from jav.core.process import engine, kinds
from tests.test_evaluation_steps_231 import ANNA, CASES, SET, _claims, _frozen_case, _Offer, _pack


def _asking(modules: list[str]) -> list[dict]:
    return [{**c, "value": modules} if c["fact"] == "requested_modules" else c for c in _claims(CASES["reference"])]


@pytest.fixture()
def packs(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    capabilities.register(capabilities.Capability(
        name="invented_offer", version=1, module="tests.synthetic", kind="machine", summary="Invented.", params=_Offer,
        run=lambda ctx, p: kinds.Done({"claims": p.claims}), state="step", output=capabilities.Result))
    data = {"process:invented_alone": _pack("invented_alone", _asking(["burglary"])),
            "process:invented_reference": _pack("invented_reference", _claims(CASES["reference"]))}
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data[name] if name in data else real(name))
    with store.use_store(tmp_path / "conditions.sqlite"):
        product_sets.install(SET, maker=ANNA, approver="Minta Bela")
        yield


def _blockers(case_id: str) -> list[str]:
    return list(evaluation_steps.record(case_id, "evaluate", 1)["content"]["blockers"])


def test_an_extension_asked_for_without_its_base_is_a_blocker(packs) -> None:
    case_id = _frozen_case("invented_alone", CASES["reference"].input["cover_start"])
    assert "the module burglary requires property, which is not asked for" in _blockers(case_id)
    steps = engine.state(case_id)["steps"]
    assert steps["rate"]["state"] == "failed" and "requires property" in steps["rate"]["note"]


def test_a_condition_document_not_in_force_on_the_cover_start_is_a_blocker(packs) -> None:
    case_id = _frozen_case("invented_reference", "2001-01-01")
    found = [b for b in _blockers(case_id) if "is not in force on 2001-01-01" in b]
    assert found and all(b.startswith("the condition document ") for b in found)


def test_the_reference_case_has_no_condition_blocker(packs) -> None:
    case_id = _frozen_case("invented_reference", CASES["reference"].input["cover_start"])
    assert not [b for b in _blockers(case_id) if "condition document" in b or "asked for" in b]


def test_a_condition_document_ends_on_or_after_its_start() -> None:
    with pytest.raises(ValidationError, match="ends on or after"):
        product_rules.ConditionDocument(kind="general", title="x", valid_from=date(2026, 2, 1), valid_to=date(2026, 1, 1))


def test_a_module_that_excludes_another_asked_for_is_a_blocker() -> None:
    """272 (K3): the "excludes" side of APPR-03 had no test of its own (only "requires" ran through a case)."""
    from types import SimpleNamespace

    from jav.app import evaluation_steps

    product = SimpleNamespace(modules=[SimpleNamespace(code="flat_rate", requires=(), excludes=("itemised",)),
                                       SimpleNamespace(code="itemised", requires=(), excludes=())])
    assert [str(s) for s in evaluation_steps._module_blockers(product, ("flat_rate", "itemised"))] == [
        "the module flat_rate excludes itemised, which is asked for too"]
    assert evaluation_steps._module_blockers(product, ("flat_rate",)) == []
