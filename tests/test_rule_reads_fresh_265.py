"""265 (code review DOM-01, X-21): a rule file is read when its rule applies, never frozen in a memoised function.

A rule's value may come from the installation's defaults, a case's own values or the case's kept copy of the file
(`cfg.overlay`), and the decision trace records which. A reader memoised with `lru_cache` froze the first value it saw
in the process: a case's value or a default edited later did not apply, while the trace said it did. Here the readers
of the duplicate search, the reconciliation, the statement months and the party checks take a case's value, a rule's
thresholds reach the memoised word comparisons as arguments, and a repository-wide guard keeps any memoised function
from reading a config file except the registries named below with why.
Real rule files, no store; nothing runs and no AI is asked.
"""

from __future__ import annotations

import ast
from pathlib import Path

from jav.core import cfg
from jav.documents import fact_checks
from jav.domains.finance import duplicates, reconcile_rules, reconcile_signals, statement_months

ROOT = Path(__file__).resolve().parents[1]


def _case(values: dict[str, dict[str, object]]) -> cfg.Overlay:
    return cfg.Overlay(values)


def test_the_duplicate_comparison_takes_a_case_s_compared_fields() -> None:
    a = {"issue_date": "2026-10-01", "gross_total": "100", "currency": "HUF"}
    b = {"issue_date": "2026-10-01", "gross_total": "120", "currency": "HUF"}
    assert duplicates.classify(a, b)[0] == "variant"  # the file's fields, read first
    with cfg.overlay(_case({"finance": {"duplicates.compared_fields": ["issue_date"]}})):
        assert duplicates.classify(a, b)[0] == "copy"
        assert duplicates.key_fields()[-1] == "issue_date"
    assert duplicates.classify(a, b)[0] == "variant"


def test_the_reconciliation_rules_take_a_case_s_window() -> None:
    assert reconcile_rules._conf()["window"]["days_after_due"] == 60
    with cfg.overlay(_case({"reconcile": {"window.days_after_due": 5}})):
        assert reconcile_rules._conf()["window"]["days_after_due"] == 5
    assert reconcile_rules._conf()["window"]["days_after_due"] == 60


def test_the_statement_months_take_a_case_s_carry_over() -> None:
    assert statement_months._conf()["carry_over"] == ["booking_date", "amount", "direction"]
    with cfg.overlay(_case({"reconcile": {"replacement.carry_over": ["amount"]}})):
        assert statement_months._conf()["carry_over"] == ["amount"]


def test_the_party_checks_take_a_case_s_ignored_words() -> None:
    assert fact_checks.significant_words("Alfa Kft") == ["alfa"]
    assert reconcile_signals.name_words("Alfa Kft") == ["alfa"]
    with cfg.overlay(_case({"fact_checks": {"parties.ignore_tokens": ["ltd"]}})):
        assert fact_checks.significant_words("Alfa Kft") == ["alfa", "kft"]
        assert reconcile_signals.name_words("Alfa Kft") == ["alfa", "kft"]
    assert fact_checks.significant_words("Alfa Kft") == ["alfa"]


def test_the_fuzzy_name_word_takes_a_case_s_ratio() -> None:
    invoice = {"supplier_name": "Kertesz Muhely Kft", "number": "A-1"}
    payment = {"counterparty_name": "KERTESY MUHELY", "description": ""}
    assert "supplier_name_fuzzy" in reconcile_signals.signals(invoice, {**payment, "counterparty_name": "KERTESY"})
    with cfg.overlay(_case({"reconcile": {"signals.fuzzy_name.min_ratio": 0.99}})):
        assert "supplier_name_fuzzy" not in reconcile_signals.signals(invoice, {**payment, "counterparty_name": "KERTESY"})


