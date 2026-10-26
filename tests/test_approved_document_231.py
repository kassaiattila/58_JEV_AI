"""231 (stage D0, D0-c; the reassessment of 2026-10-26, F05, P03): the priced document prints an approved version of the
step it names, through the builder the output's domain registers.

Until D0-c the priced document read the IT quote's own draft. Now it is a shared capability: it reads the version's
number from the step it names (checked against that step's result form), the version as it was approved from the
version store (of that step only), and the output's data from the builder registered for the output; without one it
stops with the reason. Synthetic content and a stand-in builder; no store, no paid call.
"""

from __future__ import annotations

from typing import Any

import pytest

from jav.app import approved_document, capabilities, package_release
from jav.app.outputs import contract, parts
from jav.core import identity
from jav.core.process import kinds
from jav.core.process.definition import ProcessDef, StepDef
from jav.core.process.engine import StepContext


def _ctx(result: Any) -> StepContext:
    compose = StepDef(id="compose", kind="cap.line_draft.v1")
    document = StepDef(id="document", kind="cap.priced_document.v1", gates=("compose",),
                       params={"output": "quote", "from_step": "compose"})
    definition = ProcessDef(id="invented", version="1", title="Invented", steps=(compose, document))
    ctx = StepContext(case_id="wp-00000000d0c2", step=document, definition=definition,
                      data={"container": "wp-00000000d0c2", "name": "Invented offer"}, actor=identity.machine("test"))
    object.__setattr__(ctx, "result_of", lambda step_id: (1, result))
    return ctx


@pytest.fixture()
def printed(monkeypatch):
    seen: list[dict] = []

    def build(content, *, package, version, approved_by, approved_at, output):
        seen.append({"content": content, "package": package, "version": version, "approved_by": approved_by,
                     "output": output})
        return contract.OutputData(output, (contract.Value("premium", "Premium", content["premium"]),), ())

    monkeypatch.setattr(parts, "_VERSIONS", {"quote": parts.VersionDocument("quote", "tests.synthetic", build)})
    monkeypatch.setattr(package_release, "own_version",
                        lambda wp_id, n, c=None, *, step=None: {"content": {"premium": "120000"}, "version": n,
                                                                "approved_by": "anna", "approved_at": "2026-10-26T10:00:00",
                                                                "asked_step": step})
    return seen


def test_the_priced_document_prints_through_the_builder_its_output_registers(printed) -> None:
    outcome = kinds.of("cap.priced_document.v1").run(_ctx({"version": 4}))
    assert outcome == kinds.Done({"output": "quote", "version": 4, "values": 1})
    assert printed == [{"content": {"premium": "120000"}, "package": "Invented offer", "version": 4, "approved_by": "anna",
                        "output": "quote"}]


def test_without_a_builder_for_its_output_it_stops_with_the_reason(printed, monkeypatch) -> None:
    monkeypatch.setattr(parts, "_VERSIONS", {})
    outcome = kinds.of("cap.priced_document.v1").run(_ctx({"version": 4}))
    assert isinstance(outcome, kinds.Fail) and "no domain prints an approved version into the output 'quote'" in outcome.note


def test_a_version_number_that_does_not_fit_stops_it_before_it_prints(printed) -> None:
    outcome = kinds.of("cap.priced_document.v1").run(_ctx({"version": "four"}))
    assert isinstance(outcome, kinds.Fail) and "the result of step 'compose' does not fit" in outcome.note
    assert printed == []


def test_it_is_the_shared_layer_s_and_reads_the_version_of_the_step_it_names() -> None:
    cap = capabilities.of("priced_document@1")
    assert (cap.module, cap.state, cap.output) == ("jav.app.approved_document", "step", approved_document.DocumentResult)
    assert capabilities.step_reads(cap.params, "from_step") == (("version",), None)
    assert parts.version_document("quote").module == "jav.domains.quotes.capabilities"  # the quote registers its own
