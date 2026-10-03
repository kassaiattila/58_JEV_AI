"""Source-bound flexible business facts, kept separate from native reading.

Models may propose arbitrary named fields, entities and relationships. Literal
values must be verified against frozen elements. Semantic support and factual
correctness remain separate; no result is promoted or approved here.
"""
from __future__ import annotations

from collections import Counter
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import ContractModel, Digest, Identifier, Label, Text
from .pipeline import Delivery, digest, json_bytes


class Citation(ContractModel):
    occurrence_id: Identifier
    element_id: Identifier
    quote: Annotated[str, Field(min_length=1, max_length=10_000)]


class ProposedFact(ContractModel):
    entity: Label
    property: Label
    value: Text | None
    unit: Label | None = None
    role: Label | None = None
    related_entity: Label | None = None
    state: Literal["stated", "missing", "uncertain", "conflicting"]
    citations: tuple[Citation, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_presence(self):
        if self.state == "missing":
            if self.value is not None:
                raise ValueError("Missing facts cannot invent a value")
        elif self.value is None or not self.citations:
            raise ValueError("A proposed value needs its source citations")
        return self


class ProposedExtraction(ContractModel):
    facts: tuple[ProposedFact, ...] = Field(max_length=200)
    gaps: tuple[Label, ...] = Field(default=(), max_length=100)


class CheckedFact(ContractModel):
    proposal: ProposedFact
    grounding: Literal["literal_match", "rejected", "missing_claim"]
    reasons: tuple[Label, ...] = ()
    # A raw model probability is not a truth label or an approval threshold.
    semantic_support: Annotated[float, Field(ge=0, le=1)] | None = None
    selection_confidence: Annotated[float, Field(ge=0, le=1)] | None = None


class Interpretation(ContractModel):
    schema_version: Literal["business-interpretation-0.1"] = "business-interpretation-0.1"
    source_bundle_sha256: Digest
    request_sha256: Digest
    provider: Label
    model: Label
    execution: Literal["saved_response", "live", "synthetic_test"]
    facts: tuple[CheckedFact, ...]
    gaps: tuple[Label, ...]
    review_status: Literal["not_reviewed"] = "not_reviewed"
    correctness: Literal["not_established"] = "not_established"


def source_view(delivery: Delivery, *, max_bytes=80_000) -> dict:
    """No silent truncation: the caller must select or explicitly chunk sources."""
    delivery.verify()
    records = []
    for result in delivery.bundle.results:
        for element in result.elements:
            text = element.text
            if not text:
                continue
            records.append({"occurrence_id": result.attempt.occurrence_id,
                            "source_sha256": result.attempt.source_sha256,
                            "element_id": element.element_id, "parent_id": element.parent_id,
                            "kind": element.kind, "locator": element.locator.model_dump(mode="json"),
                            "text": text, "hidden": element.hidden})
    view = {"source_bundle_sha256": delivery.bundle.digest(), "elements": records,
            "reading_gaps": [{"occurrence_id": r.attempt.occurrence_id, "status": r.status,
                              "issues": [i.model_dump(mode="json") for i in r.issues]}
                             for r in delivery.bundle.results if r.status != "complete"],
            "acquisition_status": delivery.bundle.manifest.acquisition_status()}
    if len(json_bytes(view)) > max_bytes:
        raise ValueError("Source view exceeds the explicit transfer bound; no content was sent")
    return view


def ground(delivery: Delivery, proposal: ProposedExtraction, *, provider: str, model: str,
           execution: str, max_bytes=80_000) -> Interpretation:
    view = source_view(delivery, max_bytes=max_bytes)
    elements = {(row["occurrence_id"], row["element_id"]): row["text"] for row in view["elements"]}
    facts = []
    for fact in proposal.facts:
        reasons = []
        for cite in fact.citations:
            text = elements.get((cite.occurrence_id, cite.element_id))
            if text is None or cite.quote not in text:
                reasons.append("Citation does not match its frozen source element")
        if fact.value is not None and not any(fact.value in cite.quote for cite in fact.citations):
            reasons.append("Proposed literal value is absent from its citations")
        facts.append(CheckedFact(proposal=fact, grounding="rejected" if reasons else
                                  "missing_claim" if fact.state == "missing" else "literal_match", reasons=tuple(reasons)))
    return Interpretation(source_bundle_sha256=delivery.bundle.digest(), request_sha256=digest(json_bytes(view)),
                          provider=provider, model=model, execution=execution, facts=tuple(facts), gaps=proposal.gaps)


def score(result: Interpretation, expected: list[tuple[str, str, str | None]]) -> dict:
    """Compare with independent labels, preserving duplicates and false claims.

    The exact entity/property/value metric intentionally gives no credit merely
    for two models agreeing. Missing labels must never be inferred from a model.
    """
    actual = Counter((f.proposal.entity, f.proposal.property, f.proposal.value)
                     for f in result.facts if f.grounding == "literal_match")
    gold = Counter(expected)
    true = sum((actual & gold).values())
    false = sum((actual - gold).values())
    missed = sum((gold - actual).values())
    return {"true_positive": true, "false_positive": false, "false_negative": missed,
            "precision": true / (true + false) if true + false else None,
            "recall": true / (true + missed) if true + missed else None,
            "grounding_rejected": sum(f.grounding == "rejected" for f in result.facts),
            "correctness_scope": "provided_labels_only", "human_review": "not_reviewed"}
