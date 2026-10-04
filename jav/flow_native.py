"""Resumable native reading, interpretation, publication and human review graph."""
from __future__ import annotations

from pathlib import Path

from burr.core import ApplicationBuilder, action, default, expr
from burr.core.application import Application
from burr.integrations.pydantic import PydanticTypingSystem
from pydantic import BaseModel, Field

from jav import native_processing, native_results, store
from jav.native_contracts import NativeLimits, NATIVE_SUFFIXES
from jav.readers.pipeline import json_bytes

PARTITION = "native"
TERMINALS = {"done", "needs_review"}


class NativeState(BaseModel):
    work_run_id: str
    item_id: str
    graph_id: str
    source_path: str
    read_path: str
    original_name: str
    expected_sha256: str
    recipe_hash: str
    jev: bool
    use_cache: bool
    limits: dict
    reading_id: str | None = None
    outcome_id: str | None = None
    publication_id: str | None = None
    result_version: str | None = None
    review_reasons: list[str] = Field(default_factory=list)
    final_status: str | None = None


_INPUTS = ["work_run_id", "item_id", "graph_id", "source_path", "read_path", "original_name",
           "expected_sha256", "recipe_hash", "jev", "use_cache", "limits"]


@action.pydantic(reads=_INPUTS, writes=["reading_id"])
def read_native(state: NativeState) -> NativeState:
    publication = native_results.get_publication(state.work_run_id, state.item_id)
    if publication:
        native_results.verify_publication(publication)
        if publication.source_sha256 != state.expected_sha256 or publication.recipe_hash != state.recipe_hash:
            raise native_results.NativeIntegrityError("Graph input differs from the published result")
        state.reading_id = publication.reading_id
    else:
        state.reading_id = native_results.prepare_reading(Path(state.read_path),
            original_name=state.original_name, expected_sha256=state.expected_sha256,
            limits=NativeLimits.model_validate_json(json_bytes(state.limits)).read_limits).reading_id
    return state


@action.pydantic(reads=_INPUTS + ["reading_id"], writes=["outcome_id"])
def interpret_native(state: NativeState) -> NativeState:
    publication = native_results.get_publication(state.work_run_id, state.item_id)
    if publication:
        native_results.verify_publication(publication)
        state.outcome_id = publication.outcome_id
    else:
        state.outcome_id = native_processing.interpret(work_run_id=state.work_run_id, item_id=state.item_id,
            graph_id=state.graph_id, reading_id=state.reading_id, jev=state.jev, use_cache=state.use_cache,
            limits=NativeLimits.model_validate_json(json_bytes(state.limits)))
    return state


@action.pydantic(reads=_INPUTS + ["reading_id", "outcome_id"], writes=["publication_id", "result_version"])
def publish_native(state: NativeState) -> NativeState:
    existing = native_results.get_publication(state.work_run_id, state.item_id)
    if existing:
        native_results.verify_publication(existing)
        publication = existing
    else:
        data, outcome, interpretation = native_results.load_outcome(state.outcome_id)
        if (data["run_id"], data["item_id"], data["reading_id"]) != (state.work_run_id, state.item_id, state.reading_id):
            raise native_results.NativeIntegrityError("Graph outcome belongs to another work item")
        publication = native_results.publish(run_id=state.work_run_id, item_id=state.item_id,
            source_sha256=state.expected_sha256, recipe_hash=state.recipe_hash,
            reading_id=state.reading_id, outcome=outcome, interpretation=interpretation)
    state.publication_id, state.result_version = publication.publication_id, publication.result_version
    return state


@action.pydantic(reads=_INPUTS + ["publication_id", "result_version", "review_reasons"],
                 writes=["review_reasons", "final_status"])
