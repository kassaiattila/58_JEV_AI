"""140 (backlog F-package-kinds K2; DECISIONS 137, 139, 140): the statement package.

A work package of its own kind for one own party and a period: its items are the bank statements of a folder or of
the given files, read by code where a bank's export allows it (one statement per account and month) and extracted by
AI from a PDF otherwise. Before anything is written, a survey says which file is which account's which month, what it
would replace and whose account it is. In a run, a PDF that turns out not to be a bank statement stops after its type
is recognised, with a to-do and without any extraction; an account no party holds yet goes to the package's party, and
another party's account is a to-do.

Synthetic exports and PDF lines only (the 137 Erste shapes, a made-up account number); no AI call, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jav import parties, reconcile, statement_package as sp, statement_table as st, store, work
from jav.runtime import queue, worker
from tests import test_api
from tests.test_flow_statement_table_136 import _run_all
from tests.test_statement_erste_137 import DIGITS, JUNE, MAY, OWN, PDF_JUNE, _export

OWN_KEY = reconcile.account_key(OWN)
PDF_MAY = ["Bankszámlakivonat", "Ügyfél neve, címe   EXAMPLE KFT.   Kivonat száma   E 2026/5",
           "Számla megnevezése   Időszak   2026.05.01. – 2026.05.31.",
           f"Bankszámlaszám   {OWN}   Devizanem   HUF", "BANKSZÁMLA FORGALMAK",
           "Könyvelés   Értéknap   Tranzakció megnevezése   Referencia   Összeg(+/-)   Egyenleg   Illeték (HUF)",
           "dátuma   (PTI+KPTI)", "Nyitó egyenleg", "2026.05.01.   101.500",
           "2026.05.12.   2026.05.12. KÁRTYA HASZNÁLAT   -1.500   100.000   (0,00)", "( - )",
           "Elfogadó   EXAMPLE SHOP", "1.500", "Összes terhelés", "Összes Jóváírás   0", "Záró egyenleg   100.000"]


@pytest.fixture(autouse=True)
def pdf_text(monkeypatch):
    """The PDF's text layer: the synthetic 'PDF' files hold their lines as plain text."""
    monkeypatch.setattr(st, "_pdf_lines", lambda path: Path(path).read_text(encoding="utf-8").splitlines())


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def _party(name: str = "Example Kft.") -> str:
    return parties.create(name, identities=[], actor="tester")["id"]


def _folder(root: Path, *, may_pdf: bool = False, stray: bool = True) -> Path:
    folder = root / "erste"
    _export(folder, "20260529", MAY, pdf=PDF_MAY if may_pdf else None)
    _export(folder, "20260630", JUNE, pdf=PDF_JUNE)
    if stray:  # a PDF no export uses: a statement for AI extraction, or not a statement at all
        (folder / "other-bank-2026-05.pdf").write_text("not a real PDF", encoding="utf-8")
    return folder


def _survey(folder: Path, party: str, start: str = "2026-05-01", end: str = "2026-06-30") -> dict:
    return sp.survey([folder], party_id=party, period_start=start, period_end=end)


def _row(survey: dict, month: str) -> dict:
    return next(r for r in survey["statements"] if r["period_start"].startswith(month))


# --- the survey ------------------------------------------------------------------------------------------------------------


def test_the_survey_lists_each_months_statement_and_the_pdfs_no_export_uses_without_writing(db):
    party = _party()
    survey = _survey(_folder(db), party)
    may, june = _row(survey, "2026-05"), _row(survey, "2026-06")
    assert (may["rank"], may["balance_checked"], may["companion"]) == ("unchecked", False, None)
    assert (june["rank"], june["balance_checked"], june["companion"]) == ("code_checked", True, f"20260630_{DIGITS}_S.pdf")
    assert (may["account"], may["currency"], may["lines"], june["lines"]) == ("…6666", "HUF", 1, 4)
    assert all(r["in_period"] and r["chosen"] and not r["in_store"] and r["owner"] == "none" for r in (may, june))
    assert [p["file"] for p in survey["pdfs"]] == ["other-bank-2026-05.pdf"]  # the companion PDF is not listed again
    assert survey["pdfs"][0]["chosen"] and survey["pdfs"][0]["statement"] is None
    assert not st.derived_dir().exists() and work.list_workpackages() == []


