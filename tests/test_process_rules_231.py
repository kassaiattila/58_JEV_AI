"""231 (plan stage B, B3; DECISIONS 231): a process's own values of the rule keys its capabilities let it set.

A capability names the keys of its rule files a process may set (`RuleKey`: a whole number within bounds, or one of
some options); a key the capability's rule files do not hold, or whose file value does not fit, is refused when it
registers. A process saves a value as a draft, checked by that declaration, and makes it active by the rule of who may.
A case keeps the values active when it started: its steps, its jobs in the worker and the service's requests about it
read the rule files with them in place, and a case started before reads the files. A decision traced meanwhile records
them beside the file it read, and replays with them. Invented quote requests and price lists, a stand-in model; no paid
call.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from jav.app import capabilities, process_runtime, process_settings
from jav.core import cfg, queue, store, trace
from jav.core.process import kinds
from jav.domains.quotes import quote_draft
from jav.runtime import job_kinds, worker
from jav.service.api import create_app
from tests import test_document_result_174 as rows
from tests.test_quote_case_231 import _drive, out  # noqa: F401 - the fixture
from tests.test_quote_path_231 import golden  # noqa: F401 - the fixture

PACK = "it_quote"
MAX_LINES = "quotes.draft.max_lines"


class _Nothing(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _cap(*rule_keys: capabilities.RuleKey) -> capabilities.Capability:
    return capabilities.Capability(name="invented_rules", version=1, module=__name__, kind="machine", params=_Nothing,
                                   summary="An invented capability.", rule_files=("quotes",), rule_keys=rule_keys)


def _start(case) -> str:
    return process_runtime.start_case(PACK, {"record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}},
                                      name=f"Quote {case.id}", actor="anna")


def _rule(view: dict, key: str) -> dict:
    return next(r for r in view["rules"] if r["key"] == key)


def _max_lines() -> int:
    return int(cfg.load("quotes")["draft"]["max_lines"])


def _lines_at_most(n: int) -> None:
    process_settings.propose(PACK, MAX_LINES, n, "anna", kind=process_settings.RULE, note="short quotes")
    process_settings.activate(PACK, MAX_LINES, 1, "anna", kind=process_settings.RULE)


def test_a_capability_names_only_keys_its_rule_files_hold_with_values_that_fit() -> None:
    good = capabilities.RuleKey("quotes", "draft.max_lines", "int", "Lines", least=1, most=1000)
    capabilities._check(_cap(good))
    for bad in (replace(good, file="price_lists"), replace(good, key="draft.no_such_key"), replace(good, most=10),
                replace(good, kind="choice"), capabilities.RuleKey("quotes", "draft.max_lines", "choice", "Lines", options=("5",))):
        with pytest.raises(capabilities.CapabilityError):
            capabilities._check(_cap(bad))
    with pytest.raises(capabilities.CapabilityError):
        capabilities._check(_cap(good, good))


def test_a_rule_value_is_checked_by_its_declaration_and_shown_with_the_files(golden) -> None:  # noqa: F811
    shown = _rule(process_settings.view(PACK), MAX_LINES)
    assert (shown["file_value"], shown["value"], shown["own"], shown["steps"]) == (300, 300, False, ["Quote"])
    assert {r["key"] for r in process_settings.view(PACK)["rules"]} == {
        "quotes.proposal.max_items", MAX_LINES, "price_lists.rounding.HUF", "price_lists.rounding.default",
        "quotes.letter.max_chars"}
    for key, value in ((MAX_LINES, 0), (MAX_LINES, "12"), (MAX_LINES, True), ("quotes.proposal.max_items", 500),
                       ("price_lists.rounding.HUF", "10"), ("quotes.proposal.max_item_usd.openai", "1")):
        with pytest.raises(process_settings.SettingError):
            process_settings.propose(PACK, key, value, "anna", kind=process_settings.RULE)
    _lines_at_most(2)
    shown = _rule(process_settings.view(PACK), MAX_LINES)
    assert (shown["value"], shown["own"], shown["versions"][0]["note"]) == (2, True, "short quotes")
    retired = _rule(process_settings.retire(PACK, MAX_LINES, "anna", kind=process_settings.RULE), MAX_LINES)
    assert (retired["value"], retired["own"]) == (300, False)


def test_a_case_reads_the_rule_files_with_the_values_active_when_it_started(golden, out) -> None:  # noqa: F811
    cases, _seen = golden
    many = [c for c in cases if c.expected.request is not None and len(c.expected.request.items) >= 3]
    before = _start(many[0])
    _lines_at_most(2)
    after = _start(many[1])
    with store.connect() as c:
        data = process_runtime.cases.find_case_in(c, after)["data"]
    assert data[capabilities.RULES] == {"quotes": {"draft.max_lines": 2}}
    assert data[capabilities.RULE_REFS]["quotes"]["draft.max_lines"] == {"setting": f"{PACK}/rule/{MAX_LINES}", "version": 1}
    with capabilities.case_rules(after):
        assert _max_lines() == 2
    with capabilities.case_rules(before):
        assert _max_lines() == 300
    assert _max_lines() == 300  # outside a case: the file
    _drive(after, send=False, reply=False)
    _drive(before, send=False, reply=False)
    assert len(quote_draft.view(after)["draft"]["lines"]) == 2  # the draft step ran with the case's value
    assert len(quote_draft.view(before)["draft"]["lines"]) >= 3


def test_the_worker_and_the_service_bind_a_case_s_values(golden, monkeypatch) -> None:  # noqa: F811
    cases, _seen = golden
    _lines_at_most(2)
    case_id = _start(cases[0])
    seen = []
    kind = job_kinds.JobKind("invented_rules_job", __name__, process=lambda job: seen.append(_max_lines()) or queue.complete(job.id),
                             abandon=lambda job, error: None)
    monkeypatch.setitem(job_kinds._KINDS, kind.kind, kind)
    for wp in (case_id, rows.WP):
        queue.enqueue(kind.kind, run_id=None, payload={"workpackage_id": wp})
        worker.handle(queue.claim("test", kinds=(kind.kind,)))
    assert seen == [2, 300]  # a package that is no case: the file

    app = create_app(store_path=store.current_path())

    @app.get("/api/invented/{case_id}")
    def invented(case_id: str) -> dict:
        return {"max_lines": _max_lines()}

    app.router.routes.insert(0, app.router.routes.pop())  # before the unknown-address answer

    with TestClient(app, base_url="http://127.0.0.1:8930") as c:
        assert c.get(f"/api/invented/{case_id}").json() == {"max_lines": 2}
        assert c.get(f"/api/invented/{rows.WP}").json() == {"max_lines": 300}
        shown = c.get(f"/api/processes/{PACK}/settings").json()
        assert _rule(shown, MAX_LINES)["value"] == 2
        human = {"X-Actor": "anna"}
        made = c.post(f"/api/processes/{PACK}/rules/{MAX_LINES}", headers=human, json={"value": 5})
        assert made.status_code == 201, made.text
        assert c.post(f"/api/processes/{PACK}/rules/{MAX_LINES}", headers=human, json={"value": 5000}).status_code == 422
        on = c.post(f"/api/processes/{PACK}/rules/{MAX_LINES}/versions/2/activate", headers=human, json={})
        assert on.status_code == 200 and _rule(on.json(), MAX_LINES)["value"] == 5
        assert c.post(f"/api/processes/{PACK}/rules/{MAX_LINES}/retire", headers=human, json={}).status_code == 200


def test_a_traced_decision_records_the_case_s_values_and_replays_with_them(golden, monkeypatch) -> None:  # noqa: F811
    point = trace.Point("invented.lines", "Whether a quote's lines fit.", "-", __name__, ("quotes.json",),
                        rule=lambda inputs: inputs["lines"] <= _max_lines())
    monkeypatch.setitem(trace._POINTS, point.code, point)
    cases, _seen = golden
    _lines_at_most(2)
    case_id = _start(cases[0])
    with capabilities.case_rules(case_id), store.connect() as c:
        trace.record_in(c, point.code, subject=("case", case_id), inputs={"lines": 3}, outcome=False,
                        keys={"quotes.json": ["draft.max_lines"]}, case_id=case_id)
    [row] = trace.rows(point=point.code)
    assert row["rules"][0]["process_values"] == [{"key": "draft.max_lines", "value": 2, "setting": f"{PACK}/rule/{MAX_LINES}",
                                                  "version": 1}]
    assert trace.replay(row) is False  # with the value it was made with, not the file's 300
    assert trace.replay(row, over=cfg.Overlay({"quotes": {"draft.max_lines": 5}})) is True


def test_a_step_event_and_timer_run_with_the_case_s_values() -> None:
    got = []
    handler = capabilities._with_rules(lambda ctx, c, event: got.append(_max_lines()) or kinds.APPLIED)

    class Ctx:
        data = {capabilities.RULES: {"quotes": {"draft.max_lines": 7}}}

    handler(Ctx(), None, None)
    assert got == [7] and _max_lines() == 300


def test_the_trace_names_each_config_by_its_file_under_configs() -> None:
    for name in cfg.all_names():
        file = trace.file_of(name)
        assert cfg.path_of(name).relative_to(cfg.CONFIG_DIR).as_posix() == file and trace._name_of(file) == name


def test_a_key_the_file_no_longer_holds_is_left_out(caplog) -> None:
    with cfg.overlay(cfg.Overlay({"quotes": {"draft.max_lines": 9, "draft.gone": 1, "nowhere.at_all": 2}})):
        assert _max_lines() == 9 and "gone" not in cfg.load("quotes")["draft"]
    assert "holds no rule draft.gone" in caplog.text


def test_an_approved_quote_and_its_letter_check_are_traced_decisions(golden, out) -> None:  # noqa: F811
    cases, _seen = golden
    case_id = _start(next(c for c in cases if c.expected.request is not None and c.expected.matches))
    _drive(case_id, send=False, reply=False)
    for code in ("quote.amounts", "quote.letter_check"):
        [row] = trace.rows(point=code, case_id=case_id)
        assert trace.replay(row) == row["outcome"], code  # the rule gives what was decided
    [letter] = trace.rows(point="quote.letter_check", case_id=case_id)
    assert set(letter["inputs"]) == {"chars", "found"}  # never the paragraph itself


def test_a_preview_tries_a_value_on_the_process_s_traced_decisions(golden) -> None:  # noqa: F811
    cases, _seen = golden
    case_id = _start(cases[0])
    inputs = {"currency": "HUF", "vat_percent": "27", "lines": [{"price": "1000.5", "quantity": "1", "discount_percent": "0"}]}
    with store.connect() as c:
        for subject, case in ((case_id, case_id), (rows.WP, None)):  # the second is no case of the process
            trace.record_in(c, "quote.amounts", subject=("quote_version", f"{subject}:1"), inputs=inputs,
                            outcome={"net": "1001", "vat": "270", "gross": "1271"},
                            keys={"price_lists.json": ["rounding.HUF"]}, case_id=case)
    shown = process_settings.preview(PACK, "price_lists.rounding.HUF", "0.01")
    assert (shown["decisions"], shown["changed"], shown["failed"], shown["file_value"]) == (1, 1, 0, "1")
    assert shown["examples"][0]["before"] == {"net": "1001", "vat": "270", "gross": "1271"}
    assert shown["examples"][0]["after"] == {"net": "1000.5", "vat": "270.14", "gross": "1270.64"}
    assert shown["examples"][0]["case"] == f"Quote {cases[0].id}"
    assert process_settings.preview(PACK, "price_lists.rounding.HUF", "1")["changed"] == 0
    assert process_settings.preview(PACK, MAX_LINES, 5)["decisions"] == 0  # no traced decision reads it yet
    with pytest.raises(process_settings.SettingError):
        process_settings.preview(PACK, "price_lists.rounding.HUF", "5")
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        answer = c.post(f"/api/processes/{PACK}/rules/price_lists.rounding.HUF/preview", json={"value": "0.01"})
        assert answer.status_code == 200 and answer.json()["changed"] == 1, answer.text


def test_a_config_hash_is_the_file_s_also_inside_a_case() -> None:
    cfg.config_hash.cache_clear()
    with cfg.overlay(cfg.Overlay({"quotes": {"draft.max_lines": 9}})):
        inside = cfg.config_hash("quotes")
    cfg.config_hash.cache_clear()
    assert inside == cfg.config_hash("quotes")
