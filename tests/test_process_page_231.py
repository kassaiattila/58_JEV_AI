"""231 (stage U, U3a; the owner's decision of 2026-10-28: each process its own settings page): a process's settings page
describes the process too.

The page's Description tab reads what the process is for, its steps in order (each with what its capability does,
whether a person starts it, what it waits for, whether it may be left out), its outputs, the golden sets that measure
it, what may start one of its cases, and whether it has example material; the service gives them with the page's
values. Real process packs, an empty store; nothing runs.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import capabilities, process_packs, process_settings, registrations
from jav.core import cfg, store
from jav.service.api import create_app

registrations.load_all()


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "page.sqlite"):
        yield tmp_path


def test_the_page_describes_the_process(db) -> None:
    pack = process_packs.load("it_quote")
    page = process_settings.view("it_quote")
    about = page["description"]
    assert about["summary"] == pack.summary
    assert [s["id"] for s in about["steps"]] == [s.id for s in pack.steps]
    match = next(s for s in about["steps"] if s["id"] == "match")
    assert match["start"] == "person" and match["summary"] == capabilities.of("catalogue_match@1").summary
    compose = next(s for s in about["steps"] if s["id"] == "compose")
    assert set(compose["after"]) == {"Proposal", "Request"} and compose["optional"] is False  # its gate and its order
    quote = cfg.load("outputs")["outputs"]["quote"]
    assert about["outputs"] == [{"id": "quote", "what": quote["what"], "format": quote["format"]}]
    assert about["goldens"] == list(pack.goldens) and about["examples"] is True
    assert {"on": "email_intent", "starts": "case", "intent": "quote_request"} in about["intake"]
    assert {"on": "manual", "starts": "manual", "intent": None} in about["intake"]


def test_an_optional_step_and_a_process_without_examples_are_said(db) -> None:
    about = process_settings.view("reconciliation")["description"]
    propose = next(s for s in about["steps"] if s["id"] == "propose")
    assert propose["optional"] is True and propose["start"] == "person"
    assert process_settings.view("mail_routing")["description"]["examples"] is True
    assert process_settings.view("monthly_reconciliation")["description"]["outputs"] == []


def test_the_service_gives_the_description_with_the_page(db) -> None:
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        page = c.get("/api/processes/documents/settings").json()
    assert page["description"]["summary"] and page["description"]["steps"][0]["id"] == "process"
