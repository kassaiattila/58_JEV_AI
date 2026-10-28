"""231 (stage U, U3d; the owner's decisions of 2026-10-28: every shared element says which processes use it): the
processes that use a product, a tariff, a letter frame, an output template or a partner role.

Each process pack's resources name shared things through the capability parameters they set (a product, a tariff, a
price list, a letter frame), as its file or the process's own active value has them; a derived tariff counts as its
product brings it, and a partner role by the pack's partner links. The service lists them by kind. The invented
insurer's product set, an empty store; nothing runs.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import process_packs, process_settings, product_rules, product_sets, registrations
from jav.core import store
from jav.service.api import create_app

registrations.load_all()


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "used.sqlite"):
        product_sets.install(product_sets.load(), maker="Minta Anna", approver="Minta Bela")
        yield tmp_path


def _ids(entries: list[dict]) -> set[str]:
    return {e["id"] for e in entries}


def test_a_product_and_its_tariff_name_the_processes_that_use_them(db) -> None:
    product = process_packs.load("insurance_offer").resources["product"]
    tariff = product_rules.product_tariff(product)
    used = process_settings.used_by("product")
    assert {"insurance_offer", "insurance_renewal"} <= _ids(used[product])
    assert {"insurance_offer", "insurance_renewal"} <= _ids(process_settings.used_by("tariff")[str(tariff)])
    assert "allianz_property_offer" in _ids(used[process_packs.load("allianz_property_offer").resources["product"]])
    assert all(set(e) == {"id", "title"} for entries in used.values() for e in entries)


def test_letter_frames_templates_and_partner_roles_name_their_processes(db) -> None:
    frames = process_settings.used_by("letter_frame")
    assert {"insurance_offer", "allianz_property_offer"} <= _ids(frames["offer_letter"])
    assert _ids(frames["renewal_letter"]) == {"insurance_renewal"}
    assert "it_quote" in _ids(process_settings.used_by("quote_letter_frame")["letter"])
    assert "it_quote" in _ids(process_settings.used_by("partner_role")["customer"])
    assert {"it_quote", "insurance_offer"} <= _ids(process_settings.used_by("output_template")["builtin"])


def test_the_service_lists_them_by_kind(db) -> None:
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        answer = c.get("/api/library/used-by/letter_frame")
        assert answer.status_code == 200 and "offer_letter" in answer.json()["used_by"]
        assert c.get("/api/library/used-by/Not-A-Kind").status_code == 422
