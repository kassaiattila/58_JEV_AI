"""160 (plan F-csak-gpt, L4): processing without JEV is a guarantee, not a convention.

A flow application built without JEV runs every step inside `adapters.jev.disabled()`. A JEV question asked anyway (a
regression, a new call site that forgot the switch, the native reader's own adapter) is refused before anything
happens: no model probe, no cache read, no call-log reservation. The flows' usual handling turns it into the
`jev_unavailable:disabled` to-do. In the tests the refusal fails the test instead (conftest), so a forgotten JEV
question cannot hide behind a to-do; the tests of the safety net itself are marked `jev_refusal`.
"""

from pathlib import Path

import pytest
from typesafe_sdk import Noul

from jav import flow_detect, store, work, work_readiness, work_recipes, work_runs
from jav.adapters import jev as jev_mod
from jav.adapters.jev import JevUnavailableError
from jav.runtime import calls, worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_runtime_worker import FakeClient

QS = {"q": Noul(instructions="Is the text an invoice?")}


@pytest.fixture()
def env(tmp_path: Path):
    client = FakeClient()
    adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    pdf = tmp_path / "in" / "invoice.pdf"
    pdf.parent.mkdir()
    write_text_pdf(pdf, INVOICE_LINES)
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        yield {"adapter": adapter, "client": client, "pdf": pdf}


def _forgetful_gpt_detect(pdf, path, *, run_id="adhoc"):
    """A regression stand-in: the GPT type recognition asks JEV."""
    jev_mod.get_adapter().ask("detect", {"text": "x"}, QS, run_id=run_id)
    raise AssertionError("the JEV question was answered in processing without JEV")


@pytest.mark.jev_refusal
def test_a_question_without_jev_is_refused_before_the_provider(env):
    with jev_mod.disabled(), pytest.raises(JevUnavailableError) as err:
        env["adapter"].ask("t", {"x": 1}, QS, run_id="r")
    assert err.value.reason == "disabled"
    assert env["client"].calls == 0  # not even the model probe


@pytest.mark.jev_refusal
def test_an_answer_from_the_cache_is_refused_too(env):
    env["adapter"].ask("t", {"x": 1}, QS, run_id="r")  # asked with JEV on: answered and cached
    with jev_mod.disabled(), pytest.raises(JevUnavailableError):
        env["adapter"].ask("t", {"x": 1}, QS, run_id="r")
    assert env["adapter"].ask("t", {"x": 1}, QS, run_id="r").cached  # outside, the cache works as before


@pytest.mark.jev_refusal
def test_an_adapter_built_by_hand_is_refused_too(env, tmp_path):
    """The native reader builds its own adapter; the refusal does not depend on the run's adapter."""
    client = FakeClient()
    own = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "own", model="jev-1.13.0")
    with jev_mod.disabled(), pytest.raises(JevUnavailableError):
        own.ask("t", {"x": 1}, QS, run_id="r")
    assert client.calls == 0


@pytest.mark.jev_refusal
def test_a_flow_without_jev_turns_a_forgotten_question_into_a_to_do(env, monkeypatch):
    monkeypatch.setattr("jav.detect_gpt.detect", _forgetful_gpt_detect)
    state = flow_detect.run_detect(str(env["pdf"]), jev=False)
    assert "jev_unavailable:disabled" in state.review_reasons
    assert env["client"].calls == 0


@pytest.mark.jev_refusal
def test_a_run_without_jev_turns_a_forgotten_question_into_a_to_do(env, monkeypatch):
    monkeypatch.setattr("jav.detect_gpt.detect", _forgetful_gpt_detect)
    wp = work.create_from_folder(env["pdf"].parent, name="Without JEV")
    work_recipes.assign_recipe(wp["id"], "processing", params={"jev": "off", "azure_ocr": "off"}, expected_revision=0, actor="t")
    ready = work_readiness.readiness(wp["id"])
    run_id = work_runs.start_run(wp["id"], mode="shadow", expected_assignment_revision=ready["assignment_revision"],
                            input_hash=ready["input_hash"], actor="t")["run_id"]
    assert worker.run_worker(once=True)["processed"] == 1
    run = work_runs.get_run(run_id)
    reasons = work_runs.items_reasons(run_id, run["input"]["items"])
    assert any(r["reason"] == "jev_unavailable:disabled" for s in reasons.values() for r in s["run"])
    assert env["client"].calls == 0 and "jev" not in calls.budget_usage(run_id)["providers"]


def test_in_the_tests_a_forgotten_question_fails_the_test(env):
    """Without the marker, the conftest guard fails the test at the refusal (caught here to show it)."""
    with jev_mod.disabled(), pytest.raises(pytest.fail.Exception, match="without JEV"):
        env["adapter"].ask("t", {"x": 1}, QS, run_id="r")
