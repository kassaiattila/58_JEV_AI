"""231 (plan stage B, B2; DECISIONS 231): a process's own values over its pack's resources.

A person saves a value as a draft, checked as the pack would be with it (a price list with no active version, an
unknown letter frame or a template of another output is refused); a version made active is the process's value, and
setting it aside brings the file's value back. A case takes the values active when it starts and keeps them. Who may
make a value active is a rule: by default the editor; or only the listed owners; or a second person. The output
template a process sets is its cases' default where a case chose none. Invented quote requests and price lists, a
stand-in model; no paid call.
"""

from __future__ import annotations

import pytest
from docx import Document
from fastapi.testclient import TestClient

from jav.app import process_runtime, process_settings
from jav.app.outputs import templates
from jav.core import cfg, store
from jav.domains.quotes import invented_golden, price_lists
from jav.service.api import create_app
from tests import test_document_result_174 as rows
from tests.test_quote_path_231 import golden  # noqa: F401 - the fixture

PACK = "it_quote"


def _second_list(tmp_path) -> str:
    made = price_lists.add("Second 2027", "s.xlsx", invented_golden.write_price_list(tmp_path / "s.xlsx").read_bytes(),
                           actor="anna")
    price_lists.activate(made["price_list"], 1, actor="anna")
    return made["price_list"]


