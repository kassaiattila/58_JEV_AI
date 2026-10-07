"""Text recognised outside the reader, taken over as frozen evidence (124, F-azure-text-native).

Document detection may already have paid for an Azure Document Intelligence recognition of a scanned PDF, and the
native step may ask for one itself within the run's Azure budget. The reader never calls a provider: it receives the
kept original recognition (`jav.ocr.save_recognition`), checks it against the frozen PDF pages and maps its word
polygons onto them, with the same word conversion and line tolerance as document detection. A page the recognition
does not cover, or does not fit, stays explicitly unread; local recognition is never mixed in. The original stays in
the Delivery under its digest, and loading a reading checks the saved word layer's binding to it (`verify`).
"""
from __future__ import annotations

import hashlib
import json
import math

from jav import pdf as pdfmod
from .contracts import ExternalRecognition, Issue, ReadLimits, SourceElement
from .limits import ReadFailure, limited
from .native import Reading
from .visual import add_layer, layer_for

PROVIDER = "azure_di"
MAPPING_VERSION = "azure-read-1"
SIZE_TOLERANCE_PT = 1.0  # Azure states page sizes in inches with four decimals
EDGE_TOLERANCE_PT = 0.72  # a word box may pass the page edge by 0.01 inch; it is clamped onto the page


def _evidence(recognition: bytes, limits: ReadLimits) -> dict:
    limited(len(recognition) > limits.output_bytes, "Recognition evidence exceeds the output bound")

    def reject_constant(value: str):
        raise ValueError(f"Invalid JSON constant {value}")

    evidence = json.loads(recognition, parse_constant=reject_constant)
    if (not isinstance(evidence, dict) or evidence.get("provider") != PROVIDER
            or not isinstance(evidence.get("pages"), list)):
        raise ValueError("Not an Azure recognition")
    return evidence


def describe(recognition: bytes, source_sha: str) -> ExternalRecognition:
    evidence = json.loads(recognition)
    return ExternalRecognition(provider=PROVIDER, model=str(evidence.get("model_id") or "prebuilt-read"),
                               api_version=str(evidence.get("api_version") or "unknown"), request_sha256=source_sha,
                               response_sha256=hashlib.sha256(recognition).hexdigest(), byte_size=len(recognition),
                               mapping_version=MAPPING_VERSION)


def _page_words(page: dict, words: list[dict], size: tuple[float, float], limits: ReadLimits) -> list[dict]:
    """The page's words in points, clamped onto the page; ValueError names why the page is not taken over."""
    width, height = size
    if page.get("unit") != "inch":
        raise ValueError("its unit is not inch")
    stated = (page.get("width"), page.get("height"))
    if not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in stated):
        raise ValueError("its page size is missing")
    if abs(stated[0] * 72 - width) > SIZE_TOLERANCE_PT or abs(stated[1] * 72 - height) > SIZE_TOLERANCE_PT:
        raise ValueError("its page size differs from the PDF page (a rotated or cropped page)")
    if len(words) > limits.visited_cells:
        raise ValueError("it exceeds the recognised word limit")
    if not words:
        raise ValueError("it holds no text; blankness is not established")
    out = []
    for word in words:
        box = (word["x0"], word["top"], word["x1"], word["bottom"])
        if (not all(math.isfinite(v) for v in box) or min(box[0], box[1]) < -EDGE_TOLERANCE_PT
                or box[2] > width + EDGE_TOLERANCE_PT or box[3] > height + EDGE_TOLERANCE_PT):
            raise ValueError("a recognised word lies outside the page")
        x0, top = max(0.0, box[0]), max(0.0, box[1])
        x1, bottom = min(width, box[2]), min(height, box[3])
        if not (x0 < x1 and top < bottom):
            raise ValueError("a recognised word has no area on the page")
        out.append({**word, "x0": x0, "top": top, "x1": x1, "bottom": bottom})
    return out


def map_pages(evidence: dict, sizes: list[tuple[float, float]], wanted: list[int],
              limits: ReadLimits) -> tuple[dict[int, list[dict]], dict[int, str]]:
    """The words of every wanted page the recognition fits, and the reason for every other wanted page."""
    from jav.ocr import azure_evidence_words

    pages = evidence["pages"]
    numbers = [page.get("page_number") if isinstance(page, dict) else None for page in pages]
    if (any(type(n) is not int or not 1 <= n <= len(sizes) for n in numbers) or len(set(numbers)) != len(numbers)):
        return {}, dict.fromkeys(wanted, "the recognition's pages do not match the document's pages")
    words, _confidences, _meta = azure_evidence_words(evidence)
    accepted, rejected = {}, {}
    for number in wanted:
        if number not in numbers:
            rejected[number] = "the recognition does not cover this page"
            continue
        index = numbers.index(number)
        try:
            accepted[number] = _page_words(pages[index], words[index], sizes[number - 1], limits)
        except ValueError as exc:
            rejected[number] = str(exc)
    return accepted, rejected