def test_a_derived_value_follows_the_rule_file_it_comes_from() -> None:
    first = fact_checks._rules()
    assert fact_checks._rules() is first  # built once while the file stays the same
    with cfg.overlay(_case({"fact_checks": {"parties.ignore_tokens": []}})):
        assert fact_checks._rules() is not first
        assert fact_checks._rules()["parties"]["ignore_tokens"] == []
    again = fact_checks._rules()
    assert again["parties"]["ignore_tokens"] == first["parties"]["ignore_tokens"] != []
    assert fact_checks._rules() is again


# --- the guard ------------------------------------------------------------------------------------------------------

# Memoised functions that may read a config: the registries, call sites, type packs and prompts stay as loaded until a
# reload (`cfg` module docstring, 227); their change is a new AI request, measured and released. Each with why.
ALLOWED = {
    "jav/ai/extract_llm.py:get_agent": "a type pack's extraction agent: its prompt and schema stay as loaded",
    "jav/ai/jev_select.py:site_for": "a call site: its change is a new AI request",
    "jav/ai/jev_verify.py:site_for": "a call site: its change is a new AI request",
    "jav/ai/typepack.py:get": "a type pack: a registry, cleared by `typepack.reload`",
    "jav/ai/typepack.py:_merged_schema": "a type pack's schema files",
    "jav/ai/typepack.py:_model_from_schema": "a type pack's schema files",
    "jav/ai/grounding.py:_country_names": "the country names of the grounding check: a fixed list, no rule",
    "jav/core/todo_kinds.py:kinds": "the to-do kinds: a registry",
    "jav/core/todo_kinds.py:_by_code": "the to-do kinds: a registry",
    "jav/core/applog.py:_secret_pattern": "the data guard's key pattern: cleared on reload",
    "jav/core/cfg.py:_file": "the loader's own cache of the file as loaded",
    "jav/core/cfg.py:_joint_hash": "the loader's own fingerprint cache",
    "jav/app/capabilities.py:_kept": "a case's kept copies, keyed by the case's start and the files' fingerprints",
    "jav/app/outputs/contract.py:_list_columns": "the output contract's column list: a registry",
    "jav/domains/email/email_tasks.py:get_agent": "the email tasks' agent: its prompt stays as loaded",
}

_READS = {"load", "Section", "config_hash", "version", "derived"}  # the `cfg` functions that read a config file


def _memoised(fn: ast.FunctionDef) -> bool:
    for d in fn.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name in {"lru_cache", "cache"}:
            return True
    return False


def _called(fn: ast.FunctionDef) -> set[str]:
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                owner = f.value.id if isinstance(f.value, ast.Name) else ""
                out.add(f"{owner}.{f.attr}" if owner == "cfg" else f.attr)
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


def _functions() -> dict[str, ast.FunctionDef]:
    out = {}
    for path in sorted((ROOT / "jav").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef):
                out[f"{rel}:{node.name}"] = node
    return out


def test_no_memoised_function_reads_a_rule_file() -> None:
    functions = _functions()
    direct = {f"cfg.{r}" for r in _READS}

    def private(key: str) -> bool:  # a module's own reader (`_conf`, `_rules`): a public name is too common to follow
        name = key.split(":")[1]
        return name.startswith("_") and not name.startswith("__")

    # the private functions that read a config file: directly, or through one that does (to a fixed point)
    readers = {key.split(":")[1] for key, fn in functions.items() if private(key) and _called(fn) & direct}
    while True:
        more = {key.split(":")[1] for key, fn in functions.items() if private(key) and _called(fn) & readers} - readers
        if not more:
            break
        readers |= more
    found = sorted(key for key, fn in functions.items()
                   if _memoised(fn) and (_called(fn) & (direct | readers)) and key not in ALLOWED)
    assert found == [], "a memoised function reads a config file; read it when the rule applies (cfg.load, cfg.derived)"


def test_every_allowed_memoised_reader_still_exists() -> None:
    functions = _functions()
    assert [key for key in ALLOWED if key not in functions or not _memoised(functions[key])] == []
