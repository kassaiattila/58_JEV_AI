"""Application contracts for immutable native readings and human review.

These types preserve the reader's original proposals and source structure. A
published result, successful interpretation, literal support and human approval
remain separate claims. Importing this module performs no persistence or calls.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from jav.readers.contracts import (
    ContractModel, Digest, Identifier, Issue, Label, Locator, ReadLimits,
    SourceElement, SourceOccurrence, Text, TextLocator,
)
from jav.readers.interpretation import Citation, Interpretation, ProposedFact
from jav.readers.limits import DEFAULT_LIMITS


class DocumentFormat(ContractModel):
    suffix: str
    label: str
    flow: Literal["document", "native"]
    source_view: Literal["pdf", "word", "cells", "text"]


DOCUMENT_FORMATS = (
    DocumentFormat(suffix=".pdf", label="PDF", flow="document", source_view="pdf"),
    DocumentFormat(suffix=".docx", label="Word", flow="native", source_view="word"),
    DocumentFormat(suffix=".xlsx", label="Excel", flow="native", source_view="cells"),
    DocumentFormat(suffix=".txt", label="UTF-8 text", flow="native", source_view="text"),
    DocumentFormat(suffix=".csv", label="UTF-8 comma-separated values", flow="native", source_view="cells"),
)
DOCUMENT_SUFFIXES = tuple(item.suffix for item in DOCUMENT_FORMATS)
NATIVE_SUFFIXES = tuple(item.suffix for item in DOCUMENT_FORMATS if item.flow == "native")
# 120: a document flow item that may continue into the native flow when its type has no fitting type pack
NATIVE_FALLBACK_SUFFIXES = (".pdf",)
NATIVE_CAPABLE_SUFFIXES = NATIVE_SUFFIXES + NATIVE_FALLBACK_SUFFIXES


def format_for(path: str | Path) -> DocumentFormat | None:
    """Return the single shared format registration, without reading the file."""
    suffix = Path(path).suffix.lower()
    return next((item for item in DOCUMENT_FORMATS if item.suffix == suffix), None)


ReadingStatus = Literal["not_attempted", "complete", "partial", "unsupported", "password_required",
                        "corrupt", "resource_limited", "temporary_error", "excluded"]
RecipeHash = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{16}|[0-9a-f]{64})$")]


class ReadingResult(ContractModel):
    occurrence_id: Identifier
    attempt_id: Identifier
    reader_key: Digest
    status: ReadingStatus
    issues: tuple[Issue, ...] = ()


class ReadingSummary(ContractModel):
    status: ReadingStatus = "not_attempted"
    acquisition_status: Literal["not_attempted", "complete", "partial", "unknown"] = "not_attempted"
    attempt_ids: tuple[Identifier, ...] = ()
    results: tuple[ReadingResult, ...] = ()


class ReadingRef(ContractModel):
    reading_id: Identifier
    source_sha256: Digest
    bundle_sha256: Digest
    original_name: Label
    artifact_relpath: str
    attempt_ids: tuple[Identifier, ...]
    reading: ReadingSummary


class ReceiptRef(ContractModel):
    """Resolvable private evidence; public responses never include provider text."""
    kind: Literal["invocation", "saved_cache"] = "invocation"
    receipt_id: Identifier
    invocation_id: int | None = None
    provider: Literal["openai", "jev"]
    run_id: str
    step_id: str
    request_sha256: Digest | None
    response_sha256: Digest | None
    artifact_kind: str | None = None
    artifact_id: str | None = None
    call_status: Literal["reserved", "uncertain", "succeeded", "failed", "cached"]
    cost_known: bool
    cost_usd: Annotated[Decimal, Field(ge=0)] | None
    replayed: bool = False
    reused_from: int | None = None

    @model_validator(mode="after")
    def consistent_receipt(self):
        if self.cost_known != (self.cost_usd is not None):
            raise ValueError("Known cost requires an amount; unknown cost remains null")
        if (self.artifact_kind is None) != (self.artifact_id is None):
            raise ValueError("Receipt artifact kind and identifier must be supplied together")
        if self.kind == "invocation" and (self.invocation_id is None or self.call_status == "cached"):
            raise ValueError("An invocation reference needs its actual call-log identifier and state")
        if self.kind == "saved_cache" and (self.invocation_id is not None or self.call_status != "cached"
                or not self.replayed or self.response_sha256 is None):
            raise ValueError("A saved cache reference must identify an actual reused response")
        return self


class OutcomeBase(ContractModel):
    receipt_refs: tuple[ReceiptRef, ...] = ()
    reason: Label | None = None


class NotStarted(OutcomeBase):
    status: Literal["not_started"] = "not_started"


class Running(OutcomeBase):
    status: Literal["running"] = "running"


class Succeeded(OutcomeBase):
    status: Literal["succeeded"] = "succeeded"


class Rejected(OutcomeBase):
    status: Literal["rejected"] = "rejected"
    reason: Label

    @model_validator(mode="after")
    def received_answer(self):
        if not any(ref.response_sha256 is not None and ref.artifact_id is not None for ref in self.receipt_refs):
            raise ValueError("Rejected interpretation needs a preserved received-answer receipt")
        return self


class Failed(OutcomeBase):
    status: Literal["failed"] = "failed"
    reason: Label


class Uncertain(OutcomeBase):
    status: Literal["uncertain"] = "uncertain"
    reason: Label


InterpretationOutcome = Annotated[NotStarted | Running | Succeeded | Rejected | Failed | Uncertain,
                                 Field(discriminator="status")]


class NativeProgress(ContractModel):
    reading: ReadingSummary = Field(default_factory=ReadingSummary)
    interpretation_outcome: InterpretationOutcome = Field(default_factory=NotStarted)


class Publication(ContractModel):
    run_id: str
    item_id: str
    publication_id: Identifier
    result_version: Digest
    source_sha256: Digest
    recipe_hash: RecipeHash
    reading_id: Identifier
    bundle_sha256: Digest
    reading: ReadingSummary
    outcome_id: Identifier
    outcome_sha256: Digest
    interpretation_outcome: InterpretationOutcome
    interpretation_id: Identifier | None = None
    payload_sha256: Digest | None = None
    interpretation: Interpretation | None = None

    @model_validator(mode="after")
    def terminal_publication(self):
        if self.interpretation_outcome.status in {"not_started", "running"}:
            raise ValueError("An unfinished interpretation cannot be published")
        present = self.interpretation is not None
        if present != (self.interpretation_outcome.status == "succeeded"):
            raise ValueError("Only successful outcomes carry a valid Interpretation")
        if present != (self.interpretation_id is not None) or present != (self.payload_sha256 is not None):
            raise ValueError("Interpretation identity and payload must be present together")
        if present and self.interpretation.source_bundle_sha256 != self.bundle_sha256:
            raise ValueError("Interpretation belongs to another reading")
        return self


class NativeSource(ContractModel):
    reading_id: Identifier
    bundle_sha256: Digest
    publication_id: Identifier
    source_sha256: Digest


class NativeCitation(Citation):
    locator: Locator
    attempt_id: Identifier
    reader_key: Digest
    reading_id: Identifier
    publication_id: Identifier
    result_version: Digest
    source_sha256: Digest
    quote_match_count: Annotated[int, Field(ge=1)]
    quote_span: TextLocator | None = None


class NativeFact(ContractModel):
    fact_id: Identifier
    proposal: ProposedFact
    grounding: Literal["literal_match", "rejected", "missing_claim"]
    reasons: tuple[Label, ...] = ()
    semantic_support: Annotated[float, Field(ge=0, le=1)] | None = None
    selection_confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    effective_value: Text | None
    native_citations: tuple[NativeCitation, ...] = ()
    confirmed: bool = False


class NativeSourceElement(SourceElement):
    occurrence_id: Identifier
    attempt_id: Identifier
    reader_key: Digest


class SourcePage(ContractModel):
    publication_id: Identifier
    reading_id: Identifier
    result_version: Digest
    bundle_sha256: Digest
    source_sha256: Digest
    occurrences: tuple[SourceOccurrence, ...]
    results: tuple[ReadingResult, ...]
    elements: tuple[NativeSourceElement, ...]
    texts: dict[str, str]
    offset: int
    limit: int
    total: int
    has_more: bool
    next_offset: int | None


class ArtifactRef(ContractModel):
    relative_path: str
    byte_size: Annotated[int, Field(ge=0)]
    sha256: Digest


class NativeLimits(ContractModel):
    read_limits: ReadLimits = DEFAULT_LIMITS
    max_transfer_bytes: Annotated[int, Field(gt=0, le=80_000)] = 80_000
    max_output_tokens: Annotated[int, Field(gt=0, le=4000)] = 4000
    provider_limits_usd: dict[Literal["openai", "jev"], Decimal]


class InterpretationView(ContractModel):
    interpretation_id: Identifier
    payload_sha256: Digest
    status: Literal["completed", "empty"]
    provider: str
    model: str
    execution: Literal["live", "saved_response", "synthetic_test"]
    gaps: tuple[str, ...]
    review_status: Literal["not_reviewed"] = "not_reviewed"
    correctness: Literal["not_established"] = "not_established"


class NativeCorrection(ContractModel):
    revision: Annotated[int, Field(ge=0)] = 0
    fields: dict[str, Text | None] = Field(default_factory=dict)
    native_sources: dict[str, tuple[Citation, ...]] = Field(default_factory=dict)
    confirmed: dict[str, Text | None] = Field(default_factory=dict)


class NativeItemResult(ContractModel):
    """Ready means an intact terminal publication exists, including failure outcomes.

    Approval additionally needs successful interpretation and verified evidence;
    neither a finished job nor this readiness flag grants human approval.
    """
    run_id: str
    item_id: str
    kind: Literal["document"] = "document"
    result_kind: Literal["native"] = "native"
    result_version: Digest | None
    review_version: str
    result_ready: bool
    native_source: NativeSource | None
    reading: ReadingSummary
    interpretation_outcome: InterpretationOutcome
    interpretation: InterpretationView | None
    native_facts: tuple[NativeFact, ...] = ()
    correction: NativeCorrection = Field(default_factory=NativeCorrection)
    source_file: dict
    open_reasons: tuple[dict, ...] = ()
    earlier_open_reasons: tuple[dict, ...] = ()

    @model_validator(mode="after")
    def ready_identity(self):
        if self.result_ready != (self.result_version is not None and self.native_source is not None):
            raise ValueError("Ready native results need the complete published source identity")
        if not self.result_ready and (self.result_version is not None or self.native_source is not None or self.native_facts):
            raise ValueError("Unpublished native results have no publication identity or facts")
        if self.interpretation is not None and self.interpretation_outcome.status != "succeeded":
            raise ValueError("An unsuccessful outcome cannot expose an Interpretation")
        return self
