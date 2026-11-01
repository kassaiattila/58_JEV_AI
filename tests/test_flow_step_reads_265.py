"""265 (R5): a flow step reads only the state it declares; the extraction's failure becomes its to-do again.

A Burr step gets a model with only the fields it declares (`reads`, and its `writes` as optional ones). The log line
added to the extraction's error handler (code review AI-05) named the document id, which that step does not read: the
handler itself raised `AttributeError`, so a failed extraction stopped the flow instead of giving it its
`llm:failed:<error>` to-do (a measurement without an OpenAI budget showed it). The handler names the run now, and a
check reads every step of the flows for an attribute of `state` it does not declare. Synthetic state, no AI call.
"""

from __future__ import annotations

import ast
import inspect

import pytest
from burr.integrations.pydantic import subset_model

from jav.ai import extract_llm
from jav.ai.models import FlowState
from jav.domains.email import flow_email
from jav.domains.finance import flow_statement_table
from jav.flows import flow, flow_detect, flow_native

FLOWS = (flow, flow_detect, flow_native, flow_email, flow_statement_table)


def _declared(decorator: ast.expr, module) -> set[str] | None:
    """The `reads` and `writes` of an `@action.pydantic(...)` decorator (a list, or a module's list and additions,
    evaluated in the module); None for another decorator."""
    if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "pydantic"):
        return None
    names: set[str] = set()
    for kw in decorator.keywords:
        if kw.arg in ("reads", "writes"):
            names |= set(eval(compile(ast.Expression(kw.value), module.__name__, "eval"), vars(module)))
    return names


def _undeclared(module) -> list[str]:
    tree = ast.parse(inspect.getsource(module))
    out = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        declared = next((d for d in (_declared(dec, module) for dec in fn.decorator_list) if d is not None), None)
        if declared is None:
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "state"
                    and node.attr not in declared and not node.attr.startswith("model_")):
                out.append(f"{module.__name__}.{fn.name}: state.{node.attr}")
    return out


@pytest.mark.parametrize("module", FLOWS, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_a_step_reads_only_what_it_declares(module) -> None:
    assert _undeclared(module) == []


def test_a_failed_extraction_is_its_to_do_with_the_steps_own_state(monkeypatch) -> None:
    reads = ["text", "run_id", "doc_type", "needs_review", "review_reasons"]
    writes = ["llm_output", "llm_token_p", "needs_review", "review_reasons"]
    given = subset_model(FlowState, reads, [w for w in writes if w not in reads], "extract_llm_input")

    def failing(*_a, **_k):
        raise RuntimeError("a synthetic failure")

    monkeypatch.setattr(extract_llm, "extract_scored", failing)
    state = flow.extract_llm(given(text="Invoice number: MINTA-1", run_id="run-x", doc_type="invoice_hu",
                                   needs_review=False, review_reasons=[]))
    assert state.llm_output is None and state.needs_review
    assert "llm:failed:RuntimeError" in state.review_reasons