def test_a_statement_outside_the_period_is_listed_but_not_chosen(db):
    survey = _survey(_folder(db), _party(), start="2026-06-01", end="2026-06-30")
    assert (_row(survey, "2026-05")["in_period"], _row(survey, "2026-05")["chosen"]) == (False, False)
    assert _row(survey, "2026-06")["chosen"]


def test_the_survey_shows_what_a_better_statement_would_replace(db):
    party = _party()
    old = db / "old"
    _export(old, "20260529", MAY)  # May without its PDF: unchecked, in the store
    _run_all(sp.create_from_statement_table(old, [f"{DIGITS}:HUF:2026-05-01"], name="Erste May", owner="tester")["id"])
    [stored] = reconcile.statements()
    survey = _survey(_folder(db / "new", may_pdf=True), party)
    may = _row(survey, "2026-05")
    assert may["rank"] == "code_checked" and [r["id"] for r in may["replaces"]] == [stored["id"]]
    assert may["replaces"][0]["rank"] == "unchecked" and may["replaced_by"] is None and may["conflicts"] == []


def test_a_statement_already_in_the_store_is_not_chosen_again(db):
    party = _party()
    folder = _folder(db, stray=False)
    keys = [a.key for a in st.read(folder).accounts]
    _run_all(sp.create_from_statement_table(folder, keys, name="Erste", owner="tester")["id"])
    survey = _survey(folder, party)
    assert all(r["in_store"] and not r["chosen"] and r["replaces"] == [] for r in survey["statements"])


def test_the_owner_of_each_account_is_shown(db):
    party, other = _party(), _party("Other Home")
    folder = _folder(db, stray=False)
    parties.assign("account", OWN_KEY, OWN, other, actor="tester")
    assert {r["owner"] for r in _survey(folder, party)["statements"]} == {"other"}
    assert _survey(folder, party)["statements"][0]["owner_party"]["name"] == "Other Home"
    parties.assign("account", OWN_KEY, OWN, party, actor="tester")
    assert {r["owner"] for r in _survey(folder, party)["statements"]} == {"package"}
    parties.assign("account", OWN_KEY, OWN, None, actor="tester")  # dismissed as no own party's: a package takes it
    assert {r["owner"] for r in _survey(folder, party)["statements"]} == {"none"}


def test_the_survey_refuses_a_wrong_party_or_period(db):
    folder = _folder(db)
    with pytest.raises(sp.PackageError):
        _survey(folder, "party-000000000000")
    with pytest.raises(sp.PackageError):
        _survey(folder, _party(), start="2026-07-01", end="2026-06-30")


# --- creating the package ----------------------------------------------------------------------------------------------------


def test_the_package_holds_the_chosen_statements_and_pdfs_with_its_party_and_period(db):
    party = _party()
    folder = _folder(db)
    survey = _survey(folder, party)
    june = _row(survey, "2026-06")
    pdf = survey["pdfs"][0]["path"]
    view = sp.create(name="Example Kft. statements", party_id=party, period_start="2026-05-01", period_end="2026-06-30",
                     paths=[folder], statements=[june["id"]], pdfs=[pdf], actor="tester")
    wp = work.get(view["workpackage_id"])
    assert (wp["source_kind"], wp["owner"], wp["source_ref"]) == ("statements", "tester", str(folder.resolve()))
    kinds = sorted((i["kind"], Path(i["source_path"]).suffix) for i in wp["items"])
    assert kinds == [("document", ".pdf"), ("statement_table", ".json")]
    assert next(i for i in wp["items"] if i["kind"] == "statement_table")["item_id"] == june["id"]  # the survey's id
    assert (view["party"]["id"], view["period_start"], view["period_end"]) == (party, "2026-05-01", "2026-06-30")
    assert [e["action"] for e in work.workpackage_events(wp["id"])] == ["statement_scope"]


