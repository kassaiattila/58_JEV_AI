"""Hand-authored contract fixtures, not claims of successful Office parsing.

Source objects are explicitly JSON blueprints. The picture is a generated PNG.
Actual DOCX/XLSX adapters must earn the expected structure with real-file tests.
"""

import hashlib
import io
import json

from PIL import Image, ImageDraw

from jav.readers.contracts import (
    CellContent,
    CellLocator,
    ChildInventory,
    EvidenceRef,
    ImageLocator,
    Issue,
    NativeValue,
    ParseAttempt,
    ParsedDocument,
    Protections,
    ReadLimits,
    SheetLocator,
    SourceBundle,
    SourceElement,
    SourceManifest,
    SourceObject,
    SourceOccurrence,
    WordLocator,
)


def _bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def synthetic_payloads() -> dict[str, bytes]:
    image = Image.new("RGB", (180, 40), "white")
    ImageDraw.Draw(image).text((5, 10), "Synthetic scan 0007", fill="black")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return {
        "spreadsheet.blueprint.json": _bytes({
            "fixture_kind": "expected_structure_not_reader_output", "intended_format": "xlsx",
            "sheet": "Orders", "cells": {"A2": "0007", "B2": None, "C2": "=1+2", "A4": "Synthetic heading"},
            "formula_cache": None, "hidden_sheet": "Hidden", "merged_range": "A4:C4",
        }),
        "word.blueprint.json": _bytes({
            "fixture_kind": "expected_structure_not_reader_output", "intended_format": "docx",
            "blocks": ["Before table", {"table": [["Code", "0007"]]}, "After table", {"image": "scan.png"}],
        }),
        "message.blueprint.json": _bytes({
            "fixture_kind": "expected_manifest_not_download", "body": "Synthetic message",
            "attachments": ["spreadsheet.blueprint.json", "scan.png", "missing.docx", "unsupported.bin"],
        }),
        "scan.png": stream.getvalue(),
        "unsupported.bin": b"Synthetic unsupported content",
    }


