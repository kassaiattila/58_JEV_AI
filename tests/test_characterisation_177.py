"""177 (plan 170 E5): characterisation of what the shared code asks about an item's kind and a package's source.

Plain-language summary: before the item and source kinds move into one registry, these tests pin what the shared code
does today for each kind of item (a document, an email, a statement read from a bank's table) and each kind of
package source (a folder, a watched folder, files chosen by hand, a mailbox): what is copied when it is added, whose
to-dos an item's to-dos are, how the pre-start overview counts them, which flow reads them, which of them can be read
as a native file or continue into general facts, which get a unified name, and what a package's page shows for its
source. They pass on the code before the registry and must pass, unchanged, after it. Synthetic files only, no calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jav.domains.email import mailbox
from jav.app import naming, work, work_readiness, work_recipes, work_runs, work_views
from jav.documents import native_results
from jav.core import store
from jav.runtime import worker


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield tmp_path


def _file(folder: Path, name: str, body: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(body)
    return p


def _email(root: Path, name: str = "level") -> Path:
    p = _file(root / "inbox" / name, "message.json", b"")
    p.write_text(json.dumps({"subject": "Számla", "sender": "a@b.hu"}, ensure_ascii=False), encoding="utf-8")
    return p


def _mixed(root: Path) -> dict[str, dict]:
    """A package with one item of every kind, and an attachment of the email (a document with a parent)."""
    docs = root / "bejovo"
    pdf = _file(docs, "irat.pdf", b"%PDF-1.4 minta")
    sheet = _file(docs, "tabla.xlsx", b"PK minta tabla")
    table = _file(root / "kivonat", "szamla_1234.csv", b"datum;osszeg\n2026-10-01;100\n")
    mail = _email(root)
    attachment = _file(mail.parent, "csatolmany.pdf", b"%PDF-1.4 csatolmany")
    wp = work.create_with_items(name="vegyes", source_kind="manual", source_ref=None, owner=None,
                                entries=[(pdf, "document"), (sheet, "document"), (table, "statement_table"), (mail, "email")])
    mail_id = next(i["item_id"] for i in wp["items"] if i["kind"] == "email")
    wp = work.add_items(wp["id"], [attachment], kind="document", expected_revision=wp["revision"],
                        parents={attachment: mail_id})
    by_name = {Path(i["source_path"]).name: i for i in wp["items"]}
    return {"wp": wp, "pdf": by_name["irat.pdf"], "sheet": by_name["tabla.xlsx"], "table": by_name["szamla_1234.csv"],
            "mail": by_name["message.json"], "attachment": by_name["csatolmany.pdf"]}


def test_a_document_and_a_table_statement_are_copied_when_added_an_email_is_not(isolated):
    m = _mixed(isolated)
    assert m["pdf"]["instance"] and m["sheet"]["instance"] and m["table"]["instance"] and m["attachment"]["instance"]
    assert m["mail"]["instance"] is None
    assert m["attachment"]["parent_item_id"] == m["mail"]["item_id"]


def test_an_unknown_item_kind_is_refused(isolated):
    wp = work.create_from_files([_file(isolated / "d", "a.pdf", b"%PDF-1.4 a")], name="x")
    with pytest.raises(ValueError, match="unknown item kind: kep"):
        work.add_items(wp["id"], [_file(isolated / "d", "b.png", b"png")], kind="kep", expected_revision=wp["revision"])
    with pytest.raises(ValueError, match="unknown item kind: hang, kep"):
        work.add_entries(wp["id"], [(isolated / "d" / "b.png", "kep"), (isolated / "d" / "a.pdf", "hang")],
                         expected_revision=wp["revision"])


def test_whose_todos_an_items_todos_are(isolated):
    m = _mixed(isolated)
    assert work_runs.review_subject(m["mail"]) == ("email", "level")  # the message's folder name
    for key in ("pdf", "sheet", "table", "attachment"):
        assert work_runs.review_subject(m[key]) == ("document", m[key]["item_id"])


def test_the_pre_start_overview_counts_each_kind(isolated):
    m = _mixed(isolated)
    items = work.get(m["wp"]["id"])["items"]
    plan = work_readiness.run_plan(work_recipes.recipe("processing"), {}, items, [None] * len(items))
    assert plan == {"documents": 3, "emails": 1, "statement_tables": 1, "attachments": 1,
                    "paths": {"S": 0, "G": 0, "unknown": 3}, "tasks_emails": 0, "text_emails": 1, "azure": True,
                    "jev_reuse": True, "arm": "auto", "jev": True}  # 190: text_emails
    assert list(plan) == ["documents", "emails", "statement_tables", "attachments", "paths", "tasks_emails", "text_emails",
                          "azure", "jev_reuse", "arm", "jev"]
    no_table = [i for i in items if i["kind"] != "statement_table"]
    assert "statement_tables" not in work_readiness.run_plan(work_recipes.recipe("processing"), {}, no_table, [None] * len(no_table))
    multi = work_recipes.recipe("multi-format-processing")
    docs = [i for i in items if i["kind"] == "document"]
    plan = work_readiness.run_plan(multi, {}, docs, [None] * len(docs))
    assert plan["native_documents"] == 1
    assert plan["item_flows"] == {m["pdf"]["item_id"]: "document", m["sheet"]["item_id"]: "native",
                                  m["attachment"]["item_id"]: "document"}


def test_the_flow_of_each_kind_and_suffix_routing_only_for_a_document(isolated):
    m = _mixed(isolated)
    processing, multi = work_recipes.recipe("processing"), work_recipes.recipe("multi-format-processing")
    assert [work_readiness.flow_for(processing, m[k]) for k in ("pdf", "sheet", "table", "mail")] == \
        ["document", "document", "statement_table", "email"]
    assert work_readiness.flow_for(multi, m["sheet"]) == "native"
    table_xlsx = {**m["table"], "source_path": str(Path(m["table"]["source_path"]).with_suffix(".xlsx"))}
    assert work_readiness.flow_for(multi, table_xlsx) == multi["flow"]  # a table statement is not routed by its suffix
    assert work_readiness.flow_for(processing, "email") == "email"  # by the kind's name alone


def test_only_a_document_is_read_as_a_native_file(isolated):
    m = _mixed(isolated)
    assert native_results.native_item("run-x", m["sheet"]) is True
    table_xlsx = {**m["table"], "source_path": str(Path(m["table"]["source_path"]).with_suffix(".xlsx"))}
    assert native_results.native_item("run-x", table_xlsx) is False
    assert native_results.native_item("run-x", m["mail"]) is False


def test_only_a_document_continues_into_general_facts(isolated):
    m = _mixed(isolated)
    detected = {"final_status": "done", "text_source": "pdf", "result": {"doc_type": "unknown"}}
    params = {"unknown_documents": "facts", "arm": "S"}
    assert worker.native_fallback(params, m["pdf"], detected) == {**params, "arm": "G", "native_ocr": False}
    table_pdf = {**m["table"], "source_path": str(Path(m["table"]["source_path"]).with_suffix(".pdf"))}
    assert worker.native_fallback(params, table_pdf, detected) is None
    assert worker.native_fallback(params, m["mail"], detected) is None


def test_an_email_gets_no_unified_name(isolated):
    m = _mixed(isolated)
    names = naming.package_item_names(work.get(m["wp"]["id"]))
    assert names[m["mail"]["item_id"]] == naming.NO_NAME
    assert {names[m[k]["item_id"]] for k in ("pdf", "sheet", "table", "attachment")} == {naming.PENDING}


def test_the_titles_of_an_email_and_of_a_document_in_a_subfolder(isolated):
    m = _mixed(isolated)
    titles = work_views.item_titles(work.get(m["wp"]["id"])["items"], str(isolated))
    assert titles[m["pdf"]["item_id"]] == "bejovo/irat.pdf"
    assert titles[m["table"]["item_id"]] == "kivonat/szamla_1234.csv"
    assert titles[m["mail"]["item_id"]] == "Számla — a@b.hu"
    # an attachment is titled by its email, not by its path
    assert titles[m["attachment"]["item_id"]] == "csatolmany.pdf (a levél csatolmánya: Számla)"


@pytest.mark.parametrize(("kind", "root"), [("folder", True), ("watch", True), ("manual", False), ("mailbox", False),
                                            ("upload", False)])
def test_the_folder_a_package_was_read_from(kind, root):
    wp = {"source_kind": kind, "source_ref": "C:/minta"}
    assert work_views.package_root(wp) == ("C:/minta" if root else None)


def test_only_a_mailbox_package_reports_its_missing_attachments(isolated, monkeypatch):
    monkeypatch.setattr(mailbox, "missing_attachments", lambda wp: [Path("a.pdf"), Path("b.pdf")])
    mail = _email(isolated)
    box = work.create_with_items(name="posta", source_kind="mailbox", source_ref="a@b.hu", owner=None,
                                 entries=[(mail, "email")])
    folder = work.create_from_files([_file(isolated / "d", "a.pdf", b"%PDF-1.4 a")], name="mappa")
    assert work_views.workpackage_view(box["id"])["attachments_missing"] == 2
    assert "attachments_missing" not in work_views.workpackage_view(folder["id"])
