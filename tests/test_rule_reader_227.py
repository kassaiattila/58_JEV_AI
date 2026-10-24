"""227 (plan R3b): the decision points' rule files are read through the config loader when a rule is applied.

Plain-language summary: every automatic decision names the rule files it reads (`jav.core.trace`). Until 227 three
modules copied theirs when they were loaded (the shared bands, the email routes, the OCR escalation), so a reloaded
rule file reached the decisions only after a restart, and a preview of a changed rule needed a process of its own.
Now their rule tables are read through the loader whenever a rule is applied. The loader itself does not reread a file
by itself (the service runs from the working folder: a half-edited rule must not reach it); a reload does
(`cfg.reload`). No AI call, no store.
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

from jav.core import cfg, trace
from jav.core.config import PROJECT_ROOT

JAV = PROJECT_ROOT / "jav"

# module-level reads of a decision point's rule file kept on purpose, each with its reason
KEPT = {
    ("jav.ai.policy", "NONE_LABEL"): "the none option's key is part of every S-path request: a change is a new request, "
                                    "like a call site's, measured and released, never applied while running",
    ("jav.documents.ocr", "_CFG"): "the OCR engine's own settings (tesseract, resolution, cache folder, Azure): a change "
                                   "changes the text and its cache key; only `escalation` is a decision rule",
}


def _rule_configs() -> set[str]:
    """The config names of the rule files the registered decision points read (`policy.json` -> `policy`)."""
    from jav.app import registrations

    registrations.load_all()
    names = {f.removesuffix(".json") for p in trace.points() for f in p.files if "*" not in f}
    assert {"policy", "email", "ocr"} <= names
    return names


def _calls_now(node: ast.AST):
    """The calls an expression makes when it is evaluated: not those inside a lambda, which run when it is called."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Lambda):
            continue
        if isinstance(child, ast.Call):
            yield child
        yield from _calls_now(child)


def _module_level_reads(path: Path, names: set[str]) -> list[str]:
    """The module-level assignments whose value loads one of `names` or its fingerprint."""
    found = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for call in [*([node.value] if isinstance(node.value, ast.Call) else []), *_calls_now(node.value)]:
            fn = call.func
            loader = (isinstance(fn, ast.Attribute) and fn.attr in ("load", "config_hash")
                      and isinstance(fn.value, ast.Name) and fn.value.id == "cfg")
            arg = call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else None
            if loader and arg in names:
                found += [t.id for t in targets if isinstance(t, ast.Name)]
    return found


def test_no_module_copies_a_decision_rule_file_when_it_is_loaded():
    names = _rule_configs()
    copies = set()
    for path in JAV.rglob("*.py"):
        module = ".".join(("jav", *path.relative_to(JAV).with_suffix("").parts)).removesuffix(".__init__")
        copies |= {(module, name) for name in _module_level_reads(path, names)}
    assert copies == set(KEPT), "a decision rule file copied at import: read it through `cfg` when the rule applies"


@pytest.fixture
def changed_rules(tmp_path, monkeypatch):
    """A copy of `configs/` with one value changed in each of the three rule files, loaded instead of the real one."""
    root = tmp_path / "configs"
    shutil.copytree(cfg.CONFIG_DIR, root)

    def change(name: str, edit) -> None:
        path = root / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        edit(data)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    for name in ("policy", "email", "ocr"):
        cfg.load(name)  # loaded as a running process holds them
    change("policy", lambda d: d["bands"]["default"].update(choice_human_max_conf=0.75))
    change("email", lambda d: d.update(sent_route="archive:changed"))
    change("ocr", lambda d: d["escalation"].update(enabled=not d["escalation"]["enabled"]))
    monkeypatch.setattr(cfg, "CONFIG_DIR", root)
    monkeypatch.setattr(cfg, "CALLSITE_DIR", root / "callsites")
    monkeypatch.setattr(cfg, "TYPES_DIR", root / "types")
    yield
    monkeypatch.undo()
    cfg.reload()


def test_a_reloaded_rule_file_reaches_the_rules_without_a_restart(changed_rules):
    from jav.ai import policy
    from jav.documents import ocr
    from jav.domains.email import email_rules

    before = (policy.band("invoice.pick")["choice_human_max_conf"], policy.human_max_conf(), policy.config_hash(),
              email_rules.email_sent_route([]), email_rules.config_hash(), ocr.ESCALATION["enabled"])
    assert before[3] != "archive:changed"  # not yet: the loader rereads a file only when asked
    cfg.reload()
    assert policy.band("invoice.pick")["choice_human_max_conf"] == policy.human_max_conf() == 0.75
    assert policy.config_hash() != before[2]
    assert policy.choice_band(0.70, None, "invoice.pick") == "human"  # 0.70 is under the changed threshold now
    assert email_rules.email_sent_route([]) == "archive:changed" and email_rules.config_hash() != before[4]
    assert ocr.ESCALATION["enabled"] is (not before[5])
