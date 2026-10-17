"""160 (plan F-csak-gpt, Sz0): every JEV call site has a counterpart without JEV, or a stated exception, and a test.

`configs/engine_matrix.json` lists each JEV call site with its GPT (or code) counterpart or an exception of an allowed
kind, and the tests that cover it; the preflight checks four rules (`jav/engine_matrix.py`): coverage (every call-site
config and every module that asks JEV is listed), a counterpart or an exception (exactly one, with existing modules),
existing tests, and nothing stale. The rules are checked here on small synthetic trees.
"""

from __future__ import annotations

import json
from pathlib import Path

from jav import engine_matrix

JEV_CALLER = "from jav.adapters.jev import JevAdapter\n\n\ndef ask(jev: JevAdapter):\n    return jev.ask('x', {}, {})\n"
PASSED_ADAPTER = "def ask(adapter):\n    return adapter.ask('x', {}, {})\n"


def _tree(root: Path, modules: dict[str, str], call_sites: tuple[str, ...] = ("a",)) -> Path:
    for rel, text in {**modules, "jav/gpt_a.py": "def ask():\n    return 1\n",
                      "tests/test_a.py": "def test_a():\n    pass\n"}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    (root / "configs" / "callsites").mkdir(parents=True, exist_ok=True)
    for name in call_sites:
        (root / "configs" / "callsites" / f"{name}.json").write_text("{}", encoding="utf-8")
    return root


def _matrix(**site) -> dict:
    entry = {"call_site": "a", "modules": ["jav/a.py"], "gpt": {"module": "jav/gpt_a.py"}, "tests": ["tests/test_a.py::test_a"]}
    entry.update(site)
    return {"exception_kinds": {"skipped": "left out"}, "sites": {"a": {k: v for k, v in entry.items() if v is not None}},
            "routing": {}}


def test_the_real_matrix_has_no_problem():
    assert engine_matrix.problems() == []


def test_a_complete_synthetic_matrix_has_no_problem(tmp_path):
    root = _tree(tmp_path, {"jav/a.py": JEV_CALLER})
    assert engine_matrix.problems(_matrix(), root) == []


def test_a_call_site_config_or_a_module_asking_jev_that_is_not_listed_is_a_problem(tmp_path):
    root = _tree(tmp_path, {"jav/a.py": JEV_CALLER, "jav/b.py": PASSED_ADAPTER}, call_sites=("a", "b"))
    got = engine_matrix.problems(_matrix(), root)
    assert any("call site b" in p for p in got) and any("jav/b.py" in p for p in got)


def test_a_site_needs_exactly_one_counterpart_or_exception_of_an_allowed_kind(tmp_path):
    root = _tree(tmp_path, {"jav/a.py": JEV_CALLER})
    assert any("exactly one" in p for p in engine_matrix.problems(_matrix(gpt=None), root))
    both = _matrix(exception={"kind": "skipped", "reason": "r"})
    assert any("exactly one" in p for p in engine_matrix.problems(both, root))
    odd = _matrix(gpt=None, exception={"kind": "forgotten", "reason": "r"})
    assert any("forgotten" in p for p in engine_matrix.problems(odd, root))
    silent = _matrix(gpt=None, exception={"kind": "skipped", "reason": ""})
    assert any("reason" in p for p in engine_matrix.problems(silent, root))
    assert engine_matrix.problems(_matrix(gpt=None, exception={"kind": "skipped", "reason": "r"}), root) == []


def test_a_missing_test_or_counterpart_is_a_problem(tmp_path):
    root = _tree(tmp_path, {"jav/a.py": JEV_CALLER})
    assert any("test_gone" in p for p in engine_matrix.problems(_matrix(tests=["tests/test_a.py::test_gone"]), root))
    assert any("tests" in p for p in engine_matrix.problems(_matrix(tests=[]), root))
    assert any("jav/gpt_b.py" in p for p in engine_matrix.problems(_matrix(gpt={"module": "jav/gpt_b.py"}), root))


def test_a_stale_entry_is_a_problem(tmp_path):
    root = _tree(tmp_path, {"jav/a.py": JEV_CALLER})
    stale = _matrix()
    stale["sites"]["old"] = {"call_site": "old", "modules": ["jav/old.py"], "gpt": {"module": "jav/gpt_a.py"},
                             "tests": ["tests/test_a.py::test_a"]}
    stale["routing"]["jav/quiet.py"] = "no longer asks JEV"
    (root / "jav" / "quiet.py").write_text("x = 1\n", encoding="utf-8")
    got = engine_matrix.problems(stale, root)
    assert any("call site old" in p for p in got) and any("jav/old.py" in p for p in got)
    assert any("jav/quiet.py" in p for p in got)


def test_the_matrix_file_is_a_versioned_config():
    data = json.loads((engine_matrix.MATRIX_PATH).read_text(encoding="utf-8"))
    assert data["meta"]["name"] == "engine_matrix" and data["meta"]["version"]