def review_native(state: NativeState) -> NativeState:
    publication = native_results.get_publication(state.work_run_id, state.item_id)
    if publication is None or publication.result_version != state.result_version:
        raise native_results.NativeIntegrityError("Graph publication is missing or changed")
    native_results.verify_publication(publication)
    reasons = list(state.review_reasons)
    if publication.reading.status != "complete":
        reasons.append("native:reading:" + publication.reading.status)
    if publication.interpretation_outcome.status != "succeeded":
        reasons.append("native:interpretation:" + publication.interpretation_outcome.status)
    else:
        interpretation = publication.interpretation
        if not interpretation.facts:
            reasons.append("native:no_facts")
        if interpretation.gaps:
            reasons.append("native:interpretation_gaps")
        for fact in interpretation.facts:
            if fact.grounding != "literal_match":
                reasons.append("native:grounding:" + fact.grounding)
            if fact.proposal.state != "stated":
                reasons.append("native:claim:" + fact.proposal.state)
    state.review_reasons = sorted(set(reasons))
    if state.review_reasons:
        store.review_enqueue(subject_kind="document", subject_id=state.item_id, run_id=state.graph_id,
                             producer="native", reasons=state.review_reasons)
    state.final_status = "needs_review" if state.review_reasons else "done"
    return state


@action.pydantic(reads=[], writes=[])
def done(state: NativeState) -> NativeState:
    return state


@action.pydantic(reads=[], writes=[])
def needs_review(state: NativeState) -> NativeState:
    return state


TRANSITIONS = [("read_native", "interpret_native"), ("interpret_native", "publish_native"),
               ("publish_native", "review_native"), ("review_native", "needs_review", expr("final_status == 'needs_review'")),
               ("review_native", "done", default)]

CONTRACT = {
    "name": "native", "phases": ["read", "interpret", "publish", "review", "terminal"],
    "steps": [("read_native", "read"), ("interpret_native", "interpret"), ("publish_native", "publish"),
              ("review_native", "review"), ("done", "terminal"), ("needs_review", "terminal")],
    "edges": [("read_native", "interpret_native"), ("interpret_native", "publish_native"),
              ("publish_native", "review_native"), ("review_native", "needs_review", "Review reasons remain"),
              ("review_native", "done", "No automatic review reason")],
    "step_meta": {
        "read_native": {"kind": "store", "note": "Verify the frozen source and save the complete bounded native Delivery; OCR is disabled."},
        "interpret_native": {"kind": "llm", "note": "Use the shared GPT receipt and budget boundary, with optional JEV support; persist a terminal outcome reference."},
        "publish_native": {"kind": "store", "note": "Verify saved evidence and publish exactly once for the frozen run item."},
        "review_native": {"kind": "store", "note": "Add reading, interpretation and grounding gaps to the existing review queue."},
        "done": {"kind": "terminal", "note": "A published machine result; human approval remains separate."},
        "needs_review": {"kind": "terminal", "note": "Published evidence and explicit gaps or provider outcomes remain available for review."},
    },
    "terminals": sorted(TERMINALS),
    "doc_note": "Immutable source readings, terminal interpretation outcomes and publications remain separate. Resume uses saved identities, without copying source text into Burr state.",
}


def build_app(*, work_run_id: str, item_id: str, graph_id: str, source_path: str,
              read_path: str, original_name: str, expected_sha256: str, recipe_hash: str,
              jev: bool = True, use_cache: bool = True, requested_arm: str = "G",
              persister=None, tracker: bool = False, limits: NativeLimits | None = None) -> Application:
    """Build the native graph from explicit frozen work identities and limits."""
    if requested_arm not in {"G", "auto"}:
        raise ValueError("Native interpretation requires the G path")
    if Path(original_name).suffix.lower() not in NATIVE_SUFFIXES:
        raise ValueError("Native flow requires a registered native document")
    limits = limits or native_processing.estimate_limits({"jev": "on" if jev else "off", "arm": requested_arm})
    initial = NativeState(work_run_id=work_run_id, item_id=item_id, graph_id=graph_id,
        source_path=source_path, read_path=read_path, original_name=original_name, expected_sha256=expected_sha256,
        recipe_hash=recipe_hash, jev=jev, use_cache=use_cache, limits=limits.model_dump(mode="json"))
    builder = (ApplicationBuilder().with_typing(PydanticTypingSystem(NativeState))
        .with_actions(read_native, interpret_native, publish_native, review_native, done, needs_review)
        .with_transitions(*TRANSITIONS).with_identifiers(app_id=graph_id, partition_key=PARTITION if persister else None))
    if persister is not None:
        builder = builder.initialize_from(persister, resume_at_next_action=True, default_state=initial.model_dump(),
            default_entrypoint="read_native").with_state_persister(persister)
    else:
        builder = builder.with_state(initial).with_entrypoint("read_native")
    if tracker:
        builder = builder.with_tracker("local", project="jav_native")
    return builder.build()
