"""The step kinds of a workflow come from a registry (181, plan 170 L5 = plan 160-E S6).

Guarantees tested: importing registers no step kind, and `load_all` registers every kind of the workflow templates from
the code it belongs to (the documents step by the workflows, the emails step by the email domain, the statements and
reconciliation steps by the finance domain), and nothing more; the registry gives what the old hand-written tables gave (the packages a step takes, its engine, its
repeat source); the workflow's code names no step kind and imports no finance or statement module; a kind registered
twice differently is refused, and an unknown one stops.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import replace

import pytest

from jav.app import registrations, workflow_steps, workflows
from jav.core import cfg
from jav.core.config import PROJECT_ROOT

JAV = PROJECT_ROOT / "jav"


_PROBE = """
import json
import jav.domains.email, jav.domains.finance, jav.domains.email.email_routing, jav.domains.email.mailbox, jav.domains.finance.reconcile_package, jav.domains.finance.statement_package, jav.app.process_runtime
import jav.app.workflows
from jav.app import workflow_steps
before = sorted(workflow_steps._KINDS)
from jav.app import registrations
registrations.load_all()
print(json.dumps({"before": before, "after": [k.kind for k in workflow_steps.kinds()]}))
"""


def test_importing_registers_no_step_kind_and_load_all_registers_each_from_its_owner() -> None:
    out = subprocess.run([sys.executable, "-c", _PROBE], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
                         encoding="utf-8")
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    # finance, workflows, (231 C1c) the process packs' step, email, quotes
    assert seen == {"before": [], "after": ["statements", "documents", "process", "emails", "quote"]}  # 231 C3a-2: reconcile went


def test_every_template_kind_is_registered_and_nothing_more() -> None:
    registrations.load_all()
    kinds = {k.kind: k for k in workflow_steps.kinds()}
    assert set(kinds) == set(cfg.load("workflows")["kinds"])
    assert {k: v.module for k, v in kinds.items()} == {
        "documents": "jav.app.workflows", "emails": "jav.domains.email.mailbox",
        "statements": "jav.domains.finance.statement_package",
        "process": "jav.app.process_runtime", "quote": "jav.domains.quotes.quote_package"}  # 191; 231 C1c: process


def test_a_one_step_templates_id_is_its_kind_or_its_process() -> None:
    """The interface opens a one-step template's own form before the templates have loaded (`ui/src/logic/steps.tsx`);
    231 (C1c): a one-step template of a process pack's case is named by the pack (its form, the general one, waits for
    the templates)."""
    singles = [t for t in cfg.load("workflows")["templates"] if len(t["steps"]) == 1]
    assert singles and all(t["id"] == (t["steps"][0]["pack"] if t["steps"][0]["kind"] == "process" else t["steps"][0]["kind"])
                           for t in singles)


def test_the_registry_gives_what_the_hand_written_tables_gave() -> None:
    registrations.load_all()
    assert {k.kind: k.package_kinds for k in workflow_steps.kinds()} == {
        "documents": ("folder", "manual", "watch", "upload"), "emails": ("mailbox",),
        "statements": ("statements",), "process": ("case",), "quote": ("case",)}  # 231 A3d, C1c; C3a-2: reconcile went
    assert {k.kind for k in workflow_steps.kinds() if k.own_engine} == {"documents", "emails", "statements"}
    assert {k.kind for k in workflow_steps.kinds() if k.paid} == {"documents", "emails", "statements"}
    assert {k.kind for k in workflow_steps.kinds() if k.only_new} == {"documents"}
    assert {k.kind for k in workflow_steps.kinds() if k.poll} == {"emails"}
    assert workflow_steps.of("process").repeat_from("wp-000000000000") == {"kind": "none"}
    assert workflow_steps.of("emails").repeat_from is None
    described = workflow_steps.described()
    assert described["statements"] == {"package_kinds": ["statements"], "paid": True, "own_engine": True,
                                       "only_new": False, "subfolders": False, "needs": ["party", "period"]}
    assert described["documents"]["needs"] == [] and described["emails"]["needs"] == []
    assert {k.kind for k in workflow_steps.kinds() if k.subfolders} == {"documents"}
    view = workflows.templates_view()
    assert "meta" not in view and set(view["kinds"]) == set(described)
    assert view["kinds"]["process"]["sources"] == ["none"] and view["kinds"]["process"]["paid"] is False
    assert "reconcile" not in view["kinds"]  # 231 (C3a-2): retired, read as the reconciliation pack's process step


def _strings_and_imports(path) -> tuple[set[str], set[str]]:
    strings: set[str] = set()
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            strings.add(node.value)
        elif isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names |= {node.module} | {f"{node.module}.{a.name}" for a in node.names}
    return strings, names


def test_the_workflow_code_names_no_step_kind_and_no_finance_module() -> None:
    strings, names = _strings_and_imports(PROJECT_ROOT / "jav/app/workflows.py")
    assert strings & {"emails", "statements", "reconcile"} == set()
    assert names & {"jav.domains.finance.statement_package", "jav.domains.finance.reconcile_package", "jav.domains.finance.reconcile"} == set()


def test_a_kind_registered_twice_differently_is_refused_and_an_unknown_one_stops(monkeypatch) -> None:
    registrations.load_all()
    monkeypatch.setattr(workflow_steps, "_KINDS", dict(workflow_steps._KINDS))
    known = workflow_steps.of("documents")
    workflow_steps.register(known)  # the same again adds nothing
    with pytest.raises(ValueError, match="registered already"):
        workflow_steps.register(replace(known, module="elsewhere"))
    with pytest.raises(workflow_steps.UnknownStepKind):
        workflow_steps.of("quotation")
    with pytest.raises(ValueError, match="no package kind"):
        workflow_steps.StepKind("x", "m", (), start=lambda ctx: None)


def test_a_step_of_an_unregistered_kind_fails_with_the_reason(tmp_path, monkeypatch) -> None:
    """A template naming a kind no module registered: its step fails with the reason instead of starting nothing."""
    registrations.load_all()
    from jav.core import store

    monkeypatch.setattr(workflow_steps, "_KINDS", {k.kind: k for k in workflow_steps.kinds() if k.kind != "documents"})
    with store.use_store(tmp_path / "s.sqlite"):
        folder = tmp_path / "in"
        folder.mkdir()
        (folder / "a.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        wf = {"id": "wf-000000000001", "actor": "tester", "definition": {"steps": []}}
        failed: list[str] = []
        monkeypatch.setattr(workflows, "_set", lambda *a, **kw: True)
        monkeypatch.setattr(workflows, "_steps", lambda wf_id: {"invoices": {"source": {"kind": "folder"}}})
        monkeypatch.setattr(workflows, "_done", lambda wf_, step, actor, action, **f: failed.append(f.get("note", "")))
        workflows._start(wf, {"id": "invoices", "kind": "documents"}, actor="tester")
    assert failed and "unknown workflow step kind 'documents'" in failed[0]


# the service's templates, as the interface's tests read them (`ui/src/views/workflows/workflowTemplates181.fixture.json`)
FIXTURE = PROJECT_ROOT / "ui" / "src" / "views" / "workflows" / "workflowTemplates181.fixture.json"


def write_fixture() -> None:
    """Writes the interface tests' copy of the service's templates (after a change of `configs/workflows.json` or of a
    step kind: `python -c "from tests.test_workflow_steps_181 import write_fixture; write_fixture()"`)."""
    registrations.load_all()
    FIXTURE.write_bytes((json.dumps(workflows.templates_view(), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def test_the_interface_tests_read_the_services_templates() -> None:
    registrations.load_all()
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == workflows.templates_view(), (
        "regenerate: python -c \"from tests.test_workflow_steps_181 import write_fixture; write_fixture()\"")