def _start(case) -> str:
    return process_runtime.start_case(PACK, {"record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}},
                                      name=f"Quote {case.id}", actor="anna")


def _resource(view: dict, key: str) -> dict:
    return next(r for r in view["resources"] if r["key"] == key)


def _step_params(case_id: str, step: str) -> dict:
    from jav.core.process import cases

    with store.connect() as c:
        return cases.definition_of(cases.case_row(c, case_id)).step(step).params


def test_a_process_value_is_a_draft_until_it_is_made_active_and_reaches_the_cases_started_after(golden, tmp_path) -> None:  # noqa: F811
    cases, _seen = golden
    first = price_lists.chosen()
    before = _start(cases[0])
    shown = process_settings.view(PACK)
    listed = _resource(shown, "price_list")
    assert {k: listed[k] for k in ("key", "label", "file_value", "value", "own", "versions")} == {
        "key": "price_list", "label": "Price list", "file_value": "newest_active", "value": "newest_active", "own": False,
        "versions": []}
    with pytest.raises(process_settings.SettingError):
        process_settings.propose(PACK, "price_list", "pl-000000000000", "anna")  # no active list of that name
    with pytest.raises(process_settings.SettingError):
        process_settings.propose(PACK, "letter_frame", "nowhere", "anna")
    with pytest.raises(process_settings.SettingError):
        process_settings.propose(PACK, "unknown_resource", "x", "anna")
    second = _second_list(tmp_path)
    drafted = _resource(process_settings.propose(PACK, "price_list", second, "anna", note="the 2027 list"), "price_list")
    assert drafted["own"] is False and drafted["versions"][0]["state"] == "draft"  # a draft changes nothing yet
    active = _resource(process_settings.activate(PACK, "price_list", 1, "anna"), "price_list")
    assert (active["own"], active["value"], active["versions"][0]["state"]) == (True, second, "active")
    after = _start(cases[1])
    # D0-e: a case keeps the value it started with at the version current then
    assert _step_params(after, "match")["catalogue"] == f"{second}@1"
    assert _step_params(before, "match")["catalogue"] == f"{first.price_list}@{first.version}"  # then the newest active
    with store.connect() as c:
        assert process_runtime.resource_of(c, after, "price_list") == f"{second}@1"
    retired = _resource(process_settings.retire(PACK, "price_list", "anna"), "price_list")
    assert (retired["own"], retired["value"]) == (False, "newest_active")
    assert _step_params(_start(cases[2]), "match")["catalogue"] == f"{second}@1"  # the newest active one now


@pytest.mark.parametrize(("rule", "who", "allowed"), [
    ({"activation": "editor", "owners": []}, "anna", True),
    ({"activation": "owner", "owners": ["boss"]}, "anna", False),
    ({"activation": "owner", "owners": ["boss"]}, "boss", True),
    ({"activation": "second_person", "owners": []}, "anna", False),
    ({"activation": "second_person", "owners": []}, "bela", True),
])
def test_who_may_make_a_value_active_is_a_rule(golden, monkeypatch, rule, who, allowed) -> None:  # noqa: F811
    shipped = cfg.load

    monkeypatch.setattr(process_settings.cfg, "load", lambda name: {"meta": {"version": "x"}, **rule}
                        if name == process_settings.CONFIG else shipped(name))
    process_settings.propose(PACK, "send_mode", "output_folder", "anna")
    if allowed:
        assert _resource(process_settings.activate(PACK, "send_mode", 1, who), "send_mode")["own"] is True
    else:
        with pytest.raises(process_settings.SettingRefused):
            process_settings.activate(PACK, "send_mode", 1, who)


def test_the_template_a_process_sets_is_its_cases_default(golden, tmp_path) -> None:  # noqa: F811
    cases, _seen = golden
    doc = Document()
    doc.add_paragraph("Our offer to {{customer_name}}")
    path = tmp_path / "own.docx"
    doc.save(path)
    made = templates.add("quote", "Own offer", path.name, path.read_bytes(), actor="anna")
    with pytest.raises(process_settings.SettingError):
        process_settings.propose(PACK, "template:quote", made["template"], "anna")  # not active yet
    templates.activate(made["template"], 1, actor="anna")
    process_settings.propose(PACK, "template:quote", made["template"], "anna")
    process_settings.activate(PACK, "template:quote", 1, "anna")
    case_id = _start(cases[0])
    with store.connect() as c:
        assert templates._chosen(c, case_id, "quote")["template"] == made["template"]
        assert templates._chosen(c, rows.WP, "quote") is None  # a package that is no case: the built-in one


def test_the_service_shows_saves_and_activates_a_process_value(golden, tmp_path) -> None:  # noqa: F811
    human = {"X-Actor": "anna"}
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        assert [p["id"] for p in c.get("/api/processes").json()["processes"]] == ["bank_statements", "documents", "insurance_offer",
                                                                                    PACK, "mail_routing", "mailbox", "reconciliation"]
        shown = c.get(f"/api/processes/{PACK}/settings").json()
        assert shown["policy"] == {"activation": "editor", "owners": []}
        assert {r["key"] for r in shown["resources"]} >= {"price_list", "send_mode", "letter_frame", "template:quote"}
        made = c.post(f"/api/processes/{PACK}/settings/send_mode", headers=human, json={"value": "outlook_draft"})
        assert made.status_code == 201, made.text
        assert c.post(f"/api/processes/{PACK}/settings/send_mode", headers=human, json={"value": "carrier_pigeon"}).status_code == 422
        on = c.post(f"/api/processes/{PACK}/settings/send_mode/versions/1/activate", headers=human, json={})
        assert on.status_code == 200 and _resource(on.json(), "send_mode")["value"] == "outlook_draft"
        assert c.post(f"/api/processes/{PACK}/settings/send_mode/retire", headers=human, json={}).status_code == 200
        assert c.get("/api/processes/no_such_pack/settings").status_code == 404


def test_a_resource_takes_only_the_values_its_capability_offers_and_every_label_is_translated(golden, tmp_path) -> None:  # noqa: F811
    import json
    from pathlib import Path

    shown = process_settings.view(PACK)
    send = _resource(shown, "send_mode")
    assert (send["label"], [o["value"] for o in send["options"]]) == ("Send mode", ["output_folder", "outlook_draft"])
    with pytest.raises(process_settings.SettingError):
        process_settings.propose(PACK, "send_mode", "outlook_send", "anna")  # the real send stays a change of the file
    second = _second_list(tmp_path)
    assert second in [o["value"] for o in _resource(process_settings.view(PACK), "price_list")["options"]]
    hu = json.loads((Path(__file__).parent.parent / "ui" / "src" / "i18n" / "hu-native.json").read_text(encoding="utf-8"))
    shown = process_settings.view(PACK)
    labels = {r["label"] for r in shown["resources"]} | {r["what"] for r in shown["rules"]} | {p["label"] for p in shown["partners"]}
    labels |= {o["label"] for r in shown["resources"] for o in r["options"] or [] if o["label"] != o["value"]
               and (r["key"] != "price_list" or o["value"] == "newest_active")}  # a price list's own name is not translated
    assert not sorted(label for label in labels if label not in hu)
    assert shown["partners"] == [{"role": "customer", "label": "Customer", "step": "request", "step_title": "Request"}]
