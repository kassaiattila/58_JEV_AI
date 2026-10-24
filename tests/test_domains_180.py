"""Domain modules and the parts they add to the downloads (180, plan 170 E7).

Guarantees tested: importing a domain module registers nothing, and `load_all` registers the finance domain's checks,
logic packs and download parts and the email domain's item rule and page part; the parts agree with the output
contract; the shared download code names no finance module, and without the finance parts the documents table has
only its general columns.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import replace

from jav.app import export, item_kinds, logic_packs, registrations
from jav.ai import checks
from jav.core.config import PROJECT_ROOT
from jav.domains import DOMAINS
from jav.app.outputs import contract, parts

JAV = PROJECT_ROOT / "jav"

_PROBE = """
import json
import jav.domains.email, jav.domains.finance, jav.domains.quotes
from jav.app import item_kinds, logic_packs; from jav.ai import checks
from jav.app.outputs import parts
seen = lambda: {"checks": sorted(checks._CHECKS), "packs": sorted(logic_packs._PACKS), "rules": sorted(item_kinds._RULES),
                "parts": sorted([*parts._MARKS, *parts._COLUMNS, *parts._RESULT, *parts._OWN])}
before = seen()
from jav.app import registrations
registrations.load_all()
print(json.dumps({"before": before, "after": seen()}))
"""


def test_importing_a_domain_registers_nothing_and_load_all_registers_it() -> None:
    out = subprocess.run([sys.executable, "-c", _PROBE], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
                         encoding="utf-8")
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    assert seen["before"] == {"checks": [], "packs": [], "rules": [], "parts": []}
    after = seen["after"]
    assert {"duplicate", "own_tax", "statement_overlap", "duplicate_scan", "own_tax_scan"} <= set(after["checks"])
    assert after["packs"] == ["email_routing", "reconcile", "statements"]  # 181: the routing; 231 (A3d): no quote package
    assert after["rules"] == ["suspicious_email_source"]
    assert after["parts"] == ["direction", "duplicate", "duplicate", "utility_cost", "utility_cost"]


def test_the_domains_and_their_registrations_in_order() -> None:
    registrations.load_all()  # the test session's call (conftest) made it already; a repeat adds nothing
    assert DOMAINS == ("jav.domains.finance", "jav.domains.email", "jav.domains.quotes")  # 191: the quotes
    assert [c.name for c in checks.stage("cross_document")] == ["duplicate", "own_tax", "statement_overlap"]
    assert {c.name: c.run.__module__ for c in checks.stage("after_save")} == {"duplicate_scan": "jav.domains.finance",
                                                                             "own_tax_scan": "jav.domains.finance"}
    assert [p.name for p in parts.record_marks()] == ["duplicate"]
    assert [c.key for p in parts.document_columns() for c in p.columns] == ["duplicate", "duplicate_of", "direction"]
    assert [p.name for p in parts.result_parts()] == ["utility_cost"]
    assert [p.output for p in parts.own_outputs()] == ["utility_cost"]
    assert logic_packs.outputs_of("folder") == ("package_result", "utility_cost")
    assert logic_packs.outputs_of("statements") == ("package_result", "utility_cost")
    assert logic_packs.outputs_of("reconcile") == ("reconcile_statement",)
    assert item_kinds.claimed_by(item_kinds.EMAIL) == "jav.domains.email"  # 229 (MD1): the domain claims its kinds
    assert item_kinds.source_claimed_by("mailbox") == "jav.domains.email"
    assert [(r.name, r.module) for r in item_kinds.rules()] == [("suspicious_email_source", "jav.domains.email")]


def test_the_parts_agree_with_the_output_contract() -> None:
    result = contract.spec("package_result")
    documents = list(result["tables"]["documents"]["columns"])
    added = [c.key for p in parts.document_columns() for c in p.columns]
    start = documents.index("source_email") + 1  # the general columns end with the source email
    assert documents[start:start + len(added)] == added
    assert [c.head for p in parts.document_columns() for c in p.columns] == export.document_head()[start:]
    for part in parts.result_parts():
        for table, heads in part.heads.items():
            assert set(heads) <= set(result["tables"][table]["columns"])
        assert set(part.value_labels) <= set(result["values"])
    for own in parts.own_outputs():
        spec = contract.spec(own.output)
        assert all(set(heads) <= set(spec["tables"][t]["columns"]) for t, heads in own.heads.items())
        assert set(own.value_labels) <= set(spec["values"])


def _imported(path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):  # deferred imports too
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names |= {node.module} | {f"{node.module}.{a.name}" for a in node.names}
    return names


FINANCE = {"jav.domains.finance.duplicates", "jav.domains.finance.own_parties", "jav.domains.finance.report_utility", "jav.core.type_roles", "jav.domains.finance.reconcile", "jav.domains.finance.reconcile_package",
           "jav.domains.finance.statement_package", "jav.domains.finance.statement_months"}


def test_the_shared_download_code_names_no_finance_module() -> None:
    shared = [PROJECT_ROOT / name for name in ("jav/app/export.py", "jav/app/package_release.py", "jav/app/logic_packs.py",
                                               "jav/ai/checks.py")] + sorted((PROJECT_ROOT / "jav/app/outputs").glob("*.py"))
    named = {p.relative_to(JAV).as_posix(): sorted(_imported(p) & FINANCE) for p in shared}
    assert {k: v for k, v in named.items() if v} == {}


def test_without_the_finance_parts_the_documents_table_has_its_general_columns(monkeypatch) -> None:
    record = {"item_id": "x", "file": "x.pdf", "doc_type": "certificate", "arm": "S", "final_status": "auto",
              "open_reasons": [], "fields": {"invoice_number": "A-1"}, "duplicate": {"status": "copy", "other_file": "y.pdf"}}
    head, rows = export.documents_table([record])
    assert head == [*export.DOC_HEAD, "Duplicate", "Duplicate of", "Direction", "invoice_number"]
    assert rows[0][len(export.DOC_HEAD):] == ["copy", "y.pdf", None, "A-1"]
    monkeypatch.setattr(parts, "_COLUMNS", {})
    head, rows = export.documents_table([record])
    assert head == [*export.DOC_HEAD, "invoice_number"]
    assert rows[0][len(export.DOC_HEAD):] == ["A-1"]


def test_a_part_registered_twice_differently_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(parts, "_COLUMNS", dict(parts._COLUMNS))
    known = parts.document_columns()[0]
    parts.register_document_columns(known)  # the same again adds nothing
    try:
        parts.register_document_columns(replace(known, name="other"))
    except ValueError as e:
        assert "a column another part adds already" in str(e)
    else:
        raise AssertionError("a column added twice was accepted")
