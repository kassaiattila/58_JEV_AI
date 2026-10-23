"""154 (DECISIONS 154): the attachments of an email routed as suspicious are processed but marked.

An email whose text seems to carry an injected instruction goes to a person (`human:suspicious`), yet its attachments
were processed like any other, so a statement attached to it could replace a real one in the reconciliation. Now each
attachment of such an email gets an `attachment:suspicious_email` to-do in the run (whichever of the two is processed
first), so the run cannot be approved before a person has looked at it, and a statement from it never replaces another
by rule: a person decides. An email package registers no own account at approval (only a statement package does, 153).
Synthetic emails, a fake Outlook script and a fake JEV, no paid calls.
"""

from __future__ import annotations

import pytest

from jav.domains.email import mailbox
from jav.app import work, work_readiness, work_recipes, work_runs
from jav.ai import policy
from jav.core import store
from jav.domains.finance import reconcile, statement_months as sm
from jav.runtime import worker
from tests.test_email_results import _mail_with_pdf
from tests.test_mailbox import MAILS, REQ, FakeBridge, env  # noqa: F401 - pytest fixture
from tests.test_statement_months_139 import _ln, _st

REASON = "attachment:suspicious_email"


def _run(env, monkeypatch, *, suspicious: bool) -> tuple[str, dict, dict]:  # noqa: F811 - the fixture's name
    if suspicious:
        monkeypatch.setattr(policy, "email_next_flow", lambda *a, **k: "human:suspicious")
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge([_mail_with_pdf(env), MAILS[1]]), inbox_root=env["inbox"])
    wp_id = res["workpackage"]
    work_recipes.assign_recipe(wp_id, "processing", params={"arm": "S"}, expected_revision=1, actor="t")
    ready = work_readiness.readiness(wp_id)
    run_id = work_runs.start_run(wp_id, mode="apply", expected_assignment_revision=2, input_hash=ready["input_hash"], actor="t")["run_id"]
    worker.run_worker(once=True)
    items = work_runs.get_run(run_id)["input"]["items"]
    doc = next(i for i in items if i["kind"] == "document")
    return run_id, doc, next(i for i in items if i["item_id"] == doc["parent_item_id"])


def _open(run_id: str, item: dict) -> list[str]:
    kind, subject = work_runs.review_subject(item)
    own = work_runs.flow_run_id(run_id, item["item_id"])
    return [r["reason"] for r in store.review_open_reasons(kind, subject) if r.get("run_id") == own]


def test_an_attachment_of_a_suspicious_email_is_processed_and_gets_a_todo(env, monkeypatch):  # noqa: F811
    run_id, doc, mail = _run(env, monkeypatch, suspicious=True)
    from jav.app import corrections

    assert corrections.datapoints_row(run_id, doc["item_id"]) is not None  # still processed
    assert REASON in _open(run_id, doc)
    assert REASON not in _open(run_id, mail)  # the email has its own to-do from the signal route
    with pytest.raises(work.NotReady):
        work_runs.approve_run(run_id, actor="reviewer")


def test_an_attachment_of_an_ordinary_email_gets_no_such_todo(env, monkeypatch):  # noqa: F811
    run_id, doc, _mail = _run(env, monkeypatch, suspicious=False)
    assert REASON not in _open(run_id, doc)


def test_the_order_of_the_email_and_its_attachment_does_not_matter(env, monkeypatch):  # noqa: F811
    run_id, doc, mail = _run(env, monkeypatch, suspicious=True)
    run = work_runs.get_run(run_id)

    def close() -> None:
        kind, subject = work_runs.review_subject(doc)
        store.review_close(subject_kind=kind, subject_id=subject, reason_prefix=REASON,
                           run_id=work_runs.flow_run_id(run_id, doc["item_id"]))
        assert REASON not in _open(run_id, doc)

    close()
    assert mailbox.mark_suspicious_source(run, doc) is True  # the attachment processed after its email
    assert REASON in _open(run_id, doc)
    close()
    assert mailbox.mark_suspicious_source(run, mail) is False  # the email processed after its attachment
    assert REASON in _open(run_id, doc)


def test_a_statement_from_a_suspicious_email_never_replaces_by_rule():
    old = _st("old-ai-000000000000", "2026-01-01", "2026-01-31", doc_type="statement_cib", verified=False,
              lines=[_ln("old-", "2026-01-05", "100.00")])
    new = _st("new-mail-0000000000", "2026-01-01", "2026-01-31", lines=[_ln("new-", "2026-01-05", "100")], seq=2)
    new["suspicious_source"], new["work_run"] = True, "run-000000000042"
    res = sm.resolve([old, new], {}, approved={"run-000000000042"})  # every line kept, even an approved run
    assert res.replaced == {} and res.conflicts == [(new["id"], old["id"])]
    res = sm.resolve([old, new], {sm.pair_key(old["id"], new["id"]): new["id"]})  # a person may still choose it
    assert res.replaced[old["id"]].how == "person"


def test_a_suspicious_reading_read_again_by_a_clean_one_gives_way():
    clean = _st("aaaa-clean-00000000", "2026-01-01", "2026-01-31", seq=1)
    mail = _st("bbbb-mail-000000000", "2026-01-01", "2026-01-31", seq=2,
               lines=[{**ln, "id": ln["id"].replace("aaaa", "bbbb")} for ln in clean["lines"]])
    mail["suspicious_source"] = True
    res = sm.resolve([clean, mail], {})  # the same lines: the clean one stays, though the other was processed later
    assert res.replaced == {mail["id"]: sm.Replacement(mail["id"], clean["id"], "reread")}


def test_the_snapshot_marks_a_statement_from_a_suspicious_email(env, monkeypatch):  # noqa: F811
    from tests import test_reconcile_k2_129 as k2

    k2._run(k2.RUN, ["mailed", "clean"])
    mailed = k2._save("mailed", k2._statement(), run_id=k2.RUN, doc_type="statement_table", validation=k2.VERIFIED)
    clean = k2._save("clean", k2._statement(), run_id=k2.RUN, doc_type="statement_table", validation=k2.VERIFIED)
    store.review_enqueue(subject_kind="document", subject_id=mailed, run_id=work_runs.flow_run_id(k2.RUN, mailed),
                         reasons=[REASON], producer="email_source")
    flags = {s["id"]: s["suspicious_source"] for s in reconcile.statements()}
    assert flags == {mailed: True, clean: False}


def test_an_email_package_registers_no_account_at_approval(env, monkeypatch):  # noqa: F811
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge([_mail_with_pdf(env)]), inbox_root=env["inbox"])
    rule = work.package_rule(res["workpackage"])
    assert rule is None or rule.after_approval is None
