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


# 272 (K5, the rest of the R5 check): the check above reads only a step's own body, and takes a field the step only
# writes as readable. A helper the step hands its state to reads it too, and a field the step does not read holds the
# model's default, not the earlier state, until the step (or the caller before the call) writes it.


def _sides(decorator: ast.expr, module) -> tuple[set[str], set[str]] | None:
    if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "pydantic"):
        return None
    out: dict[str, set[str]] = {"reads": set(), "writes": set()}
    for kw in decorator.keywords:
        if kw.arg in out:
            out[kw.arg] |= set(eval(compile(ast.Expression(kw.value), module.__name__, "eval"), vars(module)))
    return out["reads"], out["writes"]


def _strict(module) -> list[str]:
    tree = ast.parse(inspect.getsource(module))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    found: list[str] = []
    for step in funcs.values():
        sides = next((d for d in (_sides(dec, module) for dec in step.decorator_list) if d is not None), None)
        if sides is None:
            continue
        reads, writes = sides
        seen: set[tuple[str, str]] = set()
        todo = [(step, "state", frozenset(), step.name)]
        while todo:
            fn, var, written_before, path = todo.pop()
            if (fn.name, var) in seen:
                continue
            seen.add((fn.name, var))
            nodes = [n for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                     and n.value.id == var and not n.attr.startswith("model_")]
            stores: dict[str, list[int]] = {}
            for n in nodes:
                if isinstance(n.ctx, ast.Store):
                    stores.setdefault(n.attr, []).append(n.lineno)
            for n in nodes:
                if isinstance(n.ctx, ast.Store) or n.attr in reads:
                    continue
                if n.attr not in writes:
                    found.append(f"{module.__name__}.{path}: state.{n.attr} is not declared")
                elif n.attr not in written_before and not any(line < n.lineno for line in stores.get(n.attr, [])):
                    found.append(f"{module.__name__}.{path}: state.{n.attr} is only written, read before it is")
            for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                         and n.func.id in funcs):
                callee = funcs[call.func.id]
                params = [a.arg for a in callee.args.args]
                before = written_before | {a for a, lines in stores.items() if any(line < call.lineno for line in lines)}
                handed = [params[i] for i, a in enumerate(call.args) if isinstance(a, ast.Name) and a.id == var and i < len(params)]
                handed += [kw.arg for kw in call.keywords if kw.arg and isinstance(kw.value, ast.Name) and kw.value.id == var]
                todo += [(callee, name, frozenset(before), f"{path}->{callee.name}") for name in handed]
    return found


@pytest.mark.parametrize("module", FLOWS, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_a_step_and_the_helpers_it_hands_its_state_read_only_what_it_declares(module) -> None:
    assert _strict(module) == []


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
