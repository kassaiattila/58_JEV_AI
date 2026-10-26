"""231 (stage D, D-c4; the reassessment after D0 of 2026-10-26, P04): a case keeps the product and tariff versions of
its start, and a pack cannot need a resource no step keeps.

A step naming a product and a tariff through the pack's resources keeps the versions active when the case starts
(`<product>@<n>`, `<tariff>@<n>`): a newer version reaches only the cases started after it. A pack that needs them at
the start (`needs_at_start`) does not start a case while one has no active version. And a pack naming a resource as
needed at the start that no step keeps (a plain value, which has no version) is refused: it would pass silently.
Invented products, tariffs and a stand-in capability; no paid call.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import capabilities, process_packs, process_runtime, process_settings, product_rules
from jav.core import cfg, store
from jav.core.process import cases, kinds
from tests.test_product_rules_231 import ANNA, BELA, _product, _setup
from tests.test_rating_231 import TARIFF

PACK = "invented_assessment"


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product: str
    tariff: str


@pytest.fixture()
def registered(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    capabilities.register(capabilities.Capability(
        name="invented_assessment", version=1, module="tests.synthetic", kind="machine", summary="Invented.", params=_Params,
        run=lambda ctx, p: kinds.DONE, state="step", output=capabilities.Result,
        at_start={"product": product_rules.keeper("product"), "tariff": product_rules.keeper("tariff")}))
    data = {"meta": {"name": f"process:{PACK}", "version": "1.0.0"}, "id": PACK, "title": "Invented assessment",
            "intake": [{"on": "manual", "starts": "manual"}],
            "resources": {"product": "invented_property", "tariff": "invented_tariff", "note": "plain"},
            "needs_at_start": ["product", "tariff"],
            "steps": [{"id": "assess", "uses": "invented_assessment@1", "params": {"product": "@product", "tariff": "@tariff"}}],
            "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]}}
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data if name == f"process:{PACK}" else real(name))
    with store.use_store(tmp_path / "at-start.sqlite"):
        yield data


def _start() -> str:
    return process_runtime.start_case(PACK, {}, name="Invented assessment", actor=ANNA)


def _params(case_id: str) -> dict:
    with store.connect() as c:
        params = cases.definition_of(cases.find_case_in(c, case_id)).step("assess").params
    return {key: params[key] for key in ("product", "tariff")}


def _versions() -> None:
    _setup()
    product_rules.add("tariff", "invented_tariff", TARIFF.model_dump(mode="json"), actor=ANNA)
    product_rules.activate("tariff", "invented_tariff", 1, actor=BELA)
    product_rules.add("product", "invented_property", _product(tariff="invented_tariff"), actor=ANNA)
    product_rules.activate("product", "invented_property", 1, actor=BELA)


def test_a_case_keeps_the_product_and_tariff_of_its_start(registered) -> None:
    _versions()
    old = _start()
    product_rules.add("tariff", "invented_tariff", TARIFF.model_dump(mode="json") | {"total_factors": []}, actor=ANNA)
    product_rules.activate("tariff", "invented_tariff", 2, actor=BELA)
    product_rules.add("product", "invented_property", _product(tariff="invented_tariff", name="Invented property 2"), actor=ANNA)
    product_rules.activate("product", "invented_property", 2, actor=BELA)
    new = _start()
    assert _params(old) == {"product": "invented_property@1", "tariff": "invented_tariff@1"}
    assert _params(new) == {"product": "invented_property@2", "tariff": "invented_tariff@2"}


def test_a_case_does_not_start_without_an_active_tariff(registered) -> None:
    _setup()
    product_rules.add("product", "invented_property", _product(), actor=ANNA)
    product_rules.activate("product", "invented_property", 1, actor=BELA)
    with pytest.raises(process_settings.MissingAtStart):
        _start()


def test_a_pack_cannot_need_a_resource_no_step_keeps(registered) -> None:
    data = copy.deepcopy(registered) | {"needs_at_start": ["product", "note"]}
    problems = process_packs._problems(process_packs.ProcessPack.model_validate(data))
    assert "needs_at_start names 'note', which no step keeps at a version" in problems, problems
