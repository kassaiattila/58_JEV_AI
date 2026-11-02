"""277 (O3; the owner's decision of 2026-11-02: one case type in place of several alike): a process pack's choices.

A pack may ask a choice when a case starts (the invoices' source, whether the emails are routed, the product): each
option leaves steps out, sets resources and step parameters, and brings its own example material. A case's pack is the
pack narrowed by its choices before its definition is made, so a step left out is not in the case at all: the engine,
the track and the sub-cases see only the chosen steps. The check refuses a choice that names what is not there, and
checks every combination of the options as a pack of its own. Synthetic pack data built from a real pack, no AI call.
"""

from __future__ import annotations

import copy

import pytest

from jav.app import process_packs, registrations
from jav.core import cfg


@pytest.fixture(scope="module", autouse=True)
def _registered() -> None:
    registrations.load_all()


def _chained() -> dict:
    """The monthly reconciliation's four-step chain with its choice of the invoices' source (O3f), without what it
    replaces (the tests add that themselves)."""
    data = copy.deepcopy(cfg.load("process:monthly_reconciliation"))
    del data["replaces"]
    assert [o["id"] for o in data["choices"][0]["options"]] == ["folder", "mailbox", "both"]
    return data


def _pack(data: dict) -> process_packs.ProcessPack:
    return process_packs.ProcessPack.model_validate(data)


def _problems(data: dict) -> list[str]:
    return process_packs._problems(_pack(data))


def test_a_pack_with_a_choice_passes_its_check_and_lists_its_variants() -> None:
    pack = _pack(_chained())
    assert _problems(_chained()) == []
    assert process_packs.variants(pack) == [{"invoices_from": "folder"}, {"invoices_from": "mailbox"},
                                            {"invoices_from": "both"}]
    assert process_packs.variants(_pack(copy.deepcopy(cfg.load("process:it_quote")))) == [{}]


def test_the_chosen_pack_leaves_the_steps_out_and_the_steps_that_waited_for_them_wait_for_the_rest() -> None:
    pack = _pack(_chained())
    folder = process_packs.chosen(pack, {})  # the default
    assert [s.id for s in folder.steps] == ["invoices", "statements", "reconcile"]
    assert next(s for s in folder.steps if s.id == "reconcile").after == ("invoices", "statements")
    overview = folder.screens.tabs[0]
    assert [e.step for e in overview.elements] == [None, "invoices", "statements", "reconcile"]
    assert folder.choices == ()  # a narrowed pack asks nothing more
    assert process_packs.chosen(_merged(), {}).replaces == ()  # and replaces nothing (its file says what it did)
    mailbox = process_packs.chosen(pack, {"invoices_from": "mailbox"})
    assert [s.id for s in mailbox.steps] == ["emails", "statements", "reconcile"]
    both = process_packs.chosen(pack, {"invoices_from": "both"})
    assert [s.id for s in both.steps] == ["invoices", "emails", "statements", "reconcile"]
    # the definition a case keeps has the chosen steps only
    assert [s.id for s in process_packs.definition(folder).steps] == ["invoices", "statements", "reconcile"]
    assert process_packs.definition(folder).version == pack.version


def test_an_unknown_choice_or_option_is_refused_and_a_pack_without_choices_stays_as_it_is() -> None:
    pack = _pack(_chained())
    with pytest.raises(process_packs.PackError, match="no choice 'product'"):
        process_packs.chosen(pack, {"product": "x"})
    with pytest.raises(process_packs.PackError, match="no option 'tray' of the choice 'invoices_from'"):
        process_packs.chosen(pack, {"invoices_from": "tray"})
    quote = process_packs.load("it_quote")
    assert process_packs.chosen(quote, {}) is quote
    assert process_packs.chosen(quote, None) is quote
    with pytest.raises(process_packs.PackError, match="no choice"):
        process_packs.chosen(quote, {"invoices_from": "folder"})
    assert process_packs.picked(pack, None) == {"invoices_from": "folder"}


