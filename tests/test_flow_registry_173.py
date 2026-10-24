"""The flow registry (173, plan 170 E1): one place says which flows exist, under the names stored in every run.

Guarantees tested: every flow a recipe can route an item to is registered, a composite's stages are flows the worker
can build, and the stored names are exactly today's; the contract lint takes its targets from the registry in the
order the preflight has always reported them; an unknown name is a named error; the run plan's native branches read
the registry.
"""

from __future__ import annotations

import pytest

from jav.devtools import admin
from jav.app import work_readiness, work_recipes
from jav.runtime import worker
from jav import flows

STORED_NAMES = ("invoice", "doc_detect", "email", "native", "statement_table")  # in the frozen recipes of every run


def _routed(recipe: dict) -> set[str]:
    kinds = {k: {"kind": k, "source_path": f"C:/synthetic/item{suffix}"}
             for k, suffix in (("document", ".pdf"), ("email", ".json"), ("statement_table", ".csv"))}
    names = {recipe["flow"], *(recipe.get("flows") or {}).values(), *(recipe.get("flows_by_suffix") or {}).values()}
    return names | {work_readiness.flow_for(recipe, item) for item in kinds.values()}


def test_every_flow_a_recipe_routes_to_is_registered_under_its_stored_name() -> None:
    for recipe in work_recipes.recipes():
        for name in _routed(recipe):
            spec = flows.get(name)
            for stage in spec.stages or (name,):
                assert flows.get(stage).build is not None, f"{recipe['id']}: {name} -> {stage} cannot be built"
    runnable = {s.name for s in flows.specs() if s.build is not None}
    assert runnable == set(STORED_NAMES)
    assert flows.get("document").stages == ("doc_detect", "invoice")


def test_the_worker_loads_each_module_from_the_registry() -> None:
    for name in STORED_NAMES:
        assert worker._flow_module(name).__name__ == flows.get(name).module


def test_the_contract_lint_takes_every_flow_in_the_registry_order() -> None:
    """229 (MD1): the shared flows first, then each domain's (the finance domain's bank table, the email domain's
    intent), as their domains register them."""
    assert [module.CONTRACT["name"] for module, _app in admin.flow_lint_targets()] == [
        "invoice", "doc_detect", "native", "statement_table", "email_intent"]


def test_an_unknown_flow_name_is_a_named_error() -> None:
    with pytest.raises(flows.UnknownFlow, match="no_such_flow"):
        flows.get("no_such_flow")


def test_only_the_native_flow_takes_its_budget_and_path_from_the_reader() -> None:
    assert [s.name for s in flows.specs() if s.native] == ["native"]
    recipe = next(r for r in work_recipes.recipes() if r.get("flows_by_suffix"))
    office = {"item_id": "a" * 64, "kind": "document", "source_path": "C:/synthetic/a.docx", "sha256": "a" * 64}
    plan = work_readiness.run_plan(recipe, {"arm": "S"}, [office], arms=["S"])
    assert plan["native_documents"] == 1 and plan["azure"] is False
