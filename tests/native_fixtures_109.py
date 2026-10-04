"""Synthetic native API contracts shared by backend and UI tests.

These examples describe expected response shapes; they are not provider,
extraction-quality or browser acceptance evidence. No files or calls on import.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib

from jav.native_contracts import (
    DOCUMENT_FORMATS, Failed, InterpretationView, NativeCitation, NativeCorrection,
    NativeFact, NativeItemResult, NativeSource, NativeSourceElement, NotStarted,
    ReadingResult, ReadingSummary, ReceiptRef, Rejected, Running, SourcePage,
    Succeeded, Uncertain,
)
from jav.readers.contracts import (
    CellContent, CellLocator, Issue, NativeValue, SheetLocator, SourceOccurrence, TextLocator,
)
from jav.readers.interpretation import Citation, ProposedFact


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# Explicit codepoints keep the Unicode fixture stable across source encodings.
TEXT = "😀 Azonos\u00edt\u00f3: 0012\nPartner: P\u00e9lda\n"
SOURCE_SHA = sha(TEXT)
BUNDLE_SHA = sha("synthetic bundle")
RESULT_VERSION = sha("synthetic publication")
READING_ID = "nr-" + sha("synthetic reading")
PUBLICATION_ID = "np-" + RESULT_VERSION
FACT_ID = "nf-" + sha("synthetic interpretation:0")[:24]
READER_KEY = sha("synthetic reader key")


def _result(status="complete", issues=()) -> ReadingResult:
    return ReadingResult(occurrence_id="o0", attempt_id="read:o0", reader_key=READER_KEY,
                         status=status, issues=issues)


def _receipt(*, uncertain=False) -> ReceiptRef:
    return ReceiptRef(receipt_id="synthetic-invocation-1", invocation_id=1, provider="openai",
        run_id="synthetic-native-graph", step_id="reader:gpt:synthetic", request_sha256=sha("synthetic request"),
        response_sha256=None if uncertain else sha("synthetic received response"),
        artifact_kind=None if uncertain else "invocation_response", artifact_id=None if uncertain else "1",
        call_status="uncertain" if uncertain else "succeeded", cost_known=not uncertain,
        cost_usd=None if uncertain else Decimal("0.00012"))


def citation() -> NativeCitation:
    start = TEXT.index("0012")
    return NativeCitation(occurrence_id="o0", element_id="e0", quote="0012",
        locator=TextLocator(text_sha256=SOURCE_SHA, start=0, end=len(TEXT)),
        attempt_id="read:o0", reader_key=READER_KEY, reading_id=READING_ID,
        publication_id=PUBLICATION_ID, result_version=RESULT_VERSION, source_sha256=SOURCE_SHA,
        quote_match_count=1, quote_span=TextLocator(text_sha256=SOURCE_SHA, start=start, end=start + 4))


def complete_item() -> NativeItemResult:
    cite = citation()
    proposal = ProposedFact(entity="document", property="reference", value="0012", state="stated",
                            citations=(Citation(occurrence_id="o0", element_id="e0", quote="0012"),))
    return NativeItemResult(run_id="synthetic-native-run", item_id="synthetic-native-item",
        result_version=RESULT_VERSION, review_version=sha("synthetic review"), result_ready=True,
        native_source=NativeSource(reading_id=READING_ID, bundle_sha256=BUNDLE_SHA,
                                   publication_id=PUBLICATION_ID, source_sha256=SOURCE_SHA),
        reading=ReadingSummary(status="complete", acquisition_status="complete", attempt_ids=("read:o0",), results=(_result(),)),
        interpretation_outcome=Succeeded(receipt_refs=(_receipt(),)),
        interpretation=InterpretationView(interpretation_id="ni-" + sha("synthetic interpretation"),
            payload_sha256=sha("synthetic interpretation"), status="completed", provider="openai",
            model="synthetic-model", execution="synthetic_test", gaps=()),
        native_facts=(NativeFact(fact_id=FACT_ID, proposal=proposal, grounding="literal_match",
                                effective_value="0012", native_citations=(cite,)),),
        source_file={"copy": True, "original": "unchanged"})


def item_cases() -> dict[str, dict]:
    full = complete_item().model_dump(mode="json")
    cases = {"complete": full}
    partial = deepcopy(full)
    issue = Issue(stage="reading", code="unread_content", message="Synthetic embedded image was not read")
    partial["reading"] = ReadingSummary(status="partial", acquisition_status="complete", attempt_ids=("read:o0",),
                                        results=(_result("partial", (issue,)),)).model_dump(mode="json")
    cases["partial"] = partial
    empty = deepcopy(full)
    empty["native_facts"] = []
    empty["interpretation"]["status"] = "empty"
    cases["empty_success"] = empty
    corrected = deepcopy(full)
    corrected["native_facts"][0].update(effective_value="0099", native_citations=[], confirmed=True)
    corrected["correction"] = NativeCorrection(revision=1, fields={FACT_ID: "0099"},
                                                native_sources={FACT_ID: ()}, confirmed={FACT_ID: "0099"}).model_dump(mode="json")
    cases["corrected"] = corrected
    for state in (NotStarted(), Running()):
        value = deepcopy(full)
        value.update(result_ready=False, native_source=None, result_version=None, native_facts=[],
                     interpretation=None, reading=ReadingSummary().model_dump(mode="json"),
                     interpretation_outcome=state.model_dump(mode="json"))
        cases[state.status] = value
    outcomes = (Rejected(reason="Received answer failed validation", receipt_refs=(_receipt(),)),
                Failed(reason="Synthetic request exceeded its transfer bound"),
                Uncertain(reason="Synthetic response transport was interrupted", receipt_refs=(_receipt(uncertain=True),)))
    for outcome in outcomes:
        value = deepcopy(full)
        value.update(native_facts=[], interpretation=None, interpretation_outcome=outcome.model_dump(mode="json"))
        cases[outcome.status] = value
    # A failed worker can also have no publication; it must remain a native item.
    unpublished = deepcopy(cases["failed"])
    unpublished.update(result_ready=False, native_source=None, result_version=None, reading=ReadingSummary().model_dump(mode="json"))
    cases["unpublished_failure"] = unpublished
    return cases


def source_pages() -> dict[str, dict]:
    occurrence = SourceOccurrence(occurrence_id="o0", source_version="synthetic-source", original_name="synthetic.txt",
                                  role="document", acquisition="received", object_sha256=SOURCE_SHA)
    common = dict(publication_id=PUBLICATION_ID, reading_id=READING_ID, result_version=RESULT_VERSION,
                  bundle_sha256=BUNDLE_SHA, source_sha256=SOURCE_SHA, occurrences=(occurrence,), results=(_result(),),
                  offset=0, limit=200, has_more=False, next_offset=None)
    source = NativeSourceElement(element_id="e0", order=0, kind="text", text=TEXT,
        locator=TextLocator(text_sha256=SOURCE_SHA, start=0, end=len(TEXT)), occurrence_id="o0",
        attempt_id="read:o0", reader_key=READER_KEY)
    text = SourcePage(**common, elements=(source,), texts={SOURCE_SHA: TEXT}, total=1)
    binding = dict(occurrence_id="o0", attempt_id="read:o0", reader_key=READER_KEY)
    elements = [NativeSourceElement(element_id="sheet", order=0, kind="sheet", locator=SheetLocator(sheet="Sample"), **binding)]
    cells = [
        ("A1", NativeValue(kind="text", lexical="0012"), {}),
        ("B1", NativeValue(kind="empty", lexical=None), {"availability": "empty"}),
        ("C1", NativeValue(kind="decimal", lexical="3.00"), {}),
    ]
    for index, (address, value, extra) in enumerate(cells, 1):
        cell = CellContent(value=value, formula="=1+2" if address == "C1" else None,
                           cached_value=value if address == "C1" else None,
                           cached_state="unverified" if address == "C1" else "not_applicable")
        elements.append(NativeSourceElement(element_id=f"cell{index}", parent_id="sheet", order=index,
            kind="cell", locator=CellLocator(sheet="Sample", cell=address, row=1, column=index),
            text=value.lexical, cell=cell, **binding, **extra))
    grid = SourcePage(**common, elements=tuple(elements), texts={}, total=len(elements))
    return {"text": text.model_dump(mode="json"), "cells": grid.model_dump(mode="json")}


def contract_examples() -> dict:
    return {"description": "Synthetic contract examples only; not execution or accuracy evidence",
            "formats": [item.model_dump(mode="json") for item in DOCUMENT_FORMATS],
            "items": item_cases(), "source_pages": source_pages(),
            "resolve_request": {"result_version": RESULT_VERSION, "citations": [{"occurrence_id": "o0", "element_id": "e0", "quote": "0012"}]},
            "resolve_response": [citation().model_dump(mode="json")],
            "correction_request": {"kind": "native", "values": {FACT_ID: "0099"}, "native_sources": {FACT_ID: []},
                                   "confirm": [FACT_ID], "expected_revision": 0, "expected_result_version": RESULT_VERSION,
                                   "note": "Synthetic human correction"}}


def runtime_source(tmp_path, monkeypatch, *, text="😀 Order code: 0012\n", raster=False,
                   name="frozen.txt", content=None):
    """Construct actual saved evidence with an explicitly in-process test parser."""
    import base64
    import json
    from jav import native_results, store, work  # noqa: F401 - register the actual work schema
    from jav.readers import native, pipeline

    source = tmp_path / name
    source.write_bytes(text.encode("utf-8") if content is None else content)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()

    def read(data, name, limits, **kwargs):
        response = native.read(data, name, limits, **kwargs)
        if raster:
            data = b"Synthetic immutable recognition raster"
            response["rasters"] = [{"sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data),
                                    "data": base64.b64encode(data).decode()}]
        return response

    monkeypatch.setattr(pipeline, "run", read)
    with store.connect() as c:
        c.execute("INSERT INTO workpackages(id,name,source_kind,created_at,updated_at) VALUES (?,?,?,?,?)",
                  ("native-wp", "Synthetic native package", "manual", "now", "now"))
        c.execute("INSERT INTO runs(run_id,workpackage_id,dedup_key,mode,assignment_revision,recipe_id,recipe_version,recipe_hash,recipe,"
                  "params,input,input_hash,status,actor,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  ("native-run", "native-wp", "unique-native-run", "shadow", 1, "multi-format-processing", 1,
                   "a" * 16, "{}", "{}", json.dumps({"items": [{"item_id": "native-item", "kind": "document",
                       "sha256": source_sha, "source_path": str(source)}]}), "b" * 16, "running", "synthetic", "now"))
        c.execute("INSERT INTO run_items(run_id,item_id,status,flow_run_id,updated_at) VALUES (?,?,?,?,?)",
                  ("native-run", "native-item", "running", "native-graph", "now"))
    ref = native_results.prepare_reading(source, original_name="original" + source.suffix, expected_sha256=source_sha)
    return source, ref


def publish_runtime(ref, *, value="0012", quote="Order code: 0012", c=None):
    from jav import native_results
    from jav.readers.interpretation import Citation, ProposedExtraction, ProposedFact, ground

    delivery = native_results.load_reading(ref.reading_id, c=c)
    element = delivery.bundle.results[0].elements[0]
    proposal = ProposedExtraction(facts=(ProposedFact(entity="order", property="code", value=value, state="stated",
        citations=(Citation(occurrence_id="o0", element_id=element.element_id, quote=quote),)),))
    interpretation = ground(delivery, proposal, provider="synthetic", model="synthetic-test", execution="synthetic_test")
    return native_results.publish(run_id="native-run", item_id="native-item", source_sha256=ref.source_sha256,
        recipe_hash="a" * 16, reading_id=ref.reading_id, outcome=Succeeded(), interpretation=interpretation, c=c)


def synthetic_gpt(monkeypatch, *, mode="valid", payload=None):
    """Exercise the real agent validation and receipt path with an in-process model."""
    import json
    from pydantic_ai import Agent, NativeOutput
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.usage import RequestUsage
    from jav.config import OPENAI_MODEL
    from jav.readers import providers
    from jav.readers.interpretation import ProposedExtraction

    requests = []
    value = payload or {"facts": [{"entity": "order", "property": "code", "value": "0012", "state": "stated",
        "citations": [{"occurrence_id": "o0", "element_id": "e0", "quote": "Order code: 0012"}]}], "gaps": []}

    def respond(messages, info):
        requests.append(messages)
        if mode == "timeout":
            raise TimeoutError("Synthetic uncertain transport")
        parts = [] if mode == "empty" else [TextPart("{}" if mode == "invalid" else json.dumps(value))]
        return ModelResponse(parts, usage=RequestUsage(input_tokens=100, output_tokens=40))

    agent = Agent(FunctionModel(respond, model_name=OPENAI_MODEL), output_type=NativeOutput(ProposedExtraction), retries=0)
    original = providers.extract_gpt

    def extract(*args, **kwargs):
        return original(*args, agent=agent, **kwargs)

    monkeypatch.setattr(providers, "extract_gpt", extract)
    return requests
