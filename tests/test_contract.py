"""Burr contract - offline: the three graphs pass lint, Mermaid / FLOW.md are generated from the contract, and lint
catches errors."""

import copy

from jav import contract, flow, flow_detect, flow_email, flow_learning, flow_native


def _apps():
    return [
        (flow, flow.build_app("lint.pdf", "lint", "S", tracker=False)),
        (flow_detect, flow_detect.build_app("lint.pdf", tracker=False)),
        (flow_email, flow_email.build_app(source_dir="lint", tracker=False)),
        (flow_learning, flow_learning.build_app()),
        (flow_native, flow_native.build_app(work_run_id="lint-native-run", item_id="0" * 64,
            graph_id="lint-native-graph", source_path="lint.txt", read_path="lint.txt", original_name="lint.txt",
            expected_sha256="0" * 64, recipe_hash="0" * 16, jev=False)),
    ]


def test_all_flows_pass_lint():
    for module, app in _apps():
        result = contract.lint_flow(module.CONTRACT, app, module)
        assert result["passed"], contract.format_report(result)


def test_lint_catches_drift():
    module, app = _apps()[1]
    c = copy.deepcopy(module.CONTRACT)
    c["steps"] = [s for s in c["steps"] if s[0] != "save"]  # a live action is not declared
    c["edges"] = [e for e in c["edges"] if "save" not in e[:2]]
    result = contract.lint_flow(c, app, module)
    assert not result["passed"]
    failed = {name for name, ok, _ in result["checks"] if not ok}
    assert "kontrakt lefedi az élő gráfot" in failed and "élek egyeznek" in failed
    c2 = copy.deepcopy(module.CONTRACT)
    c2["step_meta"]["detect"]["kind"] = "det"  # JEV step disguised as code: no trace needed, but only known kinds pass
    c2["step_meta"]["load_pdf"]["kind"] = "jev"  # a code step disguised as JEV: no adapter trace -> error
    result2 = contract.lint_flow(c2, app, module)
    assert "lépés-fajták és nyomaik" in {name for name, ok, _ in result2["checks"] if not ok}


def test_mermaid_and_md_from_contract(tmp_path):
    c = flow_email.CONTRACT
    mmd = contract.overview_mermaid(c)
    assert mmd.startswith("flowchart TD") and 'subgraph ph_classify["classify"]' in mmd and "intent (jev)" in mmd
    assert "load_message --> classify_attachments" in mmd
    md = contract.flow_md(c)
    assert md.startswith("# FLOW — email_intent") and "**intent** _(jev)_" in md and "```mermaid" in md
    paths = contract.write_artifacts(c, tmp_path)
    assert (tmp_path / "email_intent" / "FLOW.md").exists() and paths["mmd"].endswith("FLOW.mmd")
    assert b"\r" not in (tmp_path / "email_intent" / "FLOW.md").read_bytes()
    assert b"\r" not in (tmp_path / "email_intent" / "FLOW.mmd").read_bytes()
    mmd2 = contract.overview_mermaid(flow.CONTRACT)
    assert "load_pdf -->|S-kar| find_candidates" in mmd2 and "save -->|route auto| done" in mmd2


def test_native_application_wrappers_are_actual_calls_not_comment_markers():
    assert contract._step_trace(
        "def step(state):\n    return native_processing.interpret(work_run_id=state.work_run_id)\n", "llm") == (True, True)
    assert contract._step_trace(
        "def step(state):\n    return native_results.publish(run_id=state.work_run_id)\n", "store") == (True, True)
    assert contract._step_trace(
        'def step(state):\n    # native_processing.interpret(run_id=run_id)\n    return "extract_llm openai run_id"\n',
        "llm") == (False, False)
    assert contract._step_trace(
        'def step(state):\n    # store.save(run_id=run_id)\n    return "native_results.publish"\n',
        "store") == (False, False)