def test_an_option_sets_resources_step_parameters_and_its_own_examples() -> None:
    data = copy.deepcopy(cfg.load("process:insurance_offer"))
    facts = next(s for s in data["steps"] if s["id"] == "facts")
    data["choices"] = [{"id": "product", "title": "Product", "default": "invented", "options": [
        {"id": "invented", "title": "Invented"},
        {"id": "other", "title": "Another", "params": {"facts": {"readings": "fact_readings_allianz_property"}},
         "examples": {"documents": "allianz_property_documents"}}]}]
    pack = _pack(data)
    other = process_packs.chosen(pack, {"product": "other"})
    assert next(s for s in other.steps if s.id == "facts").params == {**facts["params"], "readings": "fact_readings_allianz_property"}
    assert other.examples is not None and other.examples.documents == "allianz_property_documents"
    invented = process_packs.chosen(pack, {})
    assert next(s for s in invented.steps if s.id == "facts").params == facts["params"]
    assert invented.examples == pack.examples


def _with_choice(**option) -> dict:
    data = _chained()
    data["choices"][0]["options"][1].update(option)
    return data


@pytest.mark.parametrize(("change", "expected"), [
    (lambda d: d["choices"][0].update(default="tray") or d, "choice 'invoices_from': its default 'tray' is none of its options"),
    (lambda d: d["choices"].append(copy.deepcopy(d["choices"][0])) or d, "a choice is listed twice: invoices_from"),
    (lambda d: d["choices"][0]["options"].append({"id": "both", "title": "Again"}) or d,
     "choice 'invoices_from': an option is listed twice: both"),
    (lambda d: _with_choice(leaves_out=["ghost"]), "option 'mailbox' leaves out no step 'ghost'"),
    (lambda d: _with_choice(params={"ghost": {"pack": "documents"}}), "option 'mailbox' sets parameters of no step 'ghost'"),
    (lambda d: _with_choice(params={"statements": {"_start": "auto"}}), "option 'mailbox' sets the pack's own parameter '_start'"),
    (lambda d: _with_choice(resources={"price_list": "x"}), "option 'mailbox' sets 'price_list', which is no resource of the pack"),
    (lambda d: _with_choice(params={"statements": {"pack": "nowhere"}}), "with invoices_from=mailbox: step 'statements'"),
    (lambda d: _with_choice(leaves_out=["invoices", "emails", "statements", "reconcile"]),
     "with invoices_from=mailbox: it leaves out every step"),
    (lambda d: d.update(replaces=[{"pack": "monthly_reconciliation"}]) or d, "replaces itself"),
    (lambda d: d.update(replaces=[{"pack": "old_chain", "choices": {"invoices_from": "tray"}}]) or d,
     "replaces 'old_chain': no option 'tray' of the choice 'invoices_from'"),
])
def test_a_choice_that_names_what_is_not_there_is_refused(change, expected) -> None:
    problems = _problems(change(_chained()))
    assert any(expected in p for p in problems), problems


# --- 277 (O3b): a case starts on the pack narrowed by its choices --------------------------------------------------


MARCH = ["2026-03-01", "2026-03-31"]
PERSON = "anna"


def _merged() -> process_packs.ProcessPack:
    """The merged monthly reconciliation (O3f): the four-step chain with the invoices' source chosen, taking the place
    of the two chains it unites."""
    return process_packs.load("monthly_reconciliation")


def _old(pack_id: str, picks: dict[str, str]) -> tuple[process_packs.ProcessPack, str]:
    """A retired pack as its file was before the merge: the merged one's variant under its own id and version, and its
    file's text."""
    import json

    data = process_packs.chosen(_merged(), picks).model_dump(mode="json")
    data["id"] = pack_id
    data["meta"] = {**data["meta"], "name": f"process:{pack_id}", "version": "1.1.1"}
    del data["choices"], data["replaces"]
    return _pack(data), json.dumps(data)


OLD = {"mailbox_reconciliation": {"invoices_from": "mailbox"}}


