"""K5.3 (058): a feladatjavaslat kódos kapuja — a régi `email-actions-bare` ellenpéldái (fixtures/synth_evidence_
counterexamples.json) és szabályai mesterséges levélen, GPT-hívás nélkül."""

from jav import email_tasks as et

SNAP = et.snapshot(message_id="m1", subject="Számla 2026-09 — fizetési határidő",
                   body="Kérjük, a mellékelt számlát 2026-09-20-ig egyenlítsék ki. Kapcsolattartó: Minta Anna.\nÜdv, Pénzügy",
                   body_status="full", attachments=[{"filename": "szamla.pdf", "doc_type": "invoice_hu"}])


def _task(**over):
    base = {"action": "review_invoice", "title": "Számla átnézése és kifizetése", "due_date": None, "due_date_evidence": [],
            "assignee_hint": None, "assignee_evidence": [],
            "evidence": [{"pointer": "/messages/0/body", "quote": "a mellékelt számlát 2026-09-20-ig egyenlítsék ki"}]}
    return {**base, **over}


def _gate(*tasks):
    return et.gate(SNAP, {"messages": [{"message_id": "m1", "tasks": list(tasks)}]})


def test_valid_task_with_literal_deadline_and_assignee_is_accepted_as_proposal():
    ok, bad = _gate(_task(due_date="2026-09-20", due_date_evidence=[{"pointer": "/messages/0/body", "quote": "2026-09-20-ig"}],
                          assignee_hint="Minta Anna", assignee_evidence=[{"pointer": "/messages/0/body", "quote": "Kapcsolattartó: Minta Anna"}]))
    assert bad == [] and len(ok) == 1
    assert ok[0]["due_date"] == "2026-09-20" and ok[0]["assignee_hint"] == "Minta Anna" and ok[0]["approval"] == "proposed"


def test_invented_deadline_and_assignee_drop_the_whole_task():
    ok, bad = _gate(_task(due_date="2026-09-21", due_date_evidence=[{"pointer": "/messages/0/body", "quote": "2026-09-20-ig"}]),
                    _task(assignee_hint="Alice", assignee_evidence=[{"pointer": "/messages/0/body", "quote": "Kapcsolattartó: Minta Anna"}]))
    assert ok == [] and [b["details"] for b in bad] == [["field_value_not_in_source_quote"], ["field_value_not_in_source_quote"]]


def test_evidence_must_come_from_this_message_subject_or_body():
    ok, bad = _gate(
        _task(evidence=[{"pointer": "/messages/1/body", "quote": "számlát"}]),               # másik levél
        _task(evidence=[{"pointer": "/intent_proposals/0/intent_key", "quote": "szamla"}]),  # a gép korábbi válasza
        _task(evidence=[{"pointer": "/messages/0/attachments/0/filename", "quote": "szamla.pdf"}]),  # nem tartalom
        _task(evidence=[{"pointer": "/messages/0/body", "quote": "egyenlítsék ki holnap"}]),  # nincs szó szerint ott
        _task(evidence=[]),
    )
    assert ok == []
    assert [b["details"] for b in bad] == [
        ["content_evidence_missing", "evidence_outside_record"], ["content_evidence_missing", "evidence_outside_record"],
        ["content_evidence_missing", "noncontent_evidence"], ["content_evidence_missing", "evidence_quote_mismatch"],
        ["missing_or_unbounded_evidence"]]


def test_noncanonical_deadline_evidence_without_value_and_empty_title():
    snap = et.snapshot(message_id="m1", subject="Határidő", body="Határidő: 2026-9-20", body_status="full", attachments=[])
    ok, bad = et.gate(snap, {"messages": [{"message_id": "m1", "tasks": [
        _task(evidence=[{"pointer": "/messages/0/subject", "quote": "Határidő"}], due_date="2026-9-20",
              due_date_evidence=[{"pointer": "/messages/0/body", "quote": "2026-9-20"}]),
        _task(evidence=[{"pointer": "/messages/0/subject", "quote": "Határidő"}], due_date_evidence=[{"pointer": "/messages/0/body", "quote": "2026-9-20"}]),
        _task(evidence=[{"pointer": "/messages/0/subject", "quote": "Határidő"}], title="  "),
    ]}]})
    assert ok == [] and [b["details"] for b in bad] == [["noncanonical_deadline"], ["evidence_without_field_value"], ["empty_task_title"]]


