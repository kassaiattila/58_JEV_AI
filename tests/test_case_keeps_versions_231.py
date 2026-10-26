"""231 (stage D0, D0-e; the owner's decision of 2026-10-26, the reassessment's P05): a case runs to its end with the
versions it started with.

A case keeps from its start the price list version and the template version active then (a newer one reaches only the
cases started after it), and the rule files its steps read as its calculation snapshot holds them: a file changed
since is read as it was, with a key added since taken from the file, and a decision traced meanwhile names the kept
copy. A kept copy of another main version stops the step that reads it with the file and both versions, and the
release check lists the open cases it stops. A case started before D0-e keeps nothing and reads the files and the
active versions, as before. The case's history names what it keeps. Invented quote requests and price lists, a
stand-in model; no paid call.
"""

from __future__ import annotations

import argparse
import json
import shutil
from unittest import mock

import pytest
from docx import Document

from jav.app import capabilities, case_views, process_runtime, process_settings
from jav.app.outputs import templates
from jav.cli import maintenance_cli
from jav.core import cfg, identity, store, trace
from jav.core.process import cases, engine, tasks
from jav.domains.quotes import price_lists, quote_letter, quote_package, quote_proposal, quote_steps
from tests import test_document_result_174 as rows
from tests.test_quote_path_231 import ACTOR, _drain, golden  # noqa: F401 - the fixture

PACK = "it_quote"
PERSON = identity.who(ACTOR)