@pytest.fixture
def merged(tmp_path, monkeypatch):
    """A store, and the retired packs as they were before the merge: loaded while not `gone`, and in the snapshot a
    case started on one keeps (the live store's cases of them hold their file's text)."""
    from jav.core import rulebook, store
    from tests.statement_pdf import pdf_lines_as_text

    pdf_lines_as_text(monkeypatch)
    real, old = process_packs.load, {pid: _old(pid, picks) for pid, picks in OLD.items()}
    gone: set[str] = set()

    def load(pack_id: str) -> process_packs.ProcessPack:
        if pack_id not in old:
            return real(pack_id)
        if pack_id in gone:
            raise process_packs.UnknownPack(f"no process pack {pack_id!r}")
        return old[pack_id][0]

    get_in, content_in = rulebook.get_in, rulebook.content_in

    def snapshot(c, snapshot_id):
        found = get_in(c, snapshot_id) or {}
        return {**found, "files": {**(found.get("files") or {}),
                                   **{f"processes/{pid}.json": {"sha256": f"old-{pid}"} for pid in old}}}

    monkeypatch.setattr(process_packs, "load", load)
    monkeypatch.setattr(rulebook, "get_in", snapshot)
    monkeypatch.setattr(rulebook, "content_in", lambda c, sha: old[sha[4:]][1] if sha.startswith("old-") else content_in(c, sha))
    with store.use_store(tmp_path / "choices.sqlite"):
        yield tmp_path, gone


def _scope(folder, *steps: str) -> dict:
    from tests.test_workflows_146 import _invoices, _party, _statements

    sources = {"invoices": {"kind": "folder", "folder": str(_invoices(folder / "inv", n=1))},
               "emails": {"kind": "mailbox", "request": {"accounts": ["office@example.com"], "since_days": 7}},
               "statements": {"kind": "folder", "folder": str(_statements(folder / "erste"))}}
    return {"party": _party(), "period": MARCH, "step_sources": {s: sources[s] for s in steps}}


def _data(case_id: str) -> dict:
    from jav.core import store
    from jav.core.process import cases

    with store.connect() as c:
        return cases.find_case_in(c, case_id)["data"]


def test_a_case_keeps_its_choices_and_runs_only_the_chosen_steps(merged) -> None:
    from jav.app import case_views, process_runtime

    folder, _gone = merged
    case = process_runtime.start_case("monthly_reconciliation", _scope(folder, "emails", "statements"), name="March",
                                      actor=PERSON, choices={"invoices_from": "mailbox"})
    assert _data(case)["choices"] == {"invoices_from": "mailbox"}
    assert [s.id for s in process_runtime.pack_for(case).steps] == ["emails", "statements", "reconcile"]
    assert list(case_views.view(case)["steps"]) == ["emails", "statements", "reconcile"]
    draft = process_runtime.next_draft(case)  # its next period is chosen alike
    assert (draft["pack"], draft["choices"]) == ("monthly_reconciliation", {"invoices_from": "mailbox"})
    default = process_runtime.start_case("monthly_reconciliation", _scope(folder / "b", "invoices", "statements"),
                                         name="March B", actor=PERSON)
    assert _data(default)["choices"] == {"invoices_from": "folder"}
    assert [s.id for s in process_runtime.pack_for(default).steps] == ["invoices", "statements", "reconcile"]
    with pytest.raises(process_packs.PackError, match="no option 'tray'"):
        process_runtime.start_case("monthly_reconciliation", _scope(folder / "c", "invoices", "statements"),
                                   name="March C", actor=PERSON, choices={"invoices_from": "tray"})
    documents = process_runtime.start_case("documents", {"source": _scope(folder / "d", "invoices")["step_sources"]["invoices"]},
                                           name="Documents", actor=PERSON)
    assert "choices" not in _data(documents)  # a pack without choices keeps its cases' data as it was


