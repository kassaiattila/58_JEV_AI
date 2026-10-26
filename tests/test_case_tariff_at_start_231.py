"""231 (stage D, D-a; the reassessment after D0 of 2026-10-26, F05, P04, T04): every price list a case uses is the
version of its start, and one the pack cannot start without is there.

A case kept the price list version of its start where its pack named the list through a resource; a step naming the
list itself (`"catalogue": "<list>"` or `"newest_active"`) read whatever version was active when it ran. Now that is
kept too. A pack may say which of its resources a case cannot start without (`needs_at_start`): with none to keep (no
active version), the case is refused with what is missing, instead of reading another version later. The IT quote
needs none at start (its quote says when there is no price list). Invented requests and price lists; no paid call.
"""

from __future__ import annotations

import copy
import json

import pytest

from jav.app import process_packs, process_runtime, process_settings
from jav.core import cfg, store
from jav.core.process import cases
from jav.domains.quotes import invented_golden, price_lists
from tests import test_document_result_174 as rows
from tests.test_quote_path_231 import ACTOR, golden  # noqa: F401 - the fixture

PACK = "kept_quote"


def _pack(changes) -> dict:
    data = copy.deepcopy(cfg.load("process:it_quote"))
    data.update(id=PACK, intake=[{"on": "manual", "starts": "manual"}], partners=[], goldens=[])
    data["meta"] = {**data["meta"], "name": f"process:{PACK}", "version": "1.0.0"}
    changes(data)
    return data


def _use(monkeypatch, data: dict) -> None:
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data if name == f"process:{PACK}" else real(name))


def _start(case) -> str:
    return process_runtime.start_case(PACK, {"record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}},
                                      name=f"Kept {case.id}", actor=ACTOR)


def _params(case_id: str, step: str) -> dict:
    with store.connect() as c:
        return cases.definition_of(cases.find_case_in(c, case_id)).step(step).params


def test_a_step_naming_the_list_itself_keeps_its_version_too(golden, monkeypatch) -> None:  # noqa: F811
    cases_, _seen = golden
    listed = price_lists.chosen()

    def literal(data: dict) -> None:
        for step in data["steps"]:
            if step["id"] in ("match", "compose"):
                step["params"]["catalogue"] = listed.price_list if step["id"] == "match" else "newest_active"

    _use(monkeypatch, _pack(literal))
    case_id = _start(cases_[0])
    kept = f"{listed.price_list}@{listed.version}"
    assert _params(case_id, "match")["catalogue"] == _params(case_id, "compose")["catalogue"] == kept


def test_a_pack_names_only_its_own_resources_as_needed_at_start() -> None:
    data = _pack(lambda d: d.update(needs_at_start=["tariff"]))
    problems = process_packs._problems(process_packs.ProcessPack.model_validate(data))
    assert "needs_at_start names 'tariff', which is no resource of the pack" in problems, problems


@pytest.fixture()
def no_list(tmp_path):
    with store.use_store(tmp_path / "no-list.sqlite"):
        with store.connect() as c:
            c.execute("INSERT INTO workpackages(id, name, source_kind, created_at, updated_at) VALUES (?,?,?,?,?)",
                      (rows.WP, "invented quote requests", "manual", rows.NOW, rows.NOW))
        data = invented_golden.load()
        case = next(c for c in data.cases if c.expected.request is not None)
        from tests.test_quote_path_231 import _values

        rows._run("run-requests", {case.id: _values(case.expected.request)}, at=rows.NOW, doc_type="quote_request")
        yield case, tmp_path


def test_a_case_does_not_start_without_a_version_of_what_its_pack_needs(no_list, monkeypatch) -> None:
    case, tmp_path = no_list
    _use(monkeypatch, _pack(lambda d: d.update(needs_at_start=["price_list"])))
    with pytest.raises(process_settings.MissingAtStart, match="Price list"):
        _start(case)
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM process_cases").fetchone()[0] == 0  # nothing half made
    made = price_lists.add("Invented 2026", "p.xlsx", invented_golden.write_price_list(tmp_path / "p.xlsx").read_bytes(), actor=ACTOR)
    price_lists.activate(made["price_list"], 1, actor=ACTOR)
    case_id = _start(case)
    assert _params(case_id, "match")["catalogue"] == f"{made['price_list']}@1"


def test_the_it_quote_starts_without_a_price_list_and_its_quote_says_so(no_list) -> None:
    case, _tmp = no_list
    case_id = process_runtime.start_case("it_quote", {"record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}},
                                         name="No list yet", actor=ACTOR)
    assert _params(case_id, "match")["catalogue"] == "newest_active"
    view = json.loads(json.dumps(__import__("jav.domains.quotes.quote_package", fromlist=["view"]).view(case_id), default=str))
    assert "quote:no_price_list" in [b["code"] for b in view["blockers"]]
