"""086: the processing setting "without JEV" (backlog item F-jev, step K3). Synthetic documents and stand-in models
only; no paid call.

With JEV switched off a run gets no JEV budget at all, so a stray JEV call could not even reserve: that is the safety
net. Every document runs on the G path (GPT extraction, the code's own source check), its type is recognised by GPT,
and an email gets a to-do instead of an intent.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from jav import detect_gpt, extract_llm, flow_email, store, typepack, work
from jav.adapters import jev as jev_mod
from jav.emails import Attachment, EmailMessage
from jav.runtime import calls, worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_gpt_detect_086 import DETAIL_TOKENS, DETECT_TOKENS, _FakeAgent
from tests.test_no_jev_085 import GOOD
from tests.test_no_jev_085 import _FakeAgent as _FakeExtractor


class _NoJev:
    def ask(self, *a, **k):
        raise AssertionError("JEV was called with JEV switched off")


def _detector(output_model, instructions):
    return _FakeAgent(output_model, DETAIL_TOKENS if "detail_type" in output_model.model_fields else DETECT_TOKENS)


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "a.sqlite"):
        yield tmp_path


def _recipe():
    return work.recipe("processing")


# --- the setting and the budget ---------------------------------------------------------------------------


def test_the_processing_has_a_jev_switch_on_by_default():
    p = _recipe()["params"]["jev"]
    assert p["allowed"] == ["on", "off"] and p["default"] == "on"


def test_without_jev_a_document_has_no_jev_budget_and_an_openai_budget_for_recognition_too():
    r = _recipe()
    on = work.item_budget(r, {"arm": "auto", "azure_ocr": "off"}, "document")
    off = work.item_budget(r, {"arm": "auto", "azure_ocr": "off", "jev": "off"}, "document")
    assert "jev" in on and "jev" not in off
    assert off["openai"] == on["openai"] + Decimal("0.07")  # the two GPT type questions (worst case)


def test_without_jev_an_email_has_no_budget_at_all():
    off = work.item_budget(_recipe(), {"arm": "auto", "jev": "off", "tasks": "off"}, "email")
    assert off == {}


def test_without_jev_a_known_s_type_document_is_planned_on_the_g_path(isolated):
    folder = isolated / "in"
    folder.mkdir()
    write_text_pdf(folder / "szamla.pdf", INVOICE_LINES)
    wp = work.create_from_folder(folder, name="Proba")
    item = wp["items"][0]
    store.upsert_document(doc_id=item["sha256"], source_path=item["source_path"], has_text=True, page_count=1, year=2026,
                          doc_type="invoice_hu", detail_type="invoice_hu", run_id="earlier")  # detected earlier: an S type
    r, params = _recipe(), {"arm": "S", "jev": "off", "azure_ocr": "off"}
    plan = work.run_plan(r, params, wp["items"])
    assert plan["paths"] == {"S": 0, "G": 1, "unknown": 0} and plan["jev"] is False
    budget = work.run_budget(r, params, wp["items"])
    assert "jev" not in budget and budget["openai"] > 0


def test_with_jev_the_plan_says_so(isolated):
    folder = isolated / "in"
    folder.mkdir()
    write_text_pdf(folder / "szamla.pdf", INVOICE_LINES)
    wp = work.create_from_folder(folder, name="Proba")
    assert work.run_plan(_recipe(), {"arm": "auto"}, wp["items"])["jev"] is True


# --- the worker's stages ----------------------------------------------------------------------------------


def test_without_jev_the_extraction_stage_runs_on_the_g_path():
    detect_state = {"final_status": "done", "detail": {"key": "invoice_hu"}}
    assert worker._next_params({"arm": "S", "jev": "off"}, detect_state)["arm"] == "G"
    assert worker._next_params({"arm": "S"}, detect_state)["arm"] == "S"
    assert typepack.get("invoice_hu").arms == ("S", "G")


def test_without_jev_a_whole_document_runs_with_gpt_only(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    write_text_pdf(folder / "szamla.pdf", INVOICE_LINES)
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(_NoJev()), detect_gpt.use_agent_factory(_detector), \
            extract_llm.use_agent_factory(lambda pack: _FakeExtractor(pack, GOOD)):
        wp = work.create_from_folder(folder, name="JEV nelkul")
        work.assign_recipe(wp["id"], "processing", params={"arm": "auto", "jev": "off", "azure_ocr": "off"},
                           expected_revision=0, actor="t")
        r = work.readiness(wp["id"])
        run_id = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")["run_id"]
        assert not calls.has_budget(run_id, "jev") and calls.has_budget(run_id, "openai")
        info = worker.run_worker(once=True)
        run = work.get_run(run_id)
        assert info["results"] == {"done": 1}, run["items"]
        assert run["items"][0]["final_status"] in ("done", "needs_review")
        providers = {j["provider"] for j in calls.scope_journal(run_id)}
        assert providers == {"openai"}
        with store.connect() as c:
            arms = [row[0] for row in c.execute("SELECT arm FROM datapoints WHERE run_id LIKE ?", (run_id + ":%",))]
        assert arms == ["G"]


# --- an email without JEV ---------------------------------------------------------------------------------


def test_without_jev_an_email_gets_a_to_do_instead_of_an_intent(isolated):
    msg = EmailMessage(message_id="m-1", subject="Szamla", body="Mellekelten kuldom a szamlat.",
                       attachments=[Attachment(filename="a.pdf")])
    with jev_mod.use_adapter(_NoJev()):
        app = flow_email.build_app(message=msg, jev=False)
        _, _, state = app.run(halt_after=flow_email.TERMINALS)
    st = state.data
    assert st.result is None and "intent:jev_off" in st.review_reasons
    assert st.next_flow == "human:jev_unavailable"