def recognised_layer(source_sha: str, accepted: dict[int, list[dict]], sizes: list[tuple[float, float]]):
    """One word layer for every taken-over page; lines with detection's tolerance (`jav.ocr.line_tolerance`)."""
    from jav.ocr import confidence_signals, line_tolerance

    pages = [[dict(word) for word in accepted.get(number, [])] for number in range(1, len(sizes) + 1)]
    pdfmod.build_layout(pages, y_tol=line_tolerance(pages))
    signals = confidence_signals([w["conf"] for page in pages for w in page if w["conf"] >= 0])
    return layer_for(source_sha, pages, sizes, recognised=True, engine=PROVIDER), signals


def _native_sizes(layers: dict[str, dict]) -> list[tuple[float, float]]:
    native = [layer for layer in layers.values() if layer.get("text_source") == "pdf"]
    if len(native) != 1:
        raise ValueError("A recognition needs exactly one native PDF page layer")
    return [(page["width_pt"], page["height_pt"]) for page in native[0]["pages"]]


def finish(response: dict, source_sha: str, recognition: bytes,
           limits: ReadLimits) -> tuple[dict, ExternalRecognition | None]:
    """Take the recognition over for the reading's unread visual pages. Without such a page nothing is taken over."""
    reading = Reading(response["parser"], response["mime"], limits)
    reading.elements = [SourceElement.model_validate_json(json.dumps(e)) for e in response["elements"]]
    reading.issues = [Issue.model_validate_json(json.dumps(i)) for i in response["issues"]]
    reading.children, reading.texts = response["children"], response["texts"]
    reading.source_layers = response.get("source_layers", {})
    pending = {i.element_id for i in reading.issues if i.code == "needs_ocr" and i.element_id}
    visual = {e.locator.page: e.element_id for e in reading.elements
              if e.locator.kind == "pdf" and not e.locator.word_ids and e.element_id in pending}
    if not visual:
        return response, None
    try:
        evidence = _evidence(recognition, limits)
        accepted, rejected = map_pages(evidence, _native_sizes(reading.source_layers), sorted(visual), limits)
    except (ReadFailure, ValueError) as exc:
        accepted, rejected = {}, dict.fromkeys(visual, f"the recognition was rejected ({type(exc).__name__})")
    taken = {visual[number] for number in accepted}
    reading.issues = [i for i in reading.issues if not (i.code == "needs_ocr" and i.element_id in set(visual.values()))]
    for number, reason in sorted(rejected.items()):
        reading.issue("needs_ocr", f"Azure recognition was not taken over for page {number}: {reason}", visual[number])
    layer_id, signals, count = None, {"mean_conf": 0.0, "low_conf_ratio": 1.0}, 0
    if accepted:
        layer, signals = recognised_layer(source_sha, accepted, _native_sizes(reading.source_layers))
        add_layer(reading, layer)
        layer_id, count = layer.layer_id, len(layer.words)
        reading.elements = [e.model_copy(update={"availability": "read"}) if e.element_id in taken else e
                            for e in reading.elements]
    output = reading.output()
    output["recognition"] = {"sha256": hashlib.sha256(recognition).hexdigest(), "layer_id": layer_id,
                             "pages": sorted(accepted), "words": count, **signals}
    return output, describe(recognition, source_sha)


def verify(raw: dict, recognition: bytes | None, source_sha: str, external: ExternalRecognition,
           limits: ReadLimits) -> None:
    """Check the binding of a saved reading to its kept recognition from the saved data alone.

    The mapping is not recomputed on loading: that would tie every earlier reading to today's word and line code
    (`jav/ocr.py`, `jav/pdf.py`), and a later change there would make old readings, and the backup listing them,
    unloadable. The reading's identity already names the reader code that produced it (`implementation_version`).
    """
    if recognition is None or describe(recognition, source_sha) != external:
        raise ValueError("The kept recognition is missing or differs from its reading attempt")
    saved = raw.get("recognition")
    if (not isinstance(saved, dict) or set(saved) != {"sha256", "layer_id", "pages", "words", "mean_conf",
                                                      "low_conf_ratio"}
            or saved["sha256"] != external.response_sha256):
        raise ValueError("The reading does not record its taken-over recognition")
    numbers = {p.get("page_number") for p in _evidence(recognition, limits)["pages"] if isinstance(p, dict)}
    pages = saved["pages"]
    if pages != sorted(set(pages)) or not set(pages) <= numbers:
        raise ValueError("The reading names pages its recognition does not cover")
    layers = raw.get("source_layers", {})
    if not pages:
        if saved["layer_id"] is not None or saved["words"] != 0:
            raise ValueError("A recognition without taken-over pages has no word layer")
        return
    layer = layers.get(saved["layer_id"])
    if (layer is None or layer.get("engine") != PROVIDER or layer.get("text_source") != "ocr"
            or len(layer.get("words", [])) != saved["words"]
            or {word["page"] for word in layer["words"]} != set(pages)):
        raise ValueError("The saved word layer differs from the taken-over recognition")
