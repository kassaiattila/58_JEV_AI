"""Burr contract - offline: the three graphs pass lint, Mermaid / FLOW.md are generated from the contract, and lint
catches errors."""

import copy

from jav import contract, flow, flow_detect, flow_email, flow_learning


def _apps():
    return [
        (flow, flow.build_app("lint.pdf", "lint", "S", tracker=False)),
        (flow_detect, flow_detect.build_app("lint.pdf", tracker=False)),
        (flow_email, flow_email.build_app(source_dir="lint", tracker=False)),
        (flow_learning, flow_learning.build_app()),
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
    mmd2 = contract.overview_mermaid(flow.CONTRACT)
    assert "load_pdf -->|S-kar| find_candidates" in mmd2 and "save -->|route auto| done" in mmd2
