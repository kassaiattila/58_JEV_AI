"""231 (plan stage C, C0; DECISIONS 231): an existing work package taken over as a process pack's case.

The owner's decision of 2026-10-25: the live packages of the processes that move onto process packs are taken over as
cases under their own ids, so their decisions, versions and approvals stay where they are. The package becomes the
container's kind (its log and the case's data keep the kind it had), its scope is the pack's, and each step starts in
the state its capability reads from the work the package already holds; a step whose capability cannot read one has
not run. Taking a package over twice changes nothing. Invented quote requests, a stand-in model; no paid call.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from jav.app import capabilities, process_runtime, work
from jav.core import store
from jav.core.process import cases, engine
from tests import test_document_result_174 as rows
from tests.test_quote_path_231 import golden  # noqa: F401 - the fixture

PACK = "it_quote"


def _old_package() -> str:
    return work.create_workpackage(name="An earlier quote", source_kind="manual", source_ref="folder:invented",
                                   owner="Minta Anna")["id"]


def _scope(case) -> dict:
    return {"record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}}


def test_a_package_is_taken_over_as_a_case_under_its_own_id(golden) -> None:  # noqa: F811
    cases_, _seen = golden
    wp_id = _old_package()
    assert process_runtime.adopt_case(PACK, wp_id, _scope(cases_[0]), actor="Kovacs Bela") == "adopted"
    wp = work.get(wp_id)
    assert (wp["source_kind"], wp["source_ref"]) == (process_runtime.CONTAINER, f"pack:{PACK}@1.5.0")
    with store.connect() as c:
        case = cases.find_case_in(c, wp_id)
    assert case["data"]["adopted_from"] == {"source_kind": "manual", "source_ref": "folder:invented"}
    assert case["data"]["scope"]["record"]["workpackage_id"] == rows.WP
    assert process_runtime.pack_of(wp_id) == (PACK, "1.5.0")
    with store.connect() as c:
        logged = [json.loads(r["detail"]) for r in c.execute(
            "SELECT detail FROM workpackage_events WHERE workpackage_id=? AND action='retyped'", (wp_id,))]
    assert logged == [{"from": {"source_kind": "manual", "source_ref": "folder:invented"},
                       "to": {"source_kind": process_runtime.CONTAINER, "source_ref": f"pack:{PACK}@1.5.0"}}]
    assert process_runtime.adopt_case(PACK, wp_id, _scope(cases_[0]), actor="Kovacs Bela") == "exists"
    assert work.get(wp_id)["revision"] == wp["revision"]  # a second take-over changes nothing
    engine.turn(wp_id, wake=True)
    assert engine.state(wp_id)["steps"]["request"]["state"] == "done"  # no step had run: the case runs from its start


def test_a_step_starts_in_the_state_its_capability_reads_from_the_package(golden, monkeypatch) -> None:  # noqa: F811
    cases_, _seen = golden
    wp_id = _old_package()
    seen = []

    def read(wp: str, params: dict) -> cases.Adopted:
        seen.append((wp, params["record_type"]))
        return cases.Adopted(cases.DONE, result={"taken_over": True})

    cap = capabilities.of("record_assembly@1")
    monkeypatch.setitem(capabilities._CAPS, cap.key, dataclasses.replace(cap, adopt=read))
    process_runtime.adopt_case(PACK, wp_id, _scope(cases_[0]), actor="Kovacs Bela")
    assert seen == [(wp_id, "quote_request")]
    state = engine.state(wp_id)["steps"]
    assert state["request"]["state"] == "done" and state["compose"]["state"] != "done"


def test_a_package_that_is_not_there_or_a_scope_that_does_not_fit_is_refused(golden) -> None:  # noqa: F811
    with pytest.raises(KeyError):
        process_runtime.adopt_case(PACK, "wp-000000000000", {"record": {"workpackage_id": rows.WP, "item_id": "x"}},
                                   actor="Kovacs Bela")
    wp_id = _old_package()
    with pytest.raises(ValueError):
        process_runtime.adopt_case(PACK, wp_id, {}, actor="Kovacs Bela")
    assert work.get(wp_id)["source_kind"] == "manual"  # nothing changed
