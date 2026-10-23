"""175 (plan 170 E3): the checks a result goes through, in one registry with stages (`jav/ai/checks.py`).

The record checks the type packs name, the decision's steps, the cross-document checks and the after-save scans are
entries of one registry; a check that reads other documents runs only in a worker run, through one gate. Synthetic
data only; no AI call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jav.app import parties
from jav.ai import checks, validators
from jav.core import cfg
from jav.domains.finance import duplicates
from jav.ai.models import CheckResult, DocumentRecord
from jav.core import calls
from jav.ai.typepack import get as get_pack

PACKS = sorted(p.stem for p in (cfg.path_of("policy").parent / "types").glob("*.json"))


def test_the_stages_and_their_order() -> None:
    assert checks.STAGES == ("record", "decision", "cross_document", "after_save", "saved")
    # 185 (plan G-full-move T1f): the extraction flow's direction rule, as before in every flow
    assert [(c.name, c.reads_store) for c in checks.stage("saved")] == [("detail_direction", False)]
    assert [c.name for c in checks.stage("decision")] == ["pick", "verdict", "gpt_confidence", "validation"]
    assert [c.arms for c in checks.stage("decision")] == [("S",), ("G",), ("G",), ()]
    assert [c.name for c in checks.stage("cross_document")] == ["duplicate", "own_tax", "statement_overlap"]
    assert all(c.reads_store for c in checks.stage("cross_document"))
    scans = checks.stage("after_save")
    assert [(c.name, c.producer, c.opens) for c in scans] == [("duplicate_scan", duplicates.PRODUCER, "duplicate"),
                                                              ("own_tax_scan", parties.SCAN_PRODUCER, "own_tax")]
    assert all(checks.get(c.opens).stage == "cross_document" for c in scans)


@pytest.mark.parametrize("key", PACKS)
def test_every_check_a_type_pack_names_is_a_record_check_of_its_shape(key) -> None:
    for spec in get_pack(key).validators:
        check = checks.get(spec["check"])
        assert check.stage == "record", spec
        if check.kind == "pair":
            assert len(spec["fields"]) == 2, spec
        elif check.kind == "field":
            assert spec.get("field"), spec


def test_an_unknown_check_or_one_of_another_stage_in_a_pack_is_an_error() -> None:
    inv = DocumentRecord()
    with pytest.raises(ValueError, match="unknown check in the type pack: vibes"):
        validators.run_checks(inv, [{"check": "vibes", "field": "currency", "optional": True}])
    with pytest.raises(ValueError, match="unknown check in the type pack: duplicate"):
        validators.run_checks(inv, [{"check": "duplicate"}])
    with pytest.raises(checks.UnknownCheck):
        checks.get("vibes")


def test_an_entry_is_registered_once_with_a_known_stage_and_a_record_check_with_its_kind(monkeypatch) -> None:
    monkeypatch.setattr(checks, "_CHECKS", dict(checks._CHECKS))
    with pytest.raises(ValueError, match="registered twice"):
        checks.register(checks.Check("date_order", "record", lambda *a, **k: None, kind="record"))
    with pytest.raises(ValueError, match="unknown stage"):
        checks.register(checks.Check("later", "someday", lambda *a: None))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="names its kind"):
        checks.register(checks.Check("kindless", "record", lambda *a, **k: None))


def test_a_check_that_reads_the_store_runs_in_a_worker_run_only(monkeypatch) -> None:
    """The one gate: a record check and a cross-document check that read the store are skipped on the command line
    and in a measurement, and run in a worker run."""
    monkeypatch.setattr(checks, "_CHECKS", dict(checks._CHECKS))
    seen: list[str] = []

    def record(inv, spec, **_):
        seen.append("record")
        return CheckResult(name="history", ok=True, code="history.ok")

    checks.register(checks.Check("history", "record", record, kind="record", reads_store=True))
    checks.register(checks.Check("elsewhere", "cross_document", lambda subject: seen.append("cross") or ["x:y"],
                                 reads_store=True))
    subject = checks.Subject("doc-1", "invoice_hu", None)
    assert validators.run_checks(DocumentRecord(), [{"check": "history"}]) == []
    assert checks.cross_document(subject) == []
    with calls.measurement("measure-x", {}):
        assert validators.run_checks(DocumentRecord(), [{"check": "history"}]) == []
        assert checks.cross_document(subject) == []
    assert seen == []
    with calls.use_run(budget_scope="run-x"):
        assert [r.code for r in validators.run_checks(DocumentRecord(), [{"check": "history"}])] == ["history.ok"]
        assert checks.cross_document(subject) == [[], [], [], ["x:y"]]  # the built-in ones: nothing without a record
    assert seen == ["record", "cross"]


def test_the_registry_is_complete_whichever_module_asks_first() -> None:
    """The modules that register the built-in checks are loaded the first time the registry is read."""
    import subprocess
    import sys

    code = ("from jav.ai import checks; print(len(checks.stage('record')), len(checks.stage('decision')),"
            " len(checks.stage('cross_document')), len(checks.stage('after_save')), len(checks.stage('saved')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=Path(__file__).resolve().parents[1]).stdout.split()
    assert out == [str(len(checks.stage(s))) for s in checks.STAGES]
