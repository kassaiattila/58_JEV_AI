"""231 (stage U, U3c; the owner's decision of 2026-10-28: the tariff is part of the product): a process's tariff follows
from its product.

The insurance processes name their tariff as following from their product (`derived`): the settings page shows it read
only, as the product brings it; a process cannot set its own tariff; a case keeps, at its start, the active version of
the tariff its product names (not a tariff of its own); and a product whose tariff has no active version says so before a
case starts. A pack deriving a resource from one it does not hold is refused. The invented insurer's product set, an
empty store; nothing runs.
"""

from __future__ import annotations

import copy
import json
import shutil

import pytest

from jav.app import process_packs, process_settings, product_rules, product_sets, registrations
from jav.core import cfg, store
from jav.core.config import PROJECT_ROOT

registrations.load_all()
PACK = "insurance_offer"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "tariff.sqlite"):
        product_sets.install(product_sets.load(), maker="Minta Anna", approver="Minta Bela")
        yield tmp_path


def _resource(view: dict, key: str) -> dict:
    return next(r for r in view["resources"] if r["key"] == key)


def _brought(pack: process_packs.ProcessPack) -> str:
    return str(product_rules.product_at(product_rules.kept(pack.resources["product"])).product.tariff)


def test_the_tariff_is_the_product_s_and_shown_read_only(db) -> None:
    pack = process_packs.load(PACK)
    assert pack.derived == {"tariff": "product"}
    tariff = _resource(process_settings.view(PACK), "tariff")
    assert tariff["derived_from"] == "product" and tariff["value"] == _brought(pack) and tariff["options"] is None


def test_a_process_cannot_set_its_own_tariff(db) -> None:
    with pytest.raises(process_settings.SettingError, match="follows"):
        process_settings.propose(PACK, "tariff", _brought(process_packs.load(PACK)), "Minta Anna")


def test_a_case_keeps_the_active_version_of_its_product_s_tariff(db) -> None:
    pack = process_packs.load(PACK)
    kept = process_settings.at_start(pack).resources
    assert kept["tariff"] == product_rules.kept(_brought(pack), "tariff") and "@" in kept["tariff"]


def test_a_product_whose_tariff_has_no_active_version_says_so_before_a_case_starts(db) -> None:
    pack = process_packs.load(PACK)
    product_rules.retire("tariff", _brought(pack), actor="Minta Bela")
    assert [m["key"] for m in process_settings.missing_at_start(pack)] == ["tariff"]


def test_a_pack_deriving_from_a_resource_it_does_not_hold_is_refused(tmp_path, monkeypatch) -> None:
    configs = tmp_path / "configs"
    shutil.copytree(PROJECT_ROOT / "configs", configs)
    data = copy.deepcopy(json.loads((configs / "processes" / f"{PACK}.json").read_text(encoding="utf-8")))
    data["derived"] = {"tariff": "nowhere"}
    (configs / "processes" / f"{PACK}.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(cfg, "CONFIG_DIR", configs)
    monkeypatch.setattr(cfg, "CALLSITE_DIR", configs / "callsites")
    monkeypatch.setattr(cfg, "TYPES_DIR", configs / "types")
    monkeypatch.setattr(cfg, "PROCESSES_DIR", configs / "processes")
    cfg.reload()
    try:
        with pytest.raises(process_packs.PackError, match="derived"):
            process_packs.load(PACK)
    finally:
        cfg.reload()