def sample_bundles() -> dict[str, SourceBundle]:
    payloads = synthetic_payloads()
    objects = {
        name: SourceObject(sha256=_sha(payload), byte_size=len(payload),
                           detected_mime="image/png" if name.endswith(".png") else
                           "application/json" if name.endswith(".json") else "application/octet-stream")
        for name, payload in payloads.items()
    }
    limits = ReadLimits(input_bytes=1_000_000, expanded_bytes=4_000_000, archive_entries=100,
                        expansion_ratio=20, visited_cells=1000, image_pixels=1_000_000,
                        output_bytes=1_000_000, wall_seconds=10, memory_bytes=268_435_456,
                        source_tree_depth=3)
    protections = Protections(**{name: "not_executed" for name in Protections.model_fields})

    def occurrence(identity, name, *, parent=None, role="document", version="fixture-v1", acquisition="received"):
        return SourceOccurrence(occurrence_id=identity, parent_id=parent, source_version=version,
                                original_name=name, role=role, acquisition=acquisition,
                                object_sha256=objects[name].sha256)

    def result(identity, name, elements, issues, status=None):
        attempt = ParseAttempt(attempt_id=f"{identity}-attempt-1", occurrence_id=identity,
                               source_sha256=objects[name].sha256, parser_name="contract-fixture",
                               parser_version="0.1", config_sha256=_sha(b"fixture-config-v1"),
                               models_sha256=_sha(b"no-models"), execution="contract_fixture",
                               limits=limits, protections=protections)
        evidence = _bytes({"fixture": name, "elements": [item.model_dump(mode="json") for item in elements]})
        reference = EvidenceRef(sha256=_sha(evidence), byte_size=len(evidence),
                                source_sha256=attempt.source_sha256, reader_key=attempt.reader_key(),
                                media_type="application/json")
        return ParsedDocument(attempt=attempt, status=status or ("partial" if issues else "complete"), elements=tuple(elements),
                              issues=tuple(issues), raw_evidence=reference)

    sheet_elements = [SourceElement(element_id="orders", order=0, kind="sheet", locator=SheetLocator(sheet="Orders"))]
    for order, column, kind, lexical, formula in [
        (0, "A", "text", "0007", None), (1, "B", "empty", None, None), (2, "C", "empty", None, "=1+2"),
    ]:
        sheet_elements.append(SourceElement(
            element_id=f"cell-{column}2", parent_id="orders", order=order, kind="cell",
            locator=CellLocator(sheet="Orders", cell=f"{column}2", row=2, column=order + 1),
            availability="empty" if column == "B" else "read",
            cell=CellContent(value=NativeValue(kind=kind, lexical=lexical), formula=formula,
                             cached_state="missing" if formula else "not_applicable"),
        ))
    sheet_elements.extend([
        SourceElement(element_id="merged-heading", parent_id="orders", order=3, kind="cell",
                      locator=CellLocator(sheet="Orders", cell="A4", row=4, column=1),
                      cell=CellContent(value=NativeValue(kind="text", lexical="Synthetic heading"), merged_range="A4:C4")),
        SourceElement(element_id="hidden", order=1, kind="sheet", locator=SheetLocator(sheet="Hidden"), hidden=True),
    ])
    spreadsheet = result("workbook", "spreadsheet.blueprint.json", sheet_elements, [Issue(
        stage="reading", code="formula_cache_missing", message="The formula has no saved result; no calculation ran.",
        element_id="cell-C2",
    )])
    sheet_bundle = SourceBundle(
        manifest=SourceManifest(objects=(objects["spreadsheet.blueprint.json"],),
                                occurrences=(occurrence("workbook", "spreadsheet.blueprint.json"),)),
        results=(spreadsheet,),
    )

    word_elements = [SourceElement(
        element_id=identity, order=order, kind=kind, text=text,
        locator=WordLocator(part="word/document.xml", structural_path=path, block_index=order),
    ) for order, identity, kind, text, path in [
        (0, "before", "paragraph", "Before table", "/body/p[1]"),
        (1, "middle", "table", "Code\t0007", "/body/tbl[1]"),
        (2, "after", "paragraph", "After table", "/body/p[2]"),
    ]]
    word_elements.append(SourceElement(element_id="scan", order=3, kind="image", availability="unreadable",
                                       locator=ImageLocator(image_sha256=objects["scan.png"].sha256,
                                                            host=WordLocator(part="word/document.xml",
                                                                             structural_path="/body/p[3]/drawing[1]",
                                                                             block_index=3))))
    word_result = result("word", "word.blueprint.json", word_elements, [Issue(
        stage="reading", code="needs_ocr", message="Image text has not been read in this contract fixture.", element_id="scan",
    )])
    word_bundle = SourceBundle(
        manifest=SourceManifest(objects=(objects["word.blueprint.json"], objects["scan.png"]), occurrences=(
            occurrence("word", "word.blueprint.json"), occurrence("embedded-scan", "scan.png", parent="word", role="embedded"),
        ), inventories=(ChildInventory(occurrence_id="word", completeness="complete", expected_children=1),)),
        results=(word_result,),
    )

    email_bundle = SourceBundle(manifest=SourceManifest(
        objects=tuple(objects[name] for name in ["message.blueprint.json", "spreadsheet.blueprint.json", "scan.png", "unsupported.bin"]),
        occurrences=(
            occurrence("message", "message.blueprint.json", role="email"),
            occurrence("attachment", "spreadsheet.blueprint.json", parent="message", role="attachment"),
            occurrence("inline", "scan.png", parent="message", role="inline"),
            SourceOccurrence(occurrence_id="missing", parent_id="message", source_version="fixture-v1",
                             original_name="missing.docx", role="attachment", acquisition="missing", issues=(Issue(
                                 stage="acquisition", code="download_missing", message="The attachment was listed but not received.",
                             ),)),
            occurrence("unsupported", "unsupported.bin", parent="message", role="attachment"),
            occurrence("upload", "spreadsheet.blueprint.json", version="upload-v1"),
        ),
        inventories=(ChildInventory(occurrence_id="message", completeness="complete", expected_children=4),),
    ), results=(result("unsupported", "unsupported.bin", [], [Issue(
        stage="reading", code="unsupported", message="No reader has been selected for this binary format.",
    )], status="unsupported"),))
    return {"spreadsheet": sheet_bundle, "word_image": word_bundle, "email_manifest": email_bundle}


def raw_evidence_payload(result: ParsedDocument, name: str) -> bytes:
    """Reproduce the immutable fixture evidence without running a reader."""
    return _bytes({"fixture": name, "elements": [item.model_dump(mode="json") for item in result.elements]})
