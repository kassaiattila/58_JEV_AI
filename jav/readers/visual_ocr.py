"""Explicit local OCR over frozen PNG bytes; no network or paid fallback."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import csv
import hashlib
from io import StringIO
import json
import math
from pathlib import Path
import re
import time

from jav import cfg, pdf as pdfmod
from .contracts import ImageLocator, Issue, ReadLimits, SourceElement
from .isolation import exchange
from .limits import ReadFailure, limited
from .native import Reading
from .visual import add_layer, layer_for


def _hash_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class LocalOCR:
    executable: str
    tessdata: str
    languages: str
    psm: int
    oem: int
    fingerprint: str

    @classmethod
    def discover(cls) -> LocalOCR:
        from jav.ocr import native_exe
        executable = native_exe()
        if not executable:
            raise ReadFailure("unsupported", "needs_ocr", "Local Tesseract is not installed")
        settings = cfg.load("ocr")["tesseract"]
        languages = settings["lang"]
        if not re.fullmatch(r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*", languages):
            raise ReadFailure("unsupported", "needs_ocr", "Local OCR language configuration is invalid")
        folder = Path(__file__).resolve().parents[2] / settings["tessdata_dir"]
        models = [folder / f"{language}.traineddata" for language in languages.split("+")]
        if not all(path.is_file() for path in models):
            raise ReadFailure("unsupported", "needs_ocr", "A configured local OCR language model is missing")
        executable_path = Path(executable).resolve()
        # The executable, its adjacent native libraries and the actual language
        # bytes participate in identity, not merely a mutable version alias.
        files = [executable_path, *sorted(executable_path.parent.glob("*.dll")), *models]
        identity = {"files": [(p.name, _hash_file(p)) for p in files], "lang": languages,
                    "psm": settings["psm"], "oem": settings["oem"]}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return cls(str(executable_path), str(folder), languages, int(settings["psm"]), int(settings["oem"]), digest)

    def recognise(self, png: bytes, limits: ReadLimits, *, timeout: float) -> str:
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ReadFailure("corrupt", "corrupt", "OCR accepts only the reader's frozen PNG rasters")
        command = [self.executable, "stdin", "stdout", "--tessdata-dir", self.tessdata,
                   "-l", self.languages, "--psm", str(self.psm), "--oem", str(self.oem),
                   "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0"]
        output = exchange(command, png, limits, output_bound=limits.output_bytes, timeout=timeout)
        return output.decode("utf-8", errors="strict")


def _words(tsv: str, width: int, height: int, bound: int) -> list[dict]:
    from jav.ocr import parse_tsv
    rows = csv.DictReader(StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    required = {"level", "left", "top", "width", "height", "conf", "text"}
    if not required <= set(rows.fieldnames or ()):
        raise ValueError("OCR response is not a word TSV")
    count = 0
    for row in rows:
        if row["level"] != "5" or not row["text"].strip():
            continue
        count += 1
        limited(count > bound, "Recognised word limit exceeded")
        x, y, w, h = (int(row[key]) for key in ("left", "top", "width", "height"))
        confidence = float(row["conf"])
        if not (x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= width and y + h <= height
                and math.isfinite(confidence) and -1 <= confidence <= 100):
            raise ValueError("OCR word lies outside its frozen raster")
    # At 72 DPI the shared parser's point coordinates are the original pixels.
    words, _confidences = parse_tsv(tsv, dpi=72)
    return words


def finish(response: dict, source_sha: str, engine: LocalOCR | None, limits: ReadLimits, *,
           started: float, missing: str | None = None) -> dict:
    """Append recognition to one reading, preserving the original and raw TSV."""
    reading = Reading(response["parser"], response["mime"], limits)
    reading.elements = [SourceElement.model_validate_json(json.dumps(e)) for e in response["elements"]]
    reading.issues = [Issue.model_validate_json(json.dumps(i)) for i in response["issues"]]
    reading.children, reading.texts = response["children"], response["texts"]
    reading.source_layers = response.get("source_layers", {})
    reading.rasters = response.get("rasters", [])
    receipts, recognised = [], {}
    for raster in reading.rasters:
        element_id = raster["element_id"]
        receipt = {"raster_sha256": raster["sha256"], "element_id": element_id,
                   "engine_sha256": engine.fingerprint if engine else None}
        if engine is None:
            reading.issue("needs_ocr", missing or "Local recognition is unavailable", element_id)
            continue
        try:
            remaining = limits.wall_seconds - (time.monotonic() - started)
            limited(remaining <= 0, "Recognition exceeded the source reading deadline")
            png = base64.b64decode(raster["data"], validate=True)
            if hashlib.sha256(png).hexdigest() != raster["sha256"]:
                raise ValueError("Recognition raster content changed")
            cached = raster["sha256"] in recognised
            tsv = recognised.get(raster["sha256"])
            if tsv is None:
                tsv = engine.recognise(png, limits, timeout=remaining)
                limited(len(tsv.encode("utf-8")) > limits.output_bytes, "OCR TSV output limit exceeded")
                recognised[raster["sha256"]] = tsv
            receipt.update(tsv=tsv, reused=cached)
            words = _words(tsv, raster["width"], raster["height"], limits.visited_cells)
            if not words:
                reading.issue("unread_content", "Local OCR returned no text; blankness is not established", element_id)
                receipt["status"] = "empty"
                receipts.append(receipt)
                continue
            if raster["kind"] == "pdf":
                native_layer = next(iter(reading.source_layers.values()))
                sizes = [(p["width_pt"], p["height_pt"]) for p in native_layer["pages"]]
                pages = [[] for _ in sizes]
                width, height = sizes[raster["page"] - 1]
                for word in words:
                    word["x0"] *= width / raster["width"]
                    word["x1"] *= width / raster["width"]
                    word["top"] *= height / raster["height"]
                    word["bottom"] *= height / raster["height"]
                pages[raster["page"] - 1] = words
                pdfmod.build_layout(pages)
                add_layer(reading, layer_for(source_sha, pages, sizes, recognised=True))
            else:
                pdfmod.build_layout([words])
                groups = {}
                for word in words:
                    groups.setdefault(word["line_no"], []).append(word)
                for line in groups.values():
                    region = (int(min(w["x0"] for w in line)), int(min(w["top"] for w in line)),
                              int(max(w["x1"] for w in line)), int(max(w["bottom"] for w in line)))
                    reading.add("text", ImageLocator(image_sha256=source_sha, frame=raster["page"], region=region),
                                parent=element_id, text=" ".join(w["text"] for w in line))
            reading.issues = [i for i in reading.issues if not (i.element_id == element_id and i.code == "needs_ocr")]
            reading.elements = [e.model_copy(update={"availability": "read"}) if e.element_id == element_id else e
                                for e in reading.elements]
            receipt["status"] = "read"
        except ReadFailure as exc:
            reading.issue(exc.code, str(exc), element_id)
            receipt["status"] = exc.status
        except (ValueError, OSError, UnicodeError) as exc:
            reading.issue("corrupt", f"Local OCR result rejected ({type(exc).__name__})", element_id)
            receipt["status"] = "corrupt"
        receipts.append(receipt)
    return {**reading.output(), "ocr": receipts}