def test_creating_refuses_an_empty_choice_or_a_statement_the_files_no_longer_hold(db):
    party = _party()
    folder = _folder(db)
    args = {"name": "x", "party_id": party, "period_start": "2026-05-01", "period_end": "2026-06-30", "paths": [folder],
            "actor": "tester"}
    with pytest.raises(sp.PackageError):
        sp.create(statements=[], pdfs=[], **args)
    with pytest.raises(sp.PackageError):
        sp.create(statements=["0" * 64], pdfs=[], **args)
    with pytest.raises(sp.PackageError):  # only a PDF the survey listed
        sp.create(statements=[], pdfs=[str(folder / "pdf" / f"20260630_{DIGITS}_S.pdf")], **args)
    assert work.list_workpackages() == []


# --- processing -------------------------------------------------------------------------------------------------------------


def _package(db: Path, party: str, *, pdfs: bool = False) -> str:
    folder = _folder(db, stray=pdfs)
    survey = _survey(folder, party)
    return sp.create(name="Example statements", party_id=party, period_start="2026-05-01", period_end="2026-06-30",
                     paths=[folder], statements=[r["id"] for r in survey["statements"]],
                     pdfs=[p["path"] for p in survey["pdfs"]] if pdfs else [], actor="tester")["workpackage_id"]


def test_an_approved_live_run_gives_an_account_no_party_holds_to_the_packages_party(db):
    """153 (decision of 2026-10-13): the account goes to the party when the live run is approved, not when it is saved;
    until then a payment to it stays in the pairing instead of counting as a transfer between own accounts."""
    party = _party()
    wp = _package(db, party)
    run_id = _run_all(wp)
    assert work.get_run(run_id)["status"] in ("done", "needs_review")  # May's unchecked balances stay its own to-do
    assert parties.resolver().account(OWN_KEY) is None
    assert not [e for e in work.workpackage_events(wp) if e["action"] == "statement_account"]
    with store.connect() as c:  # a person closes the run's to-dos, then approves it
        c.execute("UPDATE review_reasons SET status='resolved' WHERE substr(run_id, 1, ?) = ?", (len(run_id) + 1, run_id + ":"))
    work.approve_run(run_id, actor="approver")
    assert parties.resolver().account(OWN_KEY) == party
    event = next(e for e in work.workpackage_events(wp) if e["action"] == "statement_account")
    detail = json.loads(event["detail"]) if isinstance(event["detail"], str) else event["detail"]
    assert detail == {"account": OWN_KEY, "party": party, "run_id": run_id} and event["actor"] == "approver"


def test_the_approval_reads_the_approved_runs_statements_not_a_later_reading(db):
    """174 (plan 170 L2): the accounts come from the approved run's own statements. Before, the rule read the store's
    latest reading of each statement, so a later command-line reading with another account gave that account."""
    party = _party()
    wp = _package(db, party)
    run_id = _run_all(wp)
    other = "99998887-77776666-55554444"
    with store.connect() as c:
        rows = c.execute("SELECT d.doc_id, d.doc_type, d.datapoints FROM datapoints d JOIN run_items ri"
                         " ON ri.flow_run_id = d.run_id AND ri.item_id = d.doc_id WHERE ri.run_id = ?", (run_id,)).fetchall()
    for r in rows:
        store.insert_datapoints(run_id=f"cli-{r['doc_id'][:12]}", doc_id=r["doc_id"], doc_type=r["doc_type"], arm="S",
                                datapoints={**json.loads(r["datapoints"]), "account_iban": None, "account_no": other},
                                field_conf={}, validation=[], route="auto", review_reasons=[], final_status="done")
    with store.connect() as c:
        c.execute("UPDATE review_reasons SET status='resolved' WHERE substr(run_id, 1, ?) = ?", (len(run_id) + 1, run_id + ":"))
    work.approve_run(run_id, actor="approver")
    assert parties.resolver().account(OWN_KEY) == party
    assert parties.resolver().account(reconcile.account_key(other)) is None


