"""160 (plan F-csak-gpt, Sz3): whole runs through the worker, with both engines.

A document package and a downloaded email package each run once with JEV and once with GPT only (the processing
recipe's `jev` setting). Both finish without a failed item; the saved pre-start overview records the engine; the run
calls only the provider its engine names (JEV, or OpenAI), and the cost view expected exactly those. Without JEV no
JEV question can leave (the safety net, and the guard of `tests/conftest.py`). Stand-in models and a fake JEV client,
no paid call.
"""

from __future__ import annotations

import contextlib

import pytest

from jav import costs, work, work_readiness, work_recipes, work_runs
from jav.ai import detect_gpt, extract_llm, gpt_choice
from jav.core import store
from jav.domains.email import mailbox
from jav.ai import jev as jev_mod
from jav.runtime import worker
from jav.core import calls
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_gpt_detect_086 import _by_question, _factory
from tests.test_gpt_intent_089 import _answer
from tests.test_mailbox import MAILS, REQ, FakeBridge, env  # noqa: F401 - pytest fixture
from tests.test_no_jev_085 import GOOD
from tests.test_no_jev_085 import _FakeAgent as _FakeExtractor
from tests.test_paired_recognition_160 import _Jev

ENGINES = ("jev", "gpt")
SETTING = {"jev": "on", "gpt": "off"}


def _models(engine: str, tmp_path, *, noul: float = 0.95):
    """The engine's stand-ins: a fake JEV client, or the GPT type, intent and extraction stand-ins."""
    stack = contextlib.ExitStack()
    if engine == "jev":
        stack.enter_context(jev_mod.use_adapter(jev_mod.JevAdapter(client=_Jev(noul=noul), cache_dir=tmp_path / "cache",
                                                                    model="jev-1.13.0")))
    else:
        stack.enter_context(detect_gpt.use_agent_factory(_by_question))
        stack.enter_context(gpt_choice.use_agent_factory(_by_question))
        stack.enter_context(extract_llm.use_agent_factory(lambda pack: _FakeExtractor(pack, GOOD)))
    return stack


def _start_and_run(wp_id: str) -> str:
    ready = work_readiness.readiness(wp_id)
    run_id = work_runs.start_run(wp_id, mode="shadow", expected_assignment_revision=ready["assignment_revision"],
                            input_hash=ready["input_hash"], actor="t")["run_id"]
    worker.run_worker(once=True)
    return run_id


def _check_engine(run_id: str, engine: str) -> None:
    run = work_runs.get_run(run_id)
    assert all(i["final_status"] in ("done", "needs_review") for i in run["items"]), run["items"]
    assert run["plan"]["jev"] is (engine == "jev")
    provider = "jev" if engine == "jev" else "openai"
    assert {j["provider"] for j in calls.scope_journal(run_id)} | _reused(run_id) == {provider}
    rows = {r["provider"]: r for r in costs.plan_vs_actual(run_id)["providers"]}
    assert rows[provider]["expected"] == "yes" and not any(r["unexpected"] for r in rows.values())
    if engine == "gpt":
        assert "jev" not in rows and not calls.has_budget(run_id, "jev")


def _reused(run_id: str) -> set[str]:
    """The providers that answered from an earlier answer (ledger rows at 0 USD)."""
    with store.connect() as c:
        return {r[0] for r in c.execute("SELECT DISTINCT provider FROM ledger WHERE run_id LIKE ? AND cached=1", (run_id + "%",))}


@pytest.mark.parametrize("engine", ENGINES)
def test_a_document_run_finishes_on_both_engines(tmp_path, engine):
    folder = tmp_path / "in"
    folder.mkdir()
    write_text_pdf(folder / "invoice.pdf", INVOICE_LINES)
    with store.use_store(tmp_path / "w.sqlite"), _models(engine, tmp_path):
        wp = work.create_from_folder(folder, name="Paired")
        work_recipes.assign_recipe(wp["id"], "processing", params={"arm": "auto", "jev": SETTING[engine], "azure_ocr": "off"},
                           expected_revision=0, actor="t")
        _check_engine(_start_and_run(wp["id"]), engine)


@pytest.mark.parametrize("engine", ENGINES)
def test_an_email_run_finishes_on_both_engines(env, tmp_path, engine):  # noqa: F811 - the fixture's name
    res = mailbox.fetch(REQ, actor="t", runner=FakeBridge(MAILS), inbox_root=env["inbox"])
    wp_id = res["workpackage"]
    current = work_recipes.current_assignment(wp_id)
    work_recipes.assign_recipe(wp_id, current["recipe_id"], params={**current["params"], "jev": SETTING[engine]},
                       expected_revision=current["revision"], actor="t")
    gpt = gpt_choice.use_agent_factory(_factory(_answer())) if engine == "gpt" else contextlib.nullcontext()
    with _models(engine, tmp_path, noul=0.05), gpt:
        run_id = _start_and_run(wp_id)
    _check_engine(run_id, engine)
    results = [store.email_result(work_runs.flow_run_id(run_id, i["item_id"])) for i in work_runs.get_run(run_id)["input"]["items"]]
    assert len(results) == len(MAILS) and all(r and r.get("intent") for r in results), results
