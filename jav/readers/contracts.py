"""Bounded source contracts, independent of persistence and provider runtimes.

The parser/result separation and explicit immutable evidence follow the legacy
provider and evidence patterns. See NOTICE.md in this package for provenance.
This module performs no file access, parsing, network calls or approval changes.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "source-contract-0.1"
MAX_CONTRACT_BYTES = 2_000_000
MAX_CONTRACT_DEPTH = 24
MAX_CONTRACT_NODES = 50_000

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Label = Annotated[str, Field(min_length=1, max_length=512)]
Text = Annotated[str, Field(max_length=100_000)]


class ContractError(ValueError):
    """External source-contract data exceeded a bound or was not valid JSON."""


class ContractModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False, strict=True)

    def digest(self) -> str:
        """Return a digest of this exact validated version, without doing I/O."""
        return hashlib.sha256(canonical_bytes(self)).hexdigest()


def canonical_bytes(value: ContractModel) -> bytes:
    """Use UTF-8 JSON without lossy value normalisation."""
    return json.dumps(value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


class Issue(ContractModel):
    stage: Literal["acquisition", "reading", "interpretation"]
    code: Literal[
        "download_missing", "download_truncated", "inventory_unknown", "unsupported",
        "password_required", "corrupt", "resource_limit", "temporary_error", "excluded",
        "needs_ocr", "formula_cache_missing", "unread_content", "protection_unavailable",
    ]
    message: Label
    element_id: Identifier | None = None


class SourceObject(ContractModel):
    sha256: Digest
    byte_size: Annotated[int, Field(ge=0)]
    detected_mime: Label

    def storage_key(self) -> str:
        """A proposed content address, not an existing store path."""
        return f"sha256/{self.sha256}"


class SourceOccurrence(ContractModel):
    occurrence_id: Identifier
    parent_id: Identifier | None = None
    source_version: Identifier
    original_name: Label
    role: Literal["document", "email", "attachment", "inline", "embedded", "archive_member"]
    acquisition: Literal["received", "missing", "truncated", "excluded"]
    object_sha256: Digest | None = None
    issues: tuple[Issue, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_acquisition(self) -> Self:
        if self.acquisition in ("received", "truncated") and self.object_sha256 is None:
            raise ValueError("Received bytes need a source object")
        if self.acquisition == "missing" and self.object_sha256 is not None:
            raise ValueError("A missing source cannot identify received bytes")
        if self.acquisition != "received" and not self.issues:
            raise ValueError("Incomplete acquisition needs a visible reason")
        if any(issue.stage != "acquisition" or issue.element_id is not None for issue in self.issues):
            raise ValueError("Acquisition issues belong to an occurrence, not a parsed element")
        return self


class ChildInventory(ContractModel):
    occurrence_id: Identifier
    completeness: Literal["complete", "partial", "unknown"]
    expected_children: Annotated[int, Field(ge=0)] | None
    issues: tuple[Issue, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_completeness(self) -> Self:
        if self.completeness == "complete" and (self.expected_children is None or self.issues):
            raise ValueError("A complete inventory needs a known denominator and no gaps")
        if self.completeness != "complete" and not self.issues:
            raise ValueError("An incomplete inventory needs a visible reason")
        if self.completeness == "unknown" and self.expected_children is not None:
            raise ValueError("An unknown denominator must stay unknown")
        return self


def _unique(items: tuple, key: str) -> dict:
    result = {getattr(item, key): item for item in items}
    if len(result) != len(items):
        raise ValueError(f"Duplicate {key}")
    return result


def _check_tree(items: dict, *, max_depth: int = 16) -> None:
    for identity, item in items.items():
        seen = {identity}
        parent = item.parent_id
        while parent is not None:
            if parent not in items or parent in seen:
                raise ValueError("Missing parent or cyclic source hierarchy")
            seen.add(parent)
            if len(seen) > max_depth:
                raise ValueError("Source hierarchy exceeds the contract depth bound")
            parent = items[parent].parent_id


class SourceManifest(ContractModel):
    objects: tuple[SourceObject, ...] = Field(max_length=1000)
    occurrences: tuple[SourceOccurrence, ...] = Field(min_length=1, max_length=1000)
    inventories: tuple[ChildInventory, ...] = Field(default=(), max_length=1000)

    @model_validator(mode="after")
    def validate_links(self) -> Self:
        objects = _unique(self.objects, "sha256")
        occurrences = _unique(self.occurrences, "occurrence_id")
        inventories = _unique(self.inventories, "occurrence_id")
        _check_tree(occurrences)
        for occurrence in self.occurrences:
            if occurrence.object_sha256 is not None and occurrence.object_sha256 not in objects:
                raise ValueError("An occurrence refers to an absent source object")
            if occurrence.parent_id is not None:
                parent = occurrences[occurrence.parent_id]
                if occurrence.source_version != parent.source_version:
                    raise ValueError("A child must refer to the same acquisition snapshot as its parent")
                if occurrence.parent_id not in inventories:
                    raise ValueError("Every container with children needs an explicit inventory")
            if occurrence.role == "email" and occurrence.occurrence_id not in inventories:
                raise ValueError("An email needs an inventory even when its count is unknown")
        for inventory in self.inventories:
            if inventory.occurrence_id not in occurrences:
                raise ValueError("An inventory refers to an absent occurrence")
            observed = sum(item.parent_id == inventory.occurrence_id for item in self.occurrences)
            expected = inventory.expected_children
            if expected is not None and (observed > expected or
                                         (inventory.completeness == "complete" and observed != expected)):
                raise ValueError("The inventory count disagrees with the occurrence list")
        return self

    def acquisition_status(self) -> Literal["complete", "partial", "unknown"]:
        if any(item.acquisition != "received" for item in self.occurrences):
            return "partial"
        if any(item.completeness == "partial" for item in self.inventories):
            return "partial"
        if any(item.completeness == "unknown" for item in self.inventories):
            return "unknown"
        return "complete"


class CellLocator(ContractModel):
    kind: Literal["cell"] = "cell"
    sheet: Label
    cell: Annotated[str, Field(pattern=r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")]
    row: Annotated[int, Field(ge=1, le=1_048_576)]
    column: Annotated[int, Field(ge=1, le=16_384)]

    @model_validator(mode="after")
    def validate_address(self) -> Self:
        letters, digits = re.fullmatch(r"([A-Z]+)([0-9]+)", self.cell).groups()
        column = 0
        for letter in letters:
            column = column * 26 + ord(letter) - ord("A") + 1
        if int(digits) != self.row or column != self.column:
            raise ValueError("Cell address disagrees with row or column")
        return self


class SheetLocator(ContractModel):
    kind: Literal["sheet"] = "sheet"
    sheet: Label


class WordLocator(ContractModel):
    kind: Literal["word"] = "word"
    part: Label
    structural_path: Label
    block_index: Annotated[int, Field(ge=0)]


class ImageLocator(ContractModel):
    kind: Literal["image"] = "image"
    image_sha256: Digest
    frame: Annotated[int, Field(ge=1)] = 1
    host: WordLocator | CellLocator | None = None
    # Original pixel coordinates only; transformed coordinates require a B1 mapping.
    region: tuple[int, int, int, int] | None = None

    @model_validator(mode="after")
    def validate_region(self) -> Self:
        if self.region is not None:
            left, top, right, bottom = self.region
            if min(left, top) < 0 or right <= left or bottom <= top:
                raise ValueError("Invalid original-pixel region")
        return self


class PdfLocator(ContractModel):
    """A reference to a frozen PDF word layer, without format conversion."""

    kind: Literal["pdf"] = "pdf"
    source_layer_id: Identifier
    page: Annotated[int, Field(ge=1)]
    word_ids: tuple[Annotated[int, Field(ge=0)], ...] = Field(default=(), max_length=1000)


class TextLocator(ContractModel):
    kind: Literal["text"] = "text"
    text_sha256: Digest
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if self.end < self.start:
            raise ValueError("Invalid text span")
        return self


Locator = Annotated[CellLocator | SheetLocator | WordLocator | ImageLocator | PdfLocator | TextLocator,
                    Field(discriminator="kind")]


class NativeValue(ContractModel):
    """Lexical values retain leading zeros and avoid binary floating-point loss."""

    kind: Literal["text", "integer", "decimal", "boolean", "date", "empty", "error"]
    lexical: Text | None

    @model_validator(mode="after")
    def validate_empty(self) -> Self:
        if (self.kind == "empty") != (self.lexical is None):
            raise ValueError("An empty position and a present lexical value are distinct")
        return self


class CellContent(ContractModel):
    value: NativeValue
    formula: Text | None = None
    cached_value: NativeValue | None = None
    cached_state: Literal["not_applicable", "missing", "unverified"] = "not_applicable"
    hidden: bool = False
    merged_range: Label | None = None

    @model_validator(mode="after")
    def validate_formula(self) -> Self:
        if self.formula is None:
            if self.cached_state != "not_applicable" or self.cached_value is not None:
                raise ValueError("Only a formula has a cached result")
        elif not self.formula.startswith("=") or self.cached_state == "not_applicable":
            raise ValueError("A formula needs an explicit cached-result state")
        elif (self.cached_state == "missing") != (self.cached_value is None):
            raise ValueError("Cached-result presence disagrees with its state")
        return self


class SourceElement(ContractModel):
    element_id: Identifier
    parent_id: Identifier | None = None
    order: Annotated[int, Field(ge=0)]
    kind: Literal["sheet", "paragraph", "table", "cell", "image", "text", "unsupported"]
    locator: Locator
    availability: Literal["read", "empty", "unreadable", "unsupported"] = "read"
    text: Text | None = None
    cell: CellContent | None = None
    hidden: bool = False

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        if self.kind == "cell" and (self.cell is None or not isinstance(self.locator, CellLocator)):
            raise ValueError("A cell needs its native content and cell locator")
        if self.kind != "cell" and self.cell is not None:
            raise ValueError("Cell content belongs to a cell element")
        if self.kind == "image" and not isinstance(self.locator, ImageLocator):
            raise ValueError("An image needs an image locator")
        if self.kind == "sheet" and not isinstance(self.locator, SheetLocator):
            raise ValueError("A sheet needs a sheet locator")
        return self


class ReadLimits(ContractModel):
    """Explicit experiment bounds, never silently activated production policy."""

    input_bytes: Annotated[int, Field(gt=0)]
    expanded_bytes: Annotated[int, Field(gt=0)]
    archive_entries: Annotated[int, Field(gt=0)]
    expansion_ratio: Annotated[int, Field(gt=0)]
    visited_cells: Annotated[int, Field(gt=0)]
    image_pixels: Annotated[int, Field(gt=0)]
    output_bytes: Annotated[int, Field(gt=0, le=MAX_CONTRACT_BYTES)]
    wall_seconds: Annotated[int, Field(gt=0)]
    memory_bytes: Annotated[int, Field(gt=0)]
    source_tree_depth: Annotated[int, Field(gt=0, le=16)]


ProtectionState = Literal["enforced", "not_executed", "unavailable"]


class Protections(ContractModel):
    network: ProtectionState
    paths: ProtectionState
    active_content: ProtectionState
    expansion: ProtectionState
    cells: ProtectionState
    pixels: ProtectionState
    time: ProtectionState
    memory: ProtectionState

    def combined_with(self, other: Protections) -> Protections:
        """Report the weakest stated protection across two execution boundaries."""
        priority = {"enforced": 0, "not_executed": 1, "unavailable": 2}
        return Protections(**{name: max((value, getattr(other, name)), key=priority.__getitem__)
                              for name, value in self.model_dump().items()})


class ParseAttempt(ContractModel):
    attempt_id: Identifier
    occurrence_id: Identifier
    source_sha256: Digest
    parser_name: Identifier
    parser_version: Label
    config_sha256: Digest
    models_sha256: Digest
    contract_version: Literal["source-contract-0.1"] = SCHEMA_VERSION
    execution: Literal["contract_fixture", "reader"]
    limits: ReadLimits
    protections: Protections
    parser_protections: Protections | None = Field(default=None, exclude_if=lambda value: value is None)
    recognition_protections: Protections | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def validate_protection_scopes(self) -> Self:
        if (self.parser_protections is None) != (self.recognition_protections is None):
            raise ValueError("Parser and recognition protection scopes must be supplied together")
        if self.parser_protections is not None:
            if self.protections != self.parser_protections.combined_with(self.recognition_protections):
                raise ValueError("Aggregate protections differ from their execution scopes")
        return self

    def reader_key(self) -> str:
        """Reusable reading identity; occurrence and execution attempt stay separate."""
        value = {field: getattr(self, field) for field in (
            "source_sha256", "parser_name", "parser_version", "config_sha256", "models_sha256", "contract_version", "execution",
        )}
        # Limits affect the result and therefore also affect deterministic reuse.
        value["limits"] = self.limits.model_dump(mode="json")
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class EvidenceRef(ContractModel):
    sha256: Digest
    byte_size: Annotated[int, Field(ge=0, le=MAX_CONTRACT_BYTES)]
    source_sha256: Digest
    reader_key: Digest
    media_type: Literal["application/json", "application/jsonl", "text/plain"]


def verify_evidence(reference: EvidenceRef, source: bytes, evidence: bytes) -> None:
    """Check already bounded bytes; never invoke a parser to recreate evidence."""
    if hashlib.sha256(source).hexdigest() != reference.source_sha256:
        raise ContractError("Frozen source content does not match the evidence reference")
    if len(evidence) != reference.byte_size or hashlib.sha256(evidence).hexdigest() != reference.sha256:
        raise ContractError("Frozen raw evidence does not match its reference")


class ParsedDocument(ContractModel):
    attempt: ParseAttempt
    status: Literal["complete", "partial", "unsupported", "password_required", "corrupt",
                    "resource_limited", "temporary_error", "excluded"]
    elements: tuple[SourceElement, ...] = Field(default=(), max_length=5000)
    issues: tuple[Issue, ...] = Field(default=(), max_length=1000)
    raw_evidence: EvidenceRef | None = None
    interpretation_status: Literal["not_run"] = "not_run"
    human_review_status: Literal["not_reviewed"] = "not_reviewed"

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        elements = _unique(self.elements, "element_id")
        _check_tree(elements)
        positions = {(element.parent_id, element.order) for element in self.elements}
        if len(positions) != len(self.elements):
            raise ValueError("Sibling reading positions must be unique")
        if self.status == "complete" and (not self.elements or self.issues):
            raise ValueError("An empty or incomplete reading cannot claim complete content")
        if self.status != "complete" and not self.issues:
            raise ValueError("An incomplete reading needs a visible reason")
        for issue in self.issues:
            if issue.stage != "reading":
                raise ValueError("Reading issues must not masquerade as acquisition or interpretation")
            if issue.element_id is not None and issue.element_id not in elements:
                raise ValueError("An issue refers to an absent source element")
        for element in self.elements:
            if element.availability in ("unreadable", "unsupported"):
                if self.status == "complete" or not any(i.element_id == element.element_id for i in self.issues):
                    raise ValueError("Unread content needs an explicit element-level reason")
        if self.raw_evidence is not None:
            if self.raw_evidence.byte_size > self.attempt.limits.output_bytes:
                raise ValueError("Raw evidence exceeds the declared output bound")
            if self.raw_evidence.source_sha256 != self.attempt.source_sha256:
                raise ValueError("Evidence belongs to a different source")
            if self.raw_evidence.reader_key != self.attempt.reader_key():
                raise ValueError("Evidence belongs to a different reading version")
        if self.elements and self.raw_evidence is None:
            raise ValueError("A structural result needs a frozen raw-evidence reference")
        if self.attempt.execution == "reader" and self.status in ("complete", "partial"):
            parser = self.attempt.parser_protections or self.attempt.protections
            if any(value != "enforced" for value in parser.model_dump().values()):
                raise ValueError("A real reader must enforce its protections before publishing content")
            recognition = self.attempt.recognition_protections
            if recognition is not None:
                if any(value != "enforced" for name, value in recognition.model_dump().items()
                       if name not in {"network", "paths"}):
                    raise ValueError("Recognition must enforce its content and resource bounds")
                if any(value == "not_executed" for value in recognition.model_dump().values()):
                    raise ValueError("Published recognition cannot claim an unexecuted boundary")
                if recognition.network != "enforced" or recognition.paths != "enforced":
                    if self.status != "partial" or not any(i.code == "protection_unavailable" for i in self.issues):
                        raise ValueError("Limited recognition isolation requires an explicit partial protection issue")
        return self


class SourceBundle(ContractModel):
    schema_version: Literal["source-contract-0.1"] = SCHEMA_VERSION
    manifest: SourceManifest
    results: tuple[ParsedDocument, ...] = Field(default=(), max_length=1000)

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        _unique(tuple(result.attempt for result in self.results), "attempt_id")
        occurrences = {item.occurrence_id: item for item in self.manifest.occurrences}
        objects = {item.sha256 for item in self.manifest.objects}
        for result in self.results:
            occurrence = occurrences.get(result.attempt.occurrence_id)
            if occurrence is None or occurrence.object_sha256 != result.attempt.source_sha256:
                raise ValueError("A reading is not bound to its acquired occurrence")
            if occurrence.acquisition not in ("received", "truncated"):
                raise ValueError("An absent or excluded source cannot have a reading")
            if occurrence.acquisition == "truncated" and result.status == "complete":
                raise ValueError("Truncated acquisition cannot produce a complete reading")
            for element in result.elements:
                if isinstance(element.locator, ImageLocator):
                    image_sha = element.locator.image_sha256
                    if image_sha not in objects:
                        raise ValueError("An image locator refers to an absent frozen object")
                    if image_sha != occurrence.object_sha256:
                        linked = False
                        for child in self.manifest.occurrences:
                            if child.object_sha256 != image_sha:
                                continue
                            parent = child.parent_id
                            while parent is not None:
                                if parent == occurrence.occurrence_id:
                                    linked = True
                                    break
                                parent = occurrences[parent].parent_id
                        if not linked:
                            raise ValueError("An embedded image needs a descendant occurrence in the same source tree")
        return self

    def reading_status(self, occurrence_id: str) -> str:
        """Expose received but unattempted content instead of implying success."""
        occurrence = next((item for item in self.manifest.occurrences if item.occurrence_id == occurrence_id), None)
        if occurrence is None:
            raise ContractError("Unknown source occurrence")
        if occurrence.acquisition in ("missing", "excluded"):
            return "unavailable"
        attempts = [result for result in self.results if result.attempt.occurrence_id == occurrence_id]
        return attempts[-1].status if attempts else "not_attempted"


class Parser(Protocol):
    """Small adapter boundary; implementations must run in a bounded worker.

    Availability must be a local dependency check. A parser must not initialise a
    provider, execute active content or download anything. These are implementation
    requirements, not guarantees provided by this protocol.
    """

    name: str
    applicable_mimes: frozenset[str]

    def is_available(self) -> bool: ...

    def parse(self, path: Path, attempt: ParseAttempt) -> ParsedDocument: ...


def read_bundle(payload: bytes) -> SourceBundle:
    """Validate a bounded external envelope before exposing its structured data."""
    if len(payload) > MAX_CONTRACT_BYTES:
        raise ContractError("Source contract exceeds the byte bound")

    def reject_constant(value: str) -> None:
        raise ContractError(f"Non-finite JSON value: {value}")

    def unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ContractError("Duplicate JSON keys are ambiguous")
        return value

    try:
        value = json.loads(payload.decode("utf-8"), parse_constant=reject_constant, object_pairs_hook=unique_keys)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError("Source contract is not bounded UTF-8 JSON") from exc
    pending = [(value, 0)]
    visited = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if visited > MAX_CONTRACT_NODES or depth > MAX_CONTRACT_DEPTH:
            raise ContractError("Source contract exceeds the shape bound")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return SourceBundle.model_validate_json(payload, strict=True)