def test_a_trial_run_assigns_no_account(db):
    party = _party()
    _run_all(_package(db, party), mode="shadow")
    assert parties.resolver().account(OWN_KEY) is None


def test_another_partys_account_is_a_to_do_and_stays_where_it_is(db):
    party, other = _party(), _party("Other Home")
    parties.assign("account", OWN_KEY, OWN, other, actor="tester")
    run_id = _run_all(_package(db, party))
    assert parties.resolver().account(OWN_KEY) == other
    reasons = {r["reason"] for item in work.get_run(run_id)["items"]
               for r in work.item_reasons(run_id, item["item_id"])["run"]}
    assert f"statements:other_party:{other}" in reasons
    assert all(item["final_status"] == "needs_review" for item in work.get_run(run_id)["items"])


def _fake_stages(monkeypatch, detail: str | None, coarse: str) -> list[str]:
    flows: list[str] = []

    def stage(recipe, params, source_path, app_id, persister, **kwargs):
        flows.append(recipe["flow"])
        if recipe["flow"] == "doc_detect":
            return {"final_status": "done", "text_source": "pdf", "result": {"doc_type": coarse},
                    "detail": {"key": detail, "method": "jev" if detail else "no_candidate"}}
        return {"final_status": "done"}

    monkeypatch.setattr(worker, "_run_stage", stage)
    return flows


def _run_pdf(db: Path, monkeypatch, detail: str | None, coarse: str) -> tuple[str, list[str], dict]:
    party = _party()
    folder = db / "pdfs"
    folder.mkdir()
    pdf = folder / "statement.pdf"
    pdf.write_text("a PDF", encoding="utf-8")
    survey = sp.survey([pdf], party_id=party, period_start="2026-05-01", period_end="2026-06-30")
    wp = sp.create(name="PDF", party_id=party, period_start="2026-05-01", period_end="2026-06-30", paths=[pdf],
                   statements=[], pdfs=[survey["pdfs"][0]["path"]], actor="tester")["workpackage_id"]
    flows = _fake_stages(monkeypatch, detail, coarse)
    ready = work.readiness(wp)
    run_id = work.start_run(wp, mode="apply", expected_assignment_revision=0, input_hash=ready["input_hash"],
                            actor="tester")["run_id"]
    while (job := queue.claim("statement-package-test")) is not None:
        worker.process(job)
    [item] = work.get_run(run_id)["items"]
    return run_id, flows, item


def test_a_pdf_that_is_not_a_bank_statement_stops_after_its_type_with_a_to_do(db, monkeypatch):
    run_id, flows, item = _run_pdf(db, monkeypatch, "invoice_hu", "invoice_hu")
    assert flows == ["doc_detect"] and item["final_status"] == "needs_review"
    reasons = [r["reason"] for r in work.item_reasons(run_id, item["item_id"])["run"]]
    assert reasons == ["statements:not_a_statement:invoice_hu"]


def test_a_pdf_without_a_detailed_type_does_not_go_on_to_general_facts(db, monkeypatch):
    _run_id, flows, item = _run_pdf(db, monkeypatch, None, "payment_reminder")
    assert flows == ["doc_detect"] and item["final_status"] == "needs_review"


def test_a_bank_statement_pdf_goes_on_to_its_extraction(db, monkeypatch):
    _run_id, flows, _item = _run_pdf(db, monkeypatch, "statement_cib", "bank_statement")
    assert flows == ["doc_detect", "invoice"]