def _start(case, name: str = "Kept") -> str:
    return process_runtime.start_case(PACK, {"record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}},
                                      name=f"{name} {case.id}", actor=ACTOR)


def _catalogue(case_id: str, step: str = "match") -> str:
    with store.connect() as c:
        return str(cases.definition_of(cases.find_case_in(c, case_id)).step(step).params["catalogue"])


def _new_version(price_list: str, version: int) -> int:
    """A changed setting of the list: its next version, made active."""
    current = price_lists.version(price_list, version)
    made = price_lists.change_settings(price_list, version, actor=ACTOR, currency=current.currency,
                                       vat_percent=str(current.vat_percent + 1), discounts=[])
    price_lists.activate(price_list, made["version"], actor=ACTOR)
    return int(made["version"])


def _kept_of(case_id: str) -> dict:
    events = case_views._timeline(case_id, None, {})["events"]
    return next(e for e in events if e["kind"] == "started")["detail"].get("kept")


def test_a_case_keeps_the_price_list_version_of_its_start(golden) -> None:  # noqa: F811
    cases_, _seen = golden
    old = price_lists.chosen()
    first = _start(cases_[0])
    assert _catalogue(first) == _catalogue(first, "compose") == f"{old.price_list}@{old.version}"
    newer = _new_version(old.price_list, old.version)
    second = _start(cases_[0], "After")
    assert _catalogue(second) == f"{old.price_list}@{newer}"  # a newer version reaches the cases started after it
    quote_proposal.request(first, actor=ACTOR, step="match")  # a person asks: the step's own list, not the newest
    _drain()
    proposal = quote_proposal.current(first, step="match")
    assert (proposal["state"], proposal["version"], proposal["stale"]) == ("done", old.version, False)
    shown = quote_package.view(first)["price_lists"]
    assert [(p["price_list"], p["version"]) for p in shown] == [(old.price_list, old.version)]
    kept = _kept_of(first)
    assert {"key": "price_list", "label": "Price list", "name": "Invented 2026", "version": old.version} in kept["resources"]
    assert {"file": "quotes", "version": cfg.version("quotes")} in kept["rules"]


def test_a_case_keeps_the_template_version_of_its_start(golden, tmp_path) -> None:  # noqa: F811
    cases_, _seen = golden
    doc = Document()
    doc.add_paragraph("Our offer to {{customer_name}}")
    path = tmp_path / "own.docx"
    doc.save(path)
    made = templates.add("quote", "Own offer", path.name, path.read_bytes(), actor=ACTOR)
    templates.activate(made["template"], 1, actor=ACTOR)
    process_settings.propose(PACK, "template:quote", made["template"], ACTOR)
    process_settings.activate(PACK, "template:quote", 1, ACTOR)
    first = _start(cases_[0])
    templates.add("quote", "Own offer", path.name, path.read_bytes(), actor=ACTOR, template=made["template"])
    templates.activate(made["template"], 2, actor=ACTOR)
    second = _start(cases_[0], "After")
    with store.connect() as c:
        assert templates._chosen(c, first, "quote")["version"] == 1  # superseded now, kept by the case
        assert templates._chosen(c, second, "quote")["version"] == 2
    assert {"key": "template:quote", "label": "Output template", "name": "Own offer", "version": 1} in _kept_of(first)["resources"]


@pytest.fixture()
def configs(golden, tmp_path):  # noqa: F811
    """A copy of the rule files the test may change, read as the folder."""
    copy = tmp_path / "configs"
    shutil.copytree(cfg.CONFIG_DIR, copy)
    with mock.patch.multiple(cfg, CONFIG_DIR=copy, CALLSITE_DIR=copy / "callsites", TYPES_DIR=copy / "types",
                             PROCESSES_DIR=copy / "processes"):
        cfg.reload()
        yield golden, copy
    cfg.reload()


def _change(copy, version: str, section: str = "draft", **values) -> None:
    """quotes.json at `version`, with these keys of a section changed (or added)."""
    path = copy / "quotes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["meta"]["version"] = version
    data[section].update(values)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cfg.reload()


def _minor(version: str) -> str:
    major, minor, _patch = version.split(".")
    return f"{major}.{int(minor) + 1}.0"


def test_a_case_reads_the_rule_files_as_it_started(configs) -> None:
    (cases_, _seen), copy = configs
    was, before = cfg.version("quotes"), cfg.config_hash("quotes")
    lines, chars = cfg.load("quotes")["draft"]["max_lines"], cfg.load("quotes")["letter"]["max_chars"]
    first = _start(cases_[0])
    _change(copy, _minor(was), max_lines=lines + 7)
    _change(copy, _minor(was), "letter", max_chars=chars + 100)
    second = _start(cases_[0], "After")
    facts = quote_letter.paragraph_facts("x" * (chars + 50))  # too long as the case started, short enough now
    with capabilities.case_rules(first):
        assert cfg.load("quotes")["draft"]["max_lines"] == lines and cfg.version("quotes") == was
        assert cfg.config_hash("quotes") == before  # the ledger names the copy the case read
        assert quote_letter.paragraph_problems(facts) == ["too_long"]
        with store.connect() as c:
            row_id = trace.record_in(c, quote_letter.LETTER_CHECK, subject=("quote_letter", f"{first}:1"), inputs=facts,
                                     outcome=["too_long"], keys={"quotes.json": ["letter.max_chars"]}, case_id=first)
    with capabilities.case_rules(second):
        assert cfg.load("quotes")["draft"]["max_lines"] == lines + 7
    assert cfg.load("quotes")["draft"]["max_lines"] == lines + 7  # outside a case: the file
    recorded = next(r for r in trace.rows(case_id=first) if r["id"] == row_id)
    entry = next(e for e in recorded["rules"] if e["file"] == "quotes.json")
    assert (entry["version"], entry.get("kept")) == (was, True)
    assert trace.replay(recorded) == ["too_long"]  # a replay reads the kept copy again
    _change(copy, _minor(_minor(was)), d0e_added=3)
    with capabilities.case_rules(first):  # a key added since: from the file, so newer code reads what it expects
        assert cfg.load("quotes")["draft"]["d0e_added"] == 3 and cfg.load("quotes")["draft"]["max_lines"] == lines


def test_a_rule_file_of_another_main_version_stops_the_step_with_why(configs, capsys) -> None:
    (cases_, _seen), copy = configs
    was = cfg.version("quotes")
    case_id = _start(cases_[0])
    newer = f"{int(was.split('.')[0]) + 1}.0.0"
    _change(copy, newer)
    with capabilities.case_rules(case_id), pytest.raises(cfg.RulesUnfit, match=f"quotes {was}.*{newer}: another main version"):
        cfg.load("quotes")
    assert [(u["case"], u["file"]) for u in process_runtime.unfit_cases()] == [(case_id, "quotes")]
    assert maintenance_cli.cmd_cases_kept(argparse.Namespace(store=None)) == 1  # the release check names it
    assert case_id in capsys.readouterr().out
    for _ in range(3):  # a person starts the match step; it reads the quote rules and stops with why
        engine.turn(case_id, wake=True)
        for t in engine.state(case_id)["tasks"]:
            if t["status"] == tasks.OPEN and t["task_id"] == f"step_start:{case_id}:match":
                tasks.decide(t["task_id"], PERSON)
    step = engine.state(case_id)["steps"]["match"]
    assert step["state"] == "failed" and "another main version" in (step["note"] or "")


def test_a_case_started_before_d0e_reads_the_files_and_the_active_versions(configs) -> None:
    (cases_, _seen), copy = configs
    lines = cfg.load("quotes")["draft"]["max_lines"]
    case_id = _start(cases_[0])
    with store.connect() as c:  # as a case started before D0-e: it names no rule file it keeps
        c.execute("UPDATE process_cases SET data=json_remove(data, '$.kept_rule_files') WHERE case_id=?", (case_id,))
    _change(copy, _minor(cfg.version("quotes")), max_lines=lines + 1)
    with capabilities.case_rules(case_id):
        assert cfg.load("quotes")["draft"]["max_lines"] == lines + 1
    assert _kept_of(case_id) is None
    assert quote_steps.catalogue(rows.WP, "match") == price_lists.NEWEST_ACTIVE  # a package that is no case