def test_a_case_of_a_pack_another_took_the_place_of_runs_on_and_goes_on_as_the_new_ones(merged) -> None:
    from jav.app import case_views, process_runtime

    folder, gone = merged
    old = process_runtime.start_case("mailbox_reconciliation", _scope(folder, "emails", "statements"), name="Old March",
                                     actor=PERSON)
    gone.add("mailbox_reconciliation")  # the file is removed
    assert [s.id for s in process_runtime.pack_for(old).steps] == ["emails", "statements", "reconcile"]
    assert case_views.view(old)["case"]["pack"] == "mailbox_reconciliation"
    draft = process_runtime.next_draft(old)
    assert (draft["pack"], draft["choices"]) == ("monthly_reconciliation", {"invoices_from": "mailbox"})
    scope = {"party": _data(old)["scope"]["party"], "period": [draft["period_start"], draft["period_end"]],
             "step_sources": draft["step_sources"]}
    following = process_runtime.start_next(old, "monthly_reconciliation", scope, name="April", actor=PERSON)
    assert _data(following)["choices"] == {"invoices_from": "mailbox"} and _data(following)["follows"] == old
    assert [s.id for s in process_runtime.pack_for(following).steps] == ["emails", "statements", "reconcile"]


def test_a_resource_an_option_sets_is_the_cases_choice_not_the_processs_own_value(tmp_path, monkeypatch) -> None:
    import json

    from jav.app import process_settings
    from jav.core import store

    data = copy.deepcopy(cfg.load("process:insurance_offer"))
    data["choices"] = [{"id": "frame", "title": "Frame", "default": "file", "options": [
        {"id": "file", "title": "As the file"}, {"id": "other", "title": "Another", "resources": {"letter_frame": "chosen_frame"}}]}]
    pack = _pack(data)
    own = [{"key": "letter_frame", "value": json.dumps("own_frame"), "setting_id": "s", "version": 1}]
    monkeypatch.setattr(process_settings, "_active_rows", lambda c, pack_id, kind: own if kind == process_settings.RESOURCE else [])
    with store.use_store(tmp_path / "own.sqlite"):
        assert process_settings.effective_resources(process_packs.chosen(pack, {"frame": "other"}))["letter_frame"] == "chosen_frame"
        assert process_settings.effective_resources(process_packs.chosen(pack, {}))["letter_frame"] == "own_frame"
    assert process_packs.chosen(pack, {"frame": "other"}).fixed == ("letter_frame",)
    assert pack.option_resources() == {"letter_frame"}


# --- 277 (O3c): a sub-case reads the batch a step of its own case keeps ------------------------------------------


def _routed_mailbox() -> dict:
    """The mailbox download with its routing as a step of its own case (the shape of the merged mailbox process)."""
    data = copy.deepcopy(cfg.load("process:mailbox"))
    data["steps"].append({"id": "routing", "uses": "run_case@1", "title": "Routing", "after": ["process"],
                          "params": {"pack": "mail_routing", "sources_from": ["process"]}})
    data["screens"]["tabs"].insert(1, {"id": "routing", "label": "Routing",
                                       "elements": [{"type": "sub_case", "step": "routing"}]})
    data["choices"] = [{"id": "routing", "title": "Routing", "default": "download_only", "options": [
        {"id": "download_only", "title": "Download only", "leaves_out": ["routing"]},
        {"id": "route", "title": "Download and route"}]}]
    return data


def test_a_sub_case_may_read_the_batch_its_own_cases_step_keeps() -> None:
    assert _problems(_routed_mailbox()) == []
    data = _routed_mailbox()
    data["steps"][1]["params"]["sources_from"] = ["nowhere"]
    assert any("sources_from names 'nowhere', which is no step that runs a case or keeps a batch" in p for p in _problems(data))
    # the default leaves the routing out: the mailbox download as it was
    assert [s.id for s in process_packs.chosen(_pack(_routed_mailbox()), {}).steps] == ["process"]


def test_the_batch_of_a_step_of_the_case_itself_is_read_as_a_sub_cases_batches(monkeypatch) -> None:
    from jav.app import document_processing, sub_cases

    class Ctx:
        case_id = "wp-case"

        def result_of(self, step_id):
            return ("done", {"case_id": "wp-sub"} if step_id == "emails" else {})

    monkeypatch.setattr(document_processing, "case_packages", lambda case: ["wp-a", "wp-b"] if case == "wp-sub" else [])
    monkeypatch.setattr(document_processing, "package_of", lambda case, step: "wp-own" if (case, step) == ("wp-case", "process") else None)
    assert sub_cases._batches(Ctx(), ("emails", "process", "ghost")) == ["wp-a", "wp-b", "wp-own"]


