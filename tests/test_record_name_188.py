"""188 (plan 185 T3b): the record of a document's data points has a general name (`DocumentRecord`, the flow state's
`record`), and a state saved under the old name (`invoice`) is still read.

The worker saves the flow's state after every step and resumes an interrupted item from the last saved one, reading
back only the keys the state model names. A state saved before the rename keeps its record under `invoice`: it is
read under `record` when it is loaded, so an item interrupted across the upgrade continues with its record. The GPT
schema's name (`InvoiceLLM`) stays, as it is part of the request.

Made-up values only; no call is made.
"""

from __future__ import annotations

from burr.core import State

from jav.flows import flow
from jav.ai.models import DocumentRecord, FlowState
from jav.runtime.worker import StatePersister

RECORD = {"supplier_name": "Example Ltd", "invoice_number": "INV-1", "issue_date": "2026-10-01",
          "due_date": "2026-09-01", "currency": "HUF", "net_total": "100", "vat_total": "27", "gross_total": "127"}


def old_state(app_id: str) -> State:
    """A state as the code before the rename saved it: the record under `invoice`."""
    values = FlowState(doc_type="invoice_hu", source_path="x.pdf", case_id="c", arm="S", run_id=app_id, doc_id="d" * 64).model_dump(mode="json")
    values.pop("record")
    return State({**values, "invoice": RECORD})


def persister(tmp_path) -> StatePersister:
    p = StatePersister(str(tmp_path / "burr_state.sqlite"))
    p.initialize()
    return p


def test_the_record_has_a_general_name():
    assert "record" in FlowState.model_fields and "invoice" not in FlowState.model_fields
    assert FlowState.model_fields["record"].annotation == (DocumentRecord | None)


def test_a_state_saved_under_the_old_name_loads_under_the_new_one(tmp_path):
    p = persister(tmp_path)
    p.save(flow.PARTITION, "app-1", 3, "normalize_picks", old_state("app-1"), "completed")
    loaded = p.load(flow.PARTITION, "app-1")
    assert loaded["state"]["record"] == RECORD and "invoice" not in loaded["state"]
    assert loaded["position"] == "normalize_picks" and loaded["sequence_id"] == 3
    p.cleanup()


def test_another_flows_saved_state_keeps_its_keys(tmp_path):
    p = persister(tmp_path)
    p.save("doc_detect", "app-2", 1, "detect", State({"invoice": "kept", "doc_id": "x"}), "completed")
    assert p.load("doc_detect", "app-2")["state"]["invoice"] == "kept"
    p.cleanup()


def test_a_state_model_still_reads_the_old_name():
    state = FlowState.model_validate({"source_path": "x.pdf", "case_id": "c", "arm": "S", "doc_type": "invoice_hu", "invoice": RECORD})
    assert state.record is not None and state.record.invoice_number == "INV-1"


def test_an_item_interrupted_before_the_rename_resumes_with_its_record(tmp_path):
    p = persister(tmp_path)
    p.save(flow.PARTITION, "app-3", 3, "normalize_picks", old_state("app-3"), "completed")
    app = flow.build_app("x.pdf", "c", "S", tracker=False, doc_type="invoice_hu", run_id="app-3", persister=p)
    action, _, state = app.step()
    assert action.name == "validate"
    assert state.data.record is not None and state.data.record.invoice_number == "INV-1"
    assert {c.name: c.ok for c in state.data.validation}["date_order"] is False  # due before issue: checked on it
    p.cleanup()
