"""Source-bound flexible business facts, kept separate from native reading.

Models may propose arbitrary named fields, entities and relationships. Literal
values must be verified against frozen elements. Semantic support and factual
correctness remain separate; no result is promoted or approved here.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_serializer, model_validator

from jav import fact_checks

from .contracts import ContractModel, Digest, Identifier, Label, SourceElement, Text
from .pipeline import Delivery, digest, json_bytes


class Citation(ContractModel):
    occurrence_id: Identifier
    element_id: Identifier
    quote: Annotated[str, Field(min_length=1, max_length=10_000)]


# The shape of a proposed fact without its presence rule; salvage() checks the
# shape and the rule separately. Subclassing keeps the model's JSON schema
# (and so the answer key of every saved provider response) unchanged.
class FactShape(ContractModel):
    entity: Label
    property: Label
    value: Text | None
    unit: Label | None = None
    role: Label | None = None
    related_entity: Label | None = None
    state: Literal["stated", "missing", "uncertain", "conflicting"]
    citations: tuple[Citation, ...] = Field(max_length=20)

    def presence_issue(self) -> str | None:
        if self.state == "missing":
            return "Missing facts cannot invent a value" if self.value is not None else None
        if self.value is None or not self.citations:
            return "A proposed value needs its source citations"
        return None


class ProposedFact(FactShape):
    @model_validator(mode="after")
    def validate_presence(self):
        issue = self.presence_issue()
        if issue:
            raise ValueError(issue)
        return self


class ProposedExtraction(ContractModel):
    facts: tuple[ProposedFact, ...] = Field(max_length=200)
    gaps: tuple[Label, ...] = Field(default=(), max_length=100)


class DiscardedFact(ContractModel):
    """A received fact left out because it broke the presence rule (123)."""
    entity: Label
    property: Label
    state: Literal["stated", "missing", "uncertain", "conflicting"]
    reason: Label


def salvage(raw: str) -> tuple[ProposedExtraction, tuple[DiscardedFact, ...]] | None:
    """Keep a received answer whose only defect is the presence rule of single facts.

    The valid facts survive and the others are returned for a review item. Any other
    defect (no JSON, a missing key, a wrong type, a bound) returns None: the whole
    answer stays rejected, as before.
    """
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("facts"), list):
        return None
    kept, discarded = [], []
    for item in data["facts"]:
        try:
            shape = FactShape.model_validate_json(json.dumps(item))
        except ValidationError:
            return None
        issue = shape.presence_issue()
        if issue:
            discarded.append(DiscardedFact(entity=shape.entity, property=shape.property, state=shape.state, reason=issue))
        else:
            kept.append(item)
    if not discarded:
        return None
    try:
        proposal = ProposedExtraction.model_validate_json(json.dumps({**data, "facts": kept}))
    except ValidationError:
        return None
    return proposal, tuple(discarded)


class CheckedFact(ContractModel):
    proposal: ProposedFact
    grounding: Literal["literal_match", "rejected", "missing_claim"]
    reasons: tuple[Label, ...] = ()
    # A raw model probability is not a truth label or an approval threshold.
    semantic_support: Annotated[float, Field(ge=0, le=1)] | None = None
    selection_confidence: Annotated[float, Field(ge=0, le=1)] | None = None


class InterpretationCoverage(ContractModel):
    source_elements: Annotated[int, Field(ge=0)]
    submitted_elements: Annotated[int, Field(ge=0)]
    completed_chunks: Annotated[int, Field(ge=1)]
    request_sha256s: tuple[Digest, ...]

    @model_validator(mode="after")
    def complete(self):
        if self.source_elements != self.submitted_elements or self.completed_chunks != len(self.request_sha256s):
            raise ValueError("Successful interpretation coverage must account for every submitted element and chunk")
        return self


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
    coverage: InterpretationCoverage | None = None
    discarded_facts: tuple[DiscardedFact, ...] = ()

    @model_serializer(mode="wrap")
    def preserve_legacy_identity(self, handler):
        data = handler(self)
        if self.coverage is None:
            data.pop("coverage", None)
        if not self.discarded_facts:
            data.pop("discarded_facts", None)
        return data


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
                            "text": text, "hidden": element.hidden,
                            **({"cell": element.cell.model_dump(mode="json")} if element.cell is not None else {})})
    view = {"source_bundle_sha256": delivery.bundle.digest(), "elements": records,
            "reading_gaps": [{"occurrence_id": r.attempt.occurrence_id, "status": r.status,
                              "issues": [i.model_dump(mode="json") for i in r.issues]}
                             for r in delivery.bundle.results if r.status != "complete"],
            "acquisition_status": delivery.bundle.manifest.acquisition_status()}
    if max_bytes is not None and len(json_bytes(view)) > max_bytes:
        raise ValueError("Source view exceeds the explicit transfer bound; no content was sent")
    return view


def citation_text(element: SourceElement, quote: str) -> str | None:
    """Resolve a literal quote without treating a stored formula cache as calculation."""
    if element.text and quote in element.text:
        return element.text
    if element.cell and element.cell.cached_value and quote == element.cell.cached_value.lexical:
        return element.cell.cached_value.lexical
    return None


def ground(delivery: Delivery, proposal: ProposedExtraction, *, provider: str, model: str,
           execution: str, max_bytes=80_000, view: dict | None = None) -> Interpretation:
    if view is None:
        view = source_view(delivery, max_bytes=max_bytes)
    delivery.verify()
    allowed = {(row["occurrence_id"], row["element_id"]) for row in view["elements"]}
    elements = {(r.attempt.occurrence_id, e.element_id): e for r in delivery.bundle.results for e in r.elements
                if (r.attempt.occurrence_id, e.element_id) in allowed}
    facts = []
    for fact in proposal.facts:
        reasons, warnings = [], []
        for cite in fact.citations:
            element = elements.get((cite.occurrence_id, cite.element_id))
            if element is None or citation_text(element, cite.quote) is None:
                reasons.append("Citation does not match its frozen source element")
            elif element.cell and element.cell.formula:
                if element.cell.cached_value and fact.value == element.cell.cached_value.lexical:
                    warnings.append("Saved formula result was not recalculated and may be stale")
                elif fact.value == element.cell.formula:
                    warnings.append("Formula text is not a calculated business value")
        if fact.value is not None and not any(fact.value in cite.quote for cite in fact.citations):
            reasons.append("Proposed literal value is absent from its citations")
        if fact.state != "missing":
            # 120: shared content checks (configs/fact_checks.json); they only add review warnings.
            warnings.extend(filter(None, (fact_checks.placeholder_issue(fact.value),
                                          fact_checks.quantity_issue(fact.value, fact.property, fact.unit))))
        facts.append(CheckedFact(proposal=fact, grounding="rejected" if reasons else
                                  "missing_claim" if fact.state == "missing" else "literal_match",
                                  reasons=tuple(dict.fromkeys(reasons + warnings))))
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