# --- 277 (O3d): the local service lists the choices and takes them when a case starts ------------------------------


def test_the_service_lists_a_processs_choices_and_starts_a_case_with_them(merged) -> None:
    from fastapi.testclient import TestClient

    from jav.core import store
    from jav.service.api import create_app

    folder, _gone = merged
    scope = _scope(folder, "emails", "statements")
    body = {"pack": "monthly_reconciliation", "name": "March", "party_id": scope["party"], "period_start": MARCH[0],
            "period_end": MARCH[1], "step_sources": scope["step_sources"]}
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        listed = {p["id"]: p for p in c.get("/api/processes").json()["processes"]}
        [choice] = listed["monthly_reconciliation"]["choices"]
        assert (choice["id"], choice["default"]) == ("invoices_from", "folder")
        assert [(o["id"], o["leaves_out"], o["missing_at_start"]) for o in choice["options"]] == [
            ("folder", ["emails"], []), ("mailbox", ["invoices"], []), ("both", [], [])]
        assert listed["documents"]["choices"] == []
        refused = c.post("/api/cases", headers={"X-Actor": PERSON}, json={**body, "choices": {"invoices_from": "tray"}})
        assert refused.status_code == 400 and refused.json()["error"] == "choice_refused", refused.text
        made = c.post("/api/cases", headers={"X-Actor": PERSON}, json={**body, "choices": {"invoices_from": "mailbox"}})
        assert made.status_code == 201, made.text
        assert _data(made.json()["case_id"])["choices"] == {"invoices_from": "mailbox"}
        assert c.get(f"/api/cases/{made.json()['case_id']}/next").json()["choices"] == {"invoices_from": "mailbox"}
        assert c.get("/api/processes/monthly_reconciliation/examples?choice=invoices_from:both").status_code == 200
        assert c.get("/api/processes/monthly_reconciliation/examples?choice=invoices_from:tray").status_code == 400


# --- 277 (O3e): the case types' groups ------------------------------------------------------------------------------


def test_every_process_stands_in_one_group_and_the_service_names_it() -> None:
    from fastapi.testclient import TestClient

    from jav.service.api import create_app

    assert process_packs.group_problems() == []
    assert [g["id"] for g in process_packs.groups()] == ["documents", "emails", "reconciliation", "quotes"]
    assert process_packs.group_of("bank_statements") == "documents"
    assert process_packs.group_of("it_quote") == "quotes"
    assert process_packs.group_of("nowhere") is None
    with TestClient(create_app(), base_url="http://127.0.0.1:8930") as c:
        listed = c.get("/api/processes").json()
    assert [g["title"] for g in listed["groups"]] == ["Documents", "Emails", "Reconciliation", "Quotes"]
    assert {p["id"]: p["group"] for p in listed["processes"]}["mail_routing"] == "emails"


def test_a_group_that_names_what_is_not_there_is_refused(monkeypatch) -> None:
    groups = [{"id": "documents", "title": "Documents", "processes": ["documents", "ghost"]},
              {"id": "documents", "title": "", "processes": ["documents"]}]
    monkeypatch.setattr(process_packs, "groups", lambda: groups)
    problems = process_packs.group_problems()
    for expected in ("a group is listed twice: documents", "group 'documents' has no title",
                     "group 'documents' names no process pack 'ghost'", "process 'documents' stands in two groups",
                     "process 'bank_statements' stands in no group"):
        assert any(expected in p for p in problems), (expected, problems)


def test_a_retired_packs_cases_stand_in_its_successors_group(monkeypatch) -> None:
    monkeypatch.setattr(process_packs, "successor", lambda pack_id: ("monthly_reconciliation", {}) if pack_id == "old_chain" else None)
    assert process_packs.group_of("old_chain") == "reconciliation"
