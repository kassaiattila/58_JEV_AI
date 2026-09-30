"""K5.1–K5.2 (058): a levél-eredmény futásonként megőrződik, a levél szövegéből látott rész jelölve van, a Levelek adatkészlet
az Eredményben, és a szándék kézzel javítható (a továbbirányítás a javított szándékból számolódik).

Mesterséges levelek, hamis Outlook-szkript és hamis JEV, fizetős hívás nélkül."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from jav import api, corrections, datasets, emails, intent, mailbox, store, work, work_views
from jav.emails import EmailMessage
from jav.runtime import worker
from tests.test_mailbox import MAILS, REQ, FakeBridge, env  # noqa: F401 - pytest-fixture

HUMAN = {"X-Actor": "teszt.elek"}


def _email_run(env) -> tuple[str, str, list[dict]]:  # noqa: F811 - a fixture neve
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge(MAILS), inbox_root=env["inbox"])
    wp_id = res["workpackage"]
    ready = work.readiness(wp_id)
    run_id = work.start_run(wp_id, mode="shadow", expected_assignment_revision=1, input_hash=ready["input_hash"], actor="t")["run_id"]
    worker.run_worker(once=True)
    return wp_id, run_id, work.get_run(run_id)["input"]["items"]


# --- a levél szövegéből látott rész ----------------------------------------------------------------------------


def test_body_coverage_full_shortened_and_capped():
    short = emails.body_coverage(EmailMessage(message_id="a", body="Mellékelten küldjük a számlát.\nÜdv"))
    assert short["status"] == "full" and short["chars"] == short["seen_chars"] + 1  # a sortörés nem látott karakter
    many = "\n".join(f"{i}. sor a levélben" for i in range(intent.MAX_BODY_LINES + 20))
    long_ = emails.body_coverage(EmailMessage(message_id="b", body=many))
    assert long_["status"] == "shortened" and 0 < long_["seen_chars"] < long_["chars"]
    capped = emails.body_coverage(EmailMessage(message_id="c", body="x" * emails.BRIDGE_BODY_LIMIT))
    assert capped["status"] == "capped"  # a letöltéskor már elvágódhatott
    # az idézett előzmény kihagyása nem rövidítés: a levél saját szövege teljesen látszik
    quoted = emails.body_coverage(EmailMessage(message_id="d", body="Köszönöm, rendben.\n\nOn Mon, X wrote:\n> régi szöveg\n> még régebbi"))
    assert quoted["status"] == "full" and quoted["quoted_removed"] is True


# --- futásonkénti eredmény -----------------------------------------------------------------------------------


def test_email_result_is_kept_per_run_and_not_overwritten(env):  # noqa: F811
    wp_id, run_id, items = _email_run(env)
    first = {i["item_id"]: store.email_result(work.flow_run_id(run_id, i["item_id"])) for i in items}
    assert all(r and r["intent"] and r["body"]["status"] == "full" for r in first.values())
    ready = work.readiness(wp_id)
    second = work.start_run(wp_id, mode="shadow", expected_assignment_revision=1, input_hash=ready["input_hash"], actor="t",
                            rerun_of=run_id)["run_id"]
    worker.run_worker(once=True)
    for i in items:  # az új futás saját sort kap, a régi megmarad
        assert store.email_result(work.flow_run_id(run_id, i["item_id"])) == first[i["item_id"]]
        assert store.email_result(work.flow_run_id(second, i["item_id"])) is not None
    view = corrections.item_result(run_id, items[0]["item_id"])["email"]
    assert view["result"]["from_this_run"] is True and view["body_coverage"]["status"] == "full"


# --- Levelek adatkészlet ---------------------------------------------------------------------------------------


def test_emails_dataset_and_result_tables(env):  # noqa: F811
    _wp, run_id, _items = _email_run(env)
    assert work_views.result_tables(run_id) == ["emails"]  # levélcsomagnál nincs üres irat-nézet
    cols, rows = datasets.rows("emails", {"run_id": run_id})
    keys = [c.key for c in cols]
    assert {"subject", "sender", "received_at", "intent", "confidence", "next_flow", "attachments", "body_status", "open_reasons"} <= set(keys)
    assert next(c for c in cols if c.key == "confidence").spec()["percent"] is True  # 062: százalékban kiírva
    assert sorted(r["subject"] for r in rows) == ["Kérdés", "Számla 2026/09"]
    assert all(r["intent"] and r["body_status"] == "full" and r["corrected"] is None for r in rows)
    intent_col = next(c for c in cols if c.key == "intent")
    assert intent_col.labels["szamlakuldes"] == "Számlaküldés"


# --- a szándék kézi javítása ---------------------------------------------------------------------------------------


def test_intent_correction_is_versioned_and_reroutes(env):  # noqa: F811
    _wp, run_id, items = _email_run(env)
    item_id = items[0]["item_id"]
    before = corrections.item_result(run_id, item_id)["email"]["result"]
    with pytest.raises(ValueError):
        corrections.save(run_id, item_id, fields={"intent": "nincs_ilyen"}, expected_revision=0, actor="t")
    with pytest.raises(ValueError):
        corrections.save(run_id, item_id, fields={"subject": "más"}, expected_revision=0, actor="t")  # csak a szándék javítható
    corrections.save(run_id, item_id, fields={"intent": "other"}, expected_revision=0, actor="ellenor")
    after = corrections.item_result(run_id, item_id)["email"]["result"]
    assert after["intent"] == "other" and after["corrected"] is True and after["machine_intent"] == before["intent"]
    assert after["next_flow"] == "human:inbox"  # a javított szándék útja (egyéb → kézi feldolgozás)
    rows = {r["item_id"]: r for r in datasets.rows("emails", {"run_id": run_id})[1]}
    assert rows[item_id]["intent"] == "other" and rows[item_id]["corrected"] == "igen"


def test_intent_correction_over_http_closes_only_intent_reasons(env, tmp_path):  # noqa: F811
    _wp, run_id, items = _email_run(env)
    item_id = items[0]["item_id"]
    message_id = work.review_subject(items[0])[1]
    store.review_enqueue(subject_kind="email", subject_id=message_id, run_id=work.flow_run_id(run_id, item_id),
                         reasons=["intent:low_conf:szamlakuldes:0.41", "signal:prompt_injection:0.80"], producer="email_intent")
    c = TestClient(api.create_app(store_path=store.active_path()), base_url="http://127.0.0.1:8930")
    r = c.post(f"/api/runs/{run_id}/items/{item_id}/correction", json={"fields": {"intent": "szamlakuldes"}, "expected_revision": 0},
               headers=HUMAN)
    assert r.status_code == 200, r.text
    left = [x["reason"] for x in store.review_open_reasons("email", message_id)]
    assert left == ["signal:prompt_injection:0.80"]  # a szándék-ok a döntéssel lezárult, a gyanús-tartalom ok nem


# --- K5.2: a PDF-csatolmány a levél csomagjában iratként fut (automatikus lánc) -------------------------------------


def _mail_with_pdf(env) -> dict:  # noqa: F811
    from tests.pdfgen import INVOICE_LINES, write_text_pdf

    pdf = env["inbox"].parent / "bridge" / "data" / "inbox" / "email" / "iroda" / "EID-0003" / "szamla.pdf"
    pdf.parent.mkdir(parents=True)
    write_text_pdf(pdf, INVOICE_LINES)
    return {**MAILS[0], "message_id": "EID-0003", "subject": "Szeptemberi számla csatolva",
            "attachments": [{"filename": "szamla.pdf", "path": "/data/inbox/email/iroda/EID-0003/szamla.pdf"},
                            {"filename": "logo.png", "path": "/data/inbox/email/iroda/EID-0003/logo.png"}]}


def test_pdf_attachment_becomes_a_linked_document_and_runs_with_the_email_recipe(env):  # noqa: F811
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge([_mail_with_pdf(env), MAILS[1]]), inbox_root=env["inbox"])
    wp = work.get(res["workpackage"])
    kinds = sorted(i["kind"] for i in wp["items"])
    assert kinds == ["document", "email", "email"]  # a kép-csatolmány nem kerül be
    doc = next(i for i in wp["items"] if i["kind"] == "document")
    mail = next(i for i in wp["items"] if i["item_id"] == doc["parent_item_id"])
    assert mail["kind"] == "email" and "parent_item_id" not in mail
    ready = work.readiness(wp["id"])
    assert ready["ready"], ready["blockers"]
    assert ready["budget"] == {"jev": Decimal("0.17"), "openai": Decimal("0.10")}  # 2 levél × 0,05 + 1 csatolmány
    work.assign_recipe(wp["id"], "email-intent", params={"arm": "S"}, expected_revision=1, actor="t")
    ready = work.readiness(wp["id"])
    run_id = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=2, input_hash=ready["input_hash"], actor="t")["run_id"]
    info = worker.run_worker(once=True)
    assert info["results"] == {"done": 3}, info
    assert corrections.datapoints_row(run_id, doc["item_id"]) is not None  # a csatolmányon irat-kinyerés futott
    tables = work_views.result_tables(run_id)
    assert tables[:3] == ["emails", "documents", "datapoints"]
    cols, rows = datasets.rows("documents", {"run_id": run_id})
    assert rows[0]["source_email"] == "Szeptemberi számla csatolva"  # a csatolmány eredete
    assert not next(c for c in cols if c.key == "source_email").hidden
    titles = work_views.item_titles(work.get_run(run_id)["input"]["items"])
    assert titles[doc["item_id"]] == "szamla.pdf (a levél csatolmánya: Szeptemberi számla csatolva)"


def test_attachment_detection_inside_the_email_flow_stays_in_the_run(env, monkeypatch):  # noqa: F811
    """065: a levél saját csatolmány-felismerése is a futás azonosítója alatt naplóz és vesz fel teendőt; különben a
    csatolmány teendője „korábbi”-nak látszik (a futás nem számolja), a költsége pedig a futáson kívülre kerül."""
    from jav import policy

    monkeypatch.setattr(policy, "choice_needs_review", lambda *a, **k: True)  # minden ítélet bizonytalan: legyen teendő
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge([_mail_with_pdf(env), MAILS[1]]), inbox_root=env["inbox"])
    wp_id = res["workpackage"]
    work.assign_recipe(wp_id, "email-intent", params={"arm": "S"}, expected_revision=1, actor="t")
    ready = work.readiness(wp_id)
    run_id = work.start_run(wp_id, mode="shadow", expected_assignment_revision=2, input_hash=ready["input_hash"], actor="t")["run_id"]
    worker.run_worker(once=True)
    with store.connect() as c:
        ledger_runs = {r["run_id"] for r in c.execute("SELECT DISTINCT run_id FROM ledger")}
        reason_runs = {r["run_id"] for r in c.execute("SELECT DISTINCT run_id FROM review_reasons WHERE status='open'")}
    assert ledger_runs and all(r.startswith(f"{run_id}:") for r in ledger_runs), ledger_runs
    assert reason_runs and all(r.startswith(f"{run_id}:") for r in reason_runs), reason_runs


def test_attachments_can_be_added_to_an_older_mail_package(env):  # noqa: F811
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge([_mail_with_pdf(env)]), inbox_root=env["inbox"])
    wp_id = res["workpackage"]
    wp = work.get(wp_id)
    doc = next(i for i in wp["items"] if i["kind"] == "document")
    wp = work.remove_item(wp_id, doc["item_id"], expected_revision=wp["revision"])  # mint egy 058 előtti csomag
    assert [p.name for p in mailbox.missing_attachments(wp)] == ["szamla.pdf"]
    wp = mailbox.add_attachments(wp_id, expected_revision=wp["revision"])
    assert mailbox.missing_attachments(wp) == [] and any(i.get("parent_item_id") for i in wp["items"])
    assert mailbox.add_attachments(wp_id, expected_revision=wp["revision"])["revision"] == wp["revision"]  # nincs új: nincs lépés


def test_old_results_do_not_count_bookkeeping_files_as_attachments():
    res = {"intent": "other", "intent_conf": 0.9, "attachments": [{"filename": "receipt.json", "status": "unsupported"},
                                                                 {"filename": "szamla.pdf", "doc_type": "invoice_hu"}]}
    assert [a["filename"] for a in mailbox.effective_email_result(res, None)["attachments"]] == ["szamla.pdf"]


# --- K5.3: feladatjavaslat (a GPT helyett rögzített válasz; a kapu, a mentés és az emberi döntés valódi) -------------------


def _fake_tasks(snap, *, intent_hint, run_id):
    msg = snap["messages"][0]
    if "szerződés" not in msg["body"]:
        return {"messages": [{"message_id": msg["message_id"], "tasks": []}]}
    ok = {"action": "reply", "title": "Válasz a szerződés érkezéséről", "due_date": None, "due_date_evidence": [], "assignee_hint": None,
          "assignee_evidence": [], "evidence": [{"pointer": "/messages/0/body", "quote": "Mikor érkezik a szerződés?"}]}
    invented = {**ok, "title": "Kitalált határidő", "due_date": "2026-10-01",
                "due_date_evidence": [{"pointer": "/messages/0/body", "quote": "Mikor érkezik"}]}
    return {"messages": [{"message_id": msg["message_id"], "tasks": [ok, invented]}]}


def test_task_proposals_go_through_the_gate_and_only_a_human_accepts_them(env, monkeypatch):  # noqa: F811
    from jav import email_tasks

    monkeypatch.setattr(email_tasks, "extract", _fake_tasks)
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge(MAILS), inbox_root=env["inbox"])
    wp_id = res["workpackage"]
    work.assign_recipe(wp_id, "email-intent", params={"tasks": "propose"}, expected_revision=1, actor="t")
    ready = work.readiness(wp_id)
    assert ready["budget"]["openai"] == Decimal("0.012")  # 2 levél × 0,006 USD (a feladatjavaslat kerete)
    run_id = work.start_run(wp_id, mode="shadow", expected_assignment_revision=2, input_hash=ready["input_hash"], actor="t")["run_id"]
    worker.run_worker(once=True)
    by_subject = {corrections.item_result(run_id, i["item_id"])["email"]["subject"]: i for i in work.get_run(run_id)["input"]["items"]}
    items = {"EID-0001": by_subject["Számla 2026/09"], "EID-0002": by_subject["Kérdés"]}
    question = corrections.item_result(run_id, items["EID-0002"]["item_id"])["email"]["tasks"]
    assert [t["title"] for t in question["tasks"]] == ["Válasz a szerződés érkezéséről"]  # a kitalált határidős kiesett
    assert question["rejected"][0]["details"] == ["field_value_not_in_source_quote"]
    assert corrections.item_result(run_id, items["EID-0001"]["item_id"])["email"]["tasks"]["tasks"] == []
    reasons = [r["reason"] for r in work.item_reasons(run_id, items["EID-0002"]["item_id"], items["EID-0002"])["run"]]
    assert "tasks:proposed:1" in reasons  # a javaslat ember döntésére vár
    assert "tasks" in work_views.result_tables(run_id)
    rows = datasets.rows("email_tasks", {"run_id": run_id})[1]
    assert [(r["action"], r["decision"]) for r in rows] == [("reply", None)]

    c = TestClient(api.create_app(store_path=store.active_path()), base_url="http://127.0.0.1:8930")
    url = f"/api/runs/{run_id}/items/{items['EID-0002']['item_id']}/tasks/0/decision"
    assert c.post(url, json={"decision": "accepted"}).status_code == 422  # szerző nélkül nincs döntés
    r = c.post(url, json={"decision": "accepted"}, headers=HUMAN)
    assert r.status_code == 200 and r.json()["email"]["tasks"]["tasks"][0]["decision"]["decision"] == "accepted"
    left = [x["reason"] for x in work.item_reasons(run_id, items["EID-0002"]["item_id"], items["EID-0002"])["run"]]
    assert not any(x.startswith("tasks:") for x in left)  # minden javaslatról döntöttek: a teendő lezárult
    assert c.post(url.replace("/tasks/0/", "/tasks/5/"), json={"decision": "rejected"}, headers=HUMAN).status_code == 404

    # 062 (döntés 2026-09-29): az elfogadott feladat kézzel elvégezve jelölhető és visszavonható; a döntés megmarad
    done_url = url.replace("/decision", "/done")
    assert c.post(done_url, json={"done": True}).status_code == 422  # szerző nélkül nem
    r = c.post(done_url, json={"done": True}, headers=HUMAN)
    assert r.status_code == 200, r.text
    d = r.json()["email"]["tasks"]["tasks"][0]["decision"]
    assert d["decision"] == "accepted" and d["done_by"] == "teszt.elek" and d["done_at"]
    row = datasets.rows("email_tasks", {"run_id": run_id})[1][0]
    assert row["done_by"] == "teszt.elek" and row["done_at"] == d["done_at"]
    day = d["done_at"][:10]
    acts = c.post("/api/datasets/activity/query", json={"scope": {"actor": "teszt.elek", "day": day}}).json()["rows"]
    assert "task_done" in {a["action"] for a in acts}
    undone = c.post(done_url, json={"done": False}, headers=HUMAN).json()["email"]["tasks"]["tasks"][0]["decision"]
    assert undone["decision"] == "accepted" and undone["done_at"] is None and undone["done_by"] is None
    c.post(done_url, json={"done": True}, headers=HUMAN)
    rejected = c.post(url, json={"decision": "rejected"}, headers=HUMAN).json()["email"]["tasks"]["tasks"][0]["decision"]
    assert rejected["done_at"] is None  # az elvetés az elvégzést is törli
    assert c.post(done_url, json={"done": True}, headers=HUMAN).status_code == 409  # elvetett feladat nem végezhető el
    assert c.post(done_url.replace("/tasks/0/", "/tasks/5/"), json={"done": True}, headers=HUMAN).status_code == 404


def test_task_proposal_failure_becomes_a_todo_and_archived_mail_is_skipped(env, monkeypatch):  # noqa: F811
    from jav import email_tasks, policy

    def boom(snap, *, intent_hint, run_id):
        raise RuntimeError("nincs kapcsolat")

    monkeypatch.setattr(email_tasks, "extract", boom)
    monkeypatch.setitem(policy.INTENT_ROUTE, "szamlakuldes", "archive")  # a hamis JEV mindent számlaküldésnek lát
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge(MAILS), inbox_root=env["inbox"])
    wp_id = res["workpackage"]
    work.assign_recipe(wp_id, "email-intent", params={"tasks": "propose"}, expected_revision=1, actor="t")
    ready = work.readiness(wp_id)
    run_id = work.start_run(wp_id, mode="shadow", expected_assignment_revision=2, input_hash=ready["input_hash"], actor="t")["run_id"]
    worker.run_worker(once=True)
    views = [corrections.item_result(run_id, i["item_id"])["email"]["tasks"] for i in work.get_run(run_id)["input"]["items"]]
    assert {v["status"] for v in views} <= {"skipped", "error"}
    for i, v in zip(work.get_run(run_id)["input"]["items"], views):
        reasons = [r["reason"] for r in work.item_reasons(run_id, i["item_id"], i)["run"]]
        if v["status"] == "error":
            assert "tasks:failed:RuntimeError" in reasons
        else:
            assert v["reason"] == "archived_route" and not any(x.startswith("tasks:") for x in reasons)


# --- 066 Á08: a már végállapotba jutott levél-tétel nem fut újra -------------------------------------------------


def test_finished_email_item_is_not_rerun_after_a_crash_before_completion(env, monkeypatch):  # noqa: F811
    """A feldolgozó a levél lezárása után, de a munkasor-bejegyzés lezárása előtt leáll: újraindításkor a mentett
    végállapotot kell visszaadnia. Eddig a levélfolyamatot más partíció alatt kereste, mint ahová az mentett."""
    _wp, run_id, items = _email_run(env)
    run = work.get_run(run_id)
    email_item = next(i for i in items if i["kind"] == "email")
    app_id = work.flow_run_id(run_id, email_item["item_id"])
    monkeypatch.setattr(worker, "_build", lambda *a, **k: (_ for _ in ()).throw(AssertionError("újrafutott")))
    persister = worker.StatePersister(str(worker.persister_path()))
    persister.initialize()
    try:
        state = worker._run_stage({**run["recipe"], "flow": "email"}, run["params"], email_item["source_path"], app_id,
                                  persister, run_id=run_id, job_id=0, after_step=None)
    finally:
        persister.cleanup()
    assert state.get("final_status")