def test_the_same_pdf_in_an_ordinary_package_is_not_stopped(db, monkeypatch):
    pdf = db / "statement.pdf"
    pdf.write_text("a PDF", encoding="utf-8")
    wp = work.create_from_files([pdf], name="Files")
    flows = _fake_stages(monkeypatch, "invoice_hu", "invoice_hu")
    ready = work.readiness(wp["id"])
    work.start_run(wp["id"], mode="apply", expected_assignment_revision=0, input_hash=ready["input_hash"], actor="tester")
    while (job := queue.claim("statement-package-test")) is not None:
        worker.process(job)
    assert flows == ["doc_detect", "invoice"]


# --- the package's view ------------------------------------------------------------------------------------------------------


def test_the_packages_view_shows_each_items_statement_state(db):
    party = _party()
    wp = _package(db, party)
    before = sp.package_view(wp)
    assert {s["state"] for s in before["statements"]} == {"pending"}
    _run_all(wp)
    view = sp.package_view(wp)
    assert view["scope"]["party"]["id"] == party
    states = {s["period_start"][:7]: s["state"] for s in view["statements"]}
    assert states == {"2026-05": "valid", "2026-06": "valid"}
    assert all(s["account"] == "…6666" for s in view["statements"])


def test_the_statements_are_listed_by_account_and_in_time_with_the_unread_last():
    """167 (review 153 E): not in the order of their file names, which interleaved the months of several years."""
    rows = [{"file": "a-2023-10.xlsx", "account": "…1111", "period_start": "2023-10-01"},
            {"file": "b.pdf", "account": None, "period_start": None},
            {"file": "c-2022-11.xlsx", "account": "…1111", "period_start": "2022-11-01"},
            {"file": "d-2024-01.xlsx", "account": "…0000", "period_start": "2024-01-01"}]
    assert [r["file"] for r in sorted(rows, key=sp._in_order)] == ["d-2024-01.xlsx", "c-2022-11.xlsx", "a-2023-10.xlsx", "b.pdf"]


def test_a_package_with_its_scope_can_be_deleted_before_a_run(db):
    wp = _package(db, _party())
    work.delete_workpackage(wp, actor="tester")
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM statement_scopes").fetchone()[0] == 0


def test_a_partys_merge_moves_its_statement_packages(db):
    party, other = _party(), _party("Other Home")
    wp = _package(db, party)
    parties.merge(party, other, actor="tester")
    assert sp.scope(wp)["party"]["id"] == other


# --- the service ---------------------------------------------------------------------------------------------------------


env = test_api.env


def test_the_service_surveys_and_creates_a_statement_package(env):
    c, human = env["client"], test_api.HUMAN
    party = _party()
    folder = _folder(env["root"])
    body = {"paths": [str(folder)], "party_id": party, "period_start": "2026-05-01", "period_end": "2026-06-30"}
    assert c.post("/api/statement-packages/survey", json=body).status_code == 422  # a person asks for it
    r = c.post("/api/statement-packages/survey", headers=human, json=body)
    assert r.status_code == 200, r.text
    survey = r.json()
    assert len(survey["statements"]) == 2 and "EXAMPLE CLOUD" not in r.text  # no lines or partners leave
    chosen = {"statements": [s["id"] for s in survey["statements"]], "pdfs": []}
    r = c.post("/api/statement-packages", headers=human, json={**body, **chosen, "name": "Example statements"})
    assert r.status_code == 201, r.text
    view = r.json()
    assert view["workpackage"]["source_kind"] == "statements" and len(view["workpackage"]["items"]) == 2
    assert view["statements"]["scope"]["party"]["id"] == party
    unknown = {**body, "party_id": "party-000000000000"}
    assert c.post("/api/statement-packages/survey", headers=human, json=unknown).status_code == 422
    assert c.post("/api/statement-packages/survey", headers=human, json={**body, "paths": [str(folder / "nope")]}).status_code == 422
