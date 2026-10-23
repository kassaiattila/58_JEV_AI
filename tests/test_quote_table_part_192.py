"""192 (plan F-quote-package B6c, the owner's decision of 2026-10-21, DECISIONS 192): a quote request email's Excel or
CSV attachment is read as a part of its request.

A request list often comes as a spreadsheet attached to the email. Like the email's own text (190), it is read in the
email's follow-up, by the quote request's type pack, and put together with the text into one request; it is not an
item of its own, so the folder and mailbox packages, the recipes' file types and the detection stay as they were. The
run reserves the extraction's budget for each table attachment. Synthetic emails and an invented list, a stand-in JEV
and GPT; no paid call.
"""

from __future__ import annotations

from decimal import Decimal

from jav import work, work_readiness, work_recipes, work_runs
from jav.core import store
from jav.domains.quotes import quote_request
from tests import test_email_text_follow_up_190 as follow
from tests.test_email_text_follow_up_190 import _package, _run

env = follow.env  # the 190 fixture: a mailbox package of one quote request email, a stand-in JEV and GPT

CSV = "Megnevezés;Mennyiség;Egység\n24 colos monitor;3;db\nvezeték nélküli egér;3;db\n"


def _with_list(tmp_path, monkeypatch, name: str = "lista.csv") -> None:
    folder = tmp_path / "bridge" / "data" / "inbox" / "email" / "iroda@minta.hu" / "EID-Q1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(CSV, encoding="utf-8")
    mails = [{**follow.MAILS[0], "attachments": [{"path": f"/data/inbox/email/iroda@minta.hu/EID-Q1/{name}", "filename": name}]}]
    monkeypatch.setattr(follow, "MAILS", mails)


def test_a_table_attachment_is_read_as_a_part_of_the_request(env, tmp_path, monkeypatch):
    _with_list(tmp_path, monkeypatch)
    wp_id = _package(env)
    assert [i["kind"] for i in work.get(wp_id)["items"]] == ["email"]  # the list is no item of its own
    run_id, item = _run(wp_id)
    own = work_runs.flow_run_id(run_id, item["item_id"])
    with store.connect() as c:
        stages = [r[0] for r in c.execute("SELECT run_id FROM datapoints WHERE doc_type='quote_request' ORDER BY run_id")]
    assert stages == [f"{own}-invoice", f"{own}-invoice-a1"]
    request = quote_request.read(wp_id, item["item_id"])
    assert [(p.kind, p.name) for p in request.parts] == [("email_text", "Ajanlatkeres monitorra"), ("attachment", "lista.csv")]
    assert request.items_from == 1  # the items of the first attachment that has rows
    # the stand-in GPT answers the text's values for the list too: the list does not support them, a doubt, so a to-do
    # of the email; a gap of the list (no customer in a list) would be only a note
    reasons = work_runs.item_reasons(run_id, item["item_id"], item)["run"]
    assert reasons and {r["producer"] for r in reasons} == {"follow_up:invoice-a1"}
    assert all(r["reason"].startswith("jev:unsupported:") for r in reasons)


def test_the_run_reserves_the_extraction_for_each_table_attachment(env, tmp_path, monkeypatch):
    _with_list(tmp_path, monkeypatch)
    wp_id = _package(env)
    ready = work_readiness.readiness(wp_id)
    a = work_recipes.current_assignment(wp_id)
    recipe = work_recipes.recipe(a["recipe_id"])
    email = work_readiness.item_budget(recipe, a["params"], "email")  # the email's own budget, its text's extraction with it
    assert ready["plan"]["text_tables"] == 1
    assert ready["budget"]["openai"] == email["openai"] + Decimal("0.03")


def test_with_the_setting_off_no_table_is_read(env, tmp_path, monkeypatch):
    _with_list(tmp_path, monkeypatch)
    wp_id = _package(env)
    a = work_recipes.current_assignment(wp_id)
    work_recipes.assign_recipe(wp_id, a["recipe_id"], params={**a["params"], "email_text": "off"}, expected_revision=a["revision"],
                       actor="t")
    assert "text_tables" not in work_readiness.readiness(wp_id)["plan"]
    _run(wp_id)
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM datapoints").fetchone()[0] == 0
