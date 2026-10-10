"""136 (backlog F-revolut-csv, E4): one account's statement from a bank's tabular export, by code only.

The owner's decisions (DECISIONS 132, 136): a general tabular statement reader without AI, processed as a work package
with one statement per account. The item is the account's statement file (`statement_table.derive`): the statement the
reader built from the export, with the export's name and fingerprint, the account and the reader's own findings.

The graph verifies the file against the run's frozen fingerprint, runs the type pack's checks
(`configs/types/statement_table.json`: running balance, closing balance, totals, period dates) and saves the statement
as the item's document and data points, so the reconciliation reads it like an extracted statement. A failed check, a
missing required field and a line the reader could not read each open a to-do. No model is called: the run costs
nothing.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from burr.core import ApplicationBuilder, action, default, expr
from burr.core.application import Application
from burr.integrations.pydantic import PydanticTypingSystem
from pydantic import BaseModel, Field

from jav import policy, statement_table, store
from jav.typepack import get as get_pack

PARTITION = "statement_table"
TERMINALS = {"done", "needs_review"}
DOC_TYPE = "statement_table"
ARM = "code"


class TableState(BaseModel):
    run_id: str  # the graph's identifier: the ledger, the data points and the to-dos carry it
    item_id: str
    source_path: str
    read_path: str
    expected_sha256: str
    statement: dict[str, Any] = Field(default_factory=dict)
    problems: list[str] = Field(default_factory=list)
    validation: list[dict[str, Any]] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    needs_review: bool = False
    final_status: str | None = None


_INPUTS = ["run_id", "item_id", "source_path", "read_path", "expected_sha256"]


@action.pydantic(reads=_INPUTS, writes=["statement", "problems"])
def load_table(state: TableState) -> TableState:
    """The account's statement file, verified against the frozen fingerprint of the run's input."""
    data = Path(state.read_path).read_bytes()
    if hashlib.sha256(data).hexdigest() != state.expected_sha256:
        raise statement_table.StatementTableError("the statement file differs from the run's frozen input")
    derived = statement_table.load_derived(data)
    state.statement, state.problems = derived["statement"], list(derived["problems"])
    return state


@action.pydantic(reads=["statement", "problems", "item_id"], writes=["validation", "review_reasons", "needs_review"])
def check_table(state: TableState) -> TableState:
    """The type pack's checks on the statement; a failed one, a missing required field and an unreadable line are
    to-dos (the additive latch of `policy.require_review`)."""
    from jav.validators import run_all

    pack = get_pack(DOC_TYPE)
    record, reasons = pack.normalize(state.statement)
    policy.require_review(state, *reasons)
    results = run_all(record, pack.validators, doc_id=state.item_id, doc_type=DOC_TYPE)
    state.validation = [r.model_dump() for r in results]
    for r in results:
        if not r.ok and not r.advisory:
            policy.require_review(state, f"validator:{r.code}")
    values = record.to_datapoints(pack.record_fields)
    for field in pack.required:
        if values.get(field) in (None, "", []) and field != "transactions":
            policy.require_review(state, f"statement_table:missing:{field}")
    if state.problems:
        policy.require_review(state, f"statement_table:unreadable_lines:{len(state.problems)}")
    return state


@action.pydantic(reads=["run_id", "item_id", "source_path", "statement", "validation", "review_reasons", "needs_review"],
                 writes=["final_status"])
def save_table(state: TableState) -> TableState:
    """The statement as the item's document and data points; the to-dos into the review queue."""
    pack = get_pack(DOC_TYPE)
    record, _reasons = pack.normalize(state.statement)
    store.upsert_document(doc_id=state.item_id, source_path=state.source_path, has_text=True, page_count=None,
                          year=None, doc_type=pack.parent or DOC_TYPE, run_id=state.run_id)
    store.insert_datapoints(run_id=state.run_id, doc_id=state.item_id, doc_type=DOC_TYPE, arm=ARM,
                            datapoints=record.to_datapoints(pack.record_fields), field_conf={}, validation=state.validation,
                            route="human" if state.needs_review else "auto", review_reasons=state.review_reasons,
                            final_status="needs_review" if state.needs_review else "done",
                            config_hash=pack.config_hash)
    if state.needs_review:
        store.review_enqueue(subject_kind="document", subject_id=state.item_id, run_id=state.run_id,
                             reasons=state.review_reasons, producer="statement_table", payload={"doc_type": DOC_TYPE})
    state.final_status = "needs_review" if state.needs_review else "done"
    return state


@action.pydantic(reads=[], writes=[])
def done(state: TableState) -> TableState:
    return state


@action.pydantic(reads=[], writes=[])
def needs_review(state: TableState) -> TableState:
    return state


TRANSITIONS = [("load_table", "check_table"), ("check_table", "save_table"),
               ("save_table", "needs_review", expr("final_status == 'needs_review'")), ("save_table", "done", default)]

CONTRACT = {
    "name": "statement_table", "phases": ["read", "check", "save", "terminal"],
    "steps": [("load_table", "read"), ("check_table", "check"), ("save_table", "save"),
              ("done", "terminal"), ("needs_review", "terminal")],
    "edges": [("load_table", "check_table"), ("check_table", "save_table"),
              ("save_table", "needs_review", "To-dos remain"), ("save_table", "done", "Every check passed")],
    "step_meta": {
        "load_table": {"kind": "det", "note": "Verify the account's statement file against the run's frozen fingerprint and load the statement the reader built from the export (jav/statement_table.py)."},
        "check_table": {"kind": "det", "note": "The type pack's checks (running balance, closing balance, totals, period dates); a failed check, a missing required field and a line the reader could not read are to-dos."},
        "save_table": {"kind": "store", "note": "Save the statement as the item's document and data points, so the reconciliation reads it like an extracted statement; the to-dos go into the review queue."},
        "done": {"kind": "terminal", "note": "Every check passed; human approval remains separate."},
        "needs_review": {"kind": "terminal", "note": "A check failed or a line could not be read; the statement is saved with its to-dos."},
    },
    "terminals": sorted(TERMINALS),
    "doc_note": "No model is called. The statement file is derived from a bank's tabular export when a person adds the accounts they chose to a work package (DECISIONS 132, 136).",
}


def build_app(*, run_id: str, item_id: str, source_path: str, read_path: str, expected_sha256: str,
              persister=None, tracker: bool = False) -> Application:
    initial = TableState(run_id=run_id, item_id=item_id, source_path=source_path, read_path=read_path,
                         expected_sha256=expected_sha256)
    builder = (ApplicationBuilder().with_typing(PydanticTypingSystem(TableState))
               .with_actions(load_table, check_table, save_table, done, needs_review)
               .with_transitions(*TRANSITIONS).with_identifiers(app_id=run_id, partition_key=PARTITION if persister else None))
    if persister is not None:
        builder = builder.initialize_from(persister, resume_at_next_action=True, default_state=initial.model_dump(),
                                          default_entrypoint="load_table").with_state_persister(persister)
    else:
        builder = builder.with_state(initial).with_entrypoint("load_table")
    if tracker:
        builder = builder.with_tracker("local", project="jav_statement_table")
    return builder.build()