def test_unknown_or_duplicate_message_rejects_everything():
    assert et.gate(SNAP, {"messages": [{"message_id": "m2", "tasks": [_task()]}]}) == ([], [{"code": "unknown_or_duplicate_tasks_message"}])
    twice = {"messages": [{"message_id": "m1", "tasks": [_task()]}, {"message_id": "m1", "tasks": []}]}
    assert et.gate(SNAP, twice) == ([], [{"code": "unknown_or_duplicate_tasks_message"}])


def test_identical_proposals_of_one_message_are_merged_with_evidence_union():
    """062: a céges postafiókos próbán ugyanaz a kérés a levél saját szövegéből és az idézett előzményéből kétszer jött."""
    ok, bad = _gate(_task(),
                    _task(title="  számla átnézése és  kifizetése. ",
                          evidence=[{"pointer": "/messages/0/body", "quote": "egyenlítsék ki"},
                                    {"pointer": "/messages/0/body", "quote": "a mellékelt számlát 2026-09-20-ig egyenlítsék ki"}]))
    assert bad == [] and len(ok) == 1
    assert ok[0]["title"] == "Számla átnézése és kifizetése" and ok[0]["merged"] == 1
    assert [e["quote"] for e in ok[0]["evidence"]] == ["a mellékelt számlát 2026-09-20-ig egyenlítsék ki", "egyenlítsék ki"]


def test_same_evidence_with_other_wording_is_merged_but_other_action_or_deadline_is_not():
    ok, _ = _gate(_task(), _task(title="A számla kifizetése"))
    assert [t["title"] for t in ok] == ["Számla átnézése és kifizetése"] and ok[0]["merged"] == 1
    deadline = {"due_date": "2026-09-20", "due_date_evidence": [{"pointer": "/messages/0/body", "quote": "2026-09-20-ig"}]}
    ok, _ = _gate(_task(), _task(action="reply"), _task(**deadline))
    assert [(t["action"], t["due_date"], t.get("merged", 0)) for t in ok] == [
        ("review_invoice", None, 0), ("reply", None, 0), ("review_invoice", "2026-09-20", 0)]


def test_rejected_proposal_keeps_its_content_and_names_the_failed_part():
    """062: a kiesett javaslatnál eddig csak az ok maradt meg, így nem látszott, jogos volt-e a kiejtés. A fő bizonyíték
    rendben, csak a felelős idézete kitalált: a hiba a felelős részé, nem a teendőé."""
    ok, bad = _gate(_task(assignee_hint="Anna", assignee_evidence=[{"pointer": "/messages/0/body", "quote": "Kedves Anna!"}]))
    assert ok == [] and len(bad) == 1
    b = bad[0]
    assert b["title"] == "Számla átnézése és kifizetése" and b["assignee_hint"] == "Anna" and b["due_date"] is None
    assert b["failed_parts"] == ["assignee"]
    assert [(q["part"], q["quote"], q["ok"]) for q in b["quotes"]] == [
        ("evidence", "a mellékelt számlát 2026-09-20-ig egyenlítsék ki", True), ("assignee", "Kedves Anna!", False)]
    assert b["details"] == ["content_evidence_missing", "evidence_quote_mismatch", "field_value_not_in_source_quote"]


def test_archived_routes_are_skipped_and_payload_has_catalog_and_hint():
    assert et.skip_reason("archive") == "archived_route" and et.skip_reason("archive:calendar") == "archived_route"
    assert et.skip_reason("human:inbox") is None and et.skip_reason("m2:invoice_hu") is None
    payload = et.request_payload(SNAP, {"intent_key": "szamlakuldes", "confidence": 0.9})
    assert payload["source_catalog"]["records"][0]["field_pointers"] == {"subject": "/messages/0/subject", "body": "/messages/0/body"}
    assert payload["intent_proposals"] == [{"message_id": "m1", "intent_key": "szamlakuldes", "confidence": 0.9}]
    capped = et.snapshot(message_id="m1", subject="", body="x", body_status="capped", attachments=[])
    assert capped["messages"][0]["body_completeness"] == "partial"


def test_no_task_proposal_on_a_suspicious_or_unclassified_message():
    """066 Á28: a feladatjavaslat eddig csak az archiválandó levélen maradt ki; a beszúrt utasításra gyanús levélen (a jel
    igen-sávja, `human:suspicious` út) és szándék-eredmény nélkül is lefutott."""
    assert et.skip_reason("archive") == "archived_route"
    assert et.skip_reason("human:inbox", signals={"prompt_injection": 0.97}) == "suspicious_signal"
    assert et.skip_reason("m2:invoice_hu", has_intent=False) == "no_intent"
    assert et.skip_reason("human:inbox", signals={"prompt_injection": 0.02}) is None
