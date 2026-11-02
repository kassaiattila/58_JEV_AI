"""OCR chain (BACKLOG 7, B5): PDF without text -> page image -> tesseract word boxes -> the shared line / cell builder.

Reuse (CLAUDE.md §3): follows the legacy sidecar (`10_AIFLOW_V4/sidecar/app/providers/tesseract_ocr.py`) - PDF to page
image (there pdf2image + poppler, here pypdfium2, already in the venv), tesseract `image_to_data` (here the CLI's TSV:
the same table, with word-level confidence), the mean word confidence as a quality signal. What is new: the word boxes
go through the same line and cell reconstruction as a PDF with a text layer (`jav/documents/pdf.py: build_layout`), so the
candidate finders, the JEV state and the verification questions work regardless of the source. The Hungarian + English
language packs came from the legacy sidecar's Docker image (`tools/tessdata`, tessdata_fast).

Engine (configs/ocr.json `engine`): `auto` = native tesseract (5.4 installed on the machine; ~7-10 s / page). 279: the
legacy sidecar's Docker image is no longer an engine, so the framework depends on nothing of the legacy project. With
no local engine, `NoOcrEngine`: the flow escalates straight to Azure when the run allows it (`ocr_with_escalation`),
otherwise it goes to the `needs_ocr` terminal with a to-do and does not crash. Azure Document Intelligence is the paid
engine (`jav/documents/azure_di.py`), reached only directly with this installation's own endpoint and key.

Disk cache `runs/ocr/<doc sha256>_<output-settings hash>_<tesseract version>.json` (PII, like the JEV cache): a second
golden run needs no OCR, and the determinism measurement does not repeat the OCR (OCR is deterministic; we measure JEV).
Since 076 the key covers only the settings that can change the recognised text (`output_settings`), not where things
are on the machine, time limits or notes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from decimal import ROUND_CEILING, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from jav.documents import pdf as pdfmod
from jav.core import cfg, jsonfile, trace
from jav.documents import azure_di, tessdata
from jav.core.config import AZURE_DI_MODEL, AZURE_USD_PER_PAGE, DATA_ROOT, PROJECT_ROOT, RUNS_DIR
from jav.documents.layout import LineLayout
from jav.documents.pdf import PdfText, build_layout, text_layer_ok
from jav.core.digest import file_sha256 as _sha256
from jav.core import observability  # 231 (E4): the calls are timed through one helper

log = logging.getLogger("jav.documents.ocr")

_CFG = cfg.load("ocr")  # the engine's own settings (227: the escalation rule is read when it applies, `ESCALATION`)


def config_hash() -> str:
    """The whole file's identity as it is loaded now (call log, quality signals; 227: asked, not copied at import)."""
    return cfg.config_hash("ocr")


# 076: settings that do not change what the OCR reads - where things are on this machine, time limits, the escalation
# rule (the engine that ran is in the key anyway), notes and the version record. `None` drops the whole section.
_NOT_OUTPUT: dict[str, tuple[str, ...] | None] = {
    "meta": None,
    "cache_dir": None,
    "escalation": None,
    # 278: where a fresh installation fetches the language packs from; the packs themselves are the ones in use
    "tesseract": ("timeout_s", "exe_candidates", "language_packs"),
    # 121: the REST API version is in the engine version instead (`engine_version`), so the earlier texts stay reusable;
    # 279: how a call is sent and checked (repeats, waits, the largest file) changes no recognised text; the legacy
    # sidecar's settings stay listed so that an older config's key is computed as it was (`rekey_cache`)
    "azure_di": ("timeout_s", "api_version", "poll_interval_s", "retries", "retry_max_wait_s", "max_file_mb",
                 "check_timeout_s", "sidecar_url", "data_root", "container_root"),
}

# 279: sections of an older config that belonged to an engine no longer in the framework (the legacy sidecar's Docker
# image). They chose which image the Docker engine ran and changed nothing another engine reads, so the texts cached
# under an older config's key that still had them are moved to the current key (`rekey_cache`) with no new OCR.
_RETIRED_SECTIONS = frozenset({"docker"})


def output_settings(conf: dict[str, Any]) -> dict[str, Any]:
    """The part of an OCR config that can change the recognised text (076): the input of the cache key."""
    out: dict[str, Any] = {}
    for key, value in conf.items():
        drop = _NOT_OUTPUT.get(key, ())
        if key == "note" or drop is None:
            continue
        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if k not in drop and k != "note"}
        out[key] = value
    return out


def output_hash(conf: dict[str, Any]) -> str:
    return hashlib.sha256(cfg.canonical(output_settings(conf)).encode("utf-8")).hexdigest()[: cfg.HASH_LEN]


CACHE_HASH = output_hash(_CFG)
_TESS = _CFG["tesseract"]
DPI: int = int(_CFG["dpi"])
CACHE_DIR = DATA_ROOT / _CFG["cache_dir"]  # 231 (E2): written data
LOW_CONF_WORD: float = float(_CFG["quality"]["low_conf_word"])
_TSV_LEVEL_WORD = "5"


class OcrUnavailableError(RuntimeError):
    """The recognition could not run (no engine, a failed engine, a blocked or failed Azure call, a page over a limit)."""


class NoOcrEngine(OcrUnavailableError):
    """279: no local engine on this machine (the native tesseract is not installed; the Docker engine is gone)."""


class OcrEngineFailed(OcrUnavailableError):
    """265 (code review AI-02): the OCR engine hung (over its time limit) or failed on a page."""


class AzureBlocked(OcrUnavailableError):
    """075: the Azure call was not made in a worker run. `reason`: `off` (the run has no Azure budget: the recipe switch
    is off), `budget_exceeded` (the page reservation does not fit the run's Azure budget) or `uncertain_attempt` (an
    earlier attempt for this document has an unknown outcome; it is not repeated automatically). 265 (code review
    TOOL-03): `no_budget` (outside a run or a command's budget: never paid for). 279: `not_configured` (this
    installation has no Azure endpoint and key; until 279 `unreachable`, which the legacy sidecar route could also
    raise), `switched_off` (the installation switched the provider off: `JAV_PROVIDERS_OFF`) and `not_sendable` (a file
    the service does not read, or over its size); both are found before anything is reserved."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"azure_di: {reason}")
        self.reason = reason


class PageTooLarge(OcrUnavailableError):
    """067: a page image at the recognition resolution would exceed the `input_limits.max_page_megapixels` limit of
    `configs/service.json`; the process raises a to-do (`ocr:unavailable:PageTooLarge`) and no page image is made."""


class PdfRenderLimit(OcrUnavailableError):
    """077: rendering the page images went over the isolated PDF reader's time or memory limit (`jav/documents/isolated_pdf.py`,
    `pdf_reader` in `configs/service.json`); the process raises a to-do (`ocr:unavailable:PdfRenderLimit`)."""


# --- engines -----------------------------------------------------------------------------------


def _expand(p: str) -> str:
    return os.path.expandvars(p.replace("%LOCALAPPDATA%", os.environ.get("LOCALAPPDATA", "")))


@lru_cache(maxsize=1)
def native_exe() -> str | None:
    """Path of the native tesseract from the config's candidates (PATH, then the usual Windows locations), or None."""
    for cand in _TESS["exe_candidates"]:
        cand = _expand(cand)
        found = shutil.which(cand) if os.sep not in cand and "/" not in cand else (cand if Path(cand).exists() else None)
        if found:
            return found
    return None


ENGINE_ENV = "JAV_OCR_ENGINE"  # runtime override (native / azure_di) for measurements; config = default


@lru_cache(maxsize=None)
def engine(want: str | None = None) -> str:
    """`native` | `azure_di`, by the requested engine (parameter > env > config `engine`: auto / native / azure_di)
    and by availability; `NoOcrEngine` if the local one is missing. `azure_di` is PAID: `auto` never picks it. 279: the
    legacy Docker engine is gone; asking for it is an error that says so."""
    want = want or os.environ.get(ENGINE_ENV) or _CFG["engine"]
    if want == "azure_di":
        return "azure_di"
    if want == "docker":
        raise NoOcrEngine("the Docker OCR engine (the legacy sidecar's image) was removed in 279; use native or azure_di")
    if want in ("auto", "native") and native_exe():
        return "native"
    raise NoOcrEngine(f"no OCR engine ({want}): the native tesseract is not installed ({', '.join(_TESS['exe_candidates'])};"
                      " docs/guides/SETUP.md section 3)")


# 121: the REST API version every Azure text cached before 121 was read with (the legacy sidecar's SDK 1.0.2)
_AZURE_FIRST_API = "2024-11-30"


@lru_cache(maxsize=None)
def engine_version(eng: str) -> str:
    """The engine's version line (part of the cache key: a different binary / model may give a different result).
    121: Azure's carries the REST API version only when it differs from the one the earlier texts were read with."""
    if eng == "azure_di":
        api = str(_CFG["azure_di"].get("api_version") or _AZURE_FIRST_API)
        return "azure_di prebuilt-read" + ("" if api == _AZURE_FIRST_API else f" {api}")
    out = subprocess.run([native_exe(), "--version"], capture_output=True, text=True, timeout=30)
    first = ((out.stdout or "") + (out.stderr or "")).strip().splitlines()
    return (first[0] if first else "tesseract ?").strip()


# --- Azure Document Intelligence (121: directly; 279: the only route) -----------------------------------------------


def azure_limits() -> azure_di.Limits:
    """279: how an analysis is sent (`configs/ocr.json` `azure_di`), read when asked."""
    az = _CFG["azure_di"]
    return azure_di.Limits(timeout_s=float(az["timeout_s"]), poll_s=float(az.get("poll_interval_s", 2.0)),
                           retries=int(az.get("retries", 3)), retry_max_wait_s=float(az.get("retry_max_wait_s", 30.0)),
                           max_file_mb=float(az.get("max_file_mb", 500.0)))


def azure_api_version() -> str:
    return str(_CFG["azure_di"].get("api_version") or _AZURE_FIRST_API)


def azure_page_plan(path: Path) -> tuple[int, str | None]:
    """279 (the owner's decision of 2026-11-02): Azure reads at most as many pages as the local recognition
    (`max_pages`, 12). Returns the pages reserved at the Azure price and the page range sent (None: the whole
    document, when it has no more pages than that). A document whose page count cannot be read (an image file, a PDF
    the isolated reader cannot open) reserves the limit and sends the range; an image has one page, or a few frames."""
    cap = int(_CFG["max_pages"])
    known = len(page_sizes(path)) if Path(path).suffix.lower() == ".pdf" else 0
    if 0 < known <= cap:
        return known, None
    return cap, f"1-{cap}"


def azure_ready(path: Path) -> None:
    """279: before anything is reserved or sent: this installation has its endpoint and key (`not_configured`), and
    the file is one the service reads, within its size (`not_sendable`)."""
    if not azure_di.configured():
        raise AzureBlocked("not_configured")
    try:
        azure_di.check_sendable(path, azure_limits())
    except azure_di.AzureDiRefused as exc:
        log.warning("Azure cannot read %s: %s", Path(path).name, exc)
        raise AzureBlocked("not_sendable") from exc


def azure_words(path: Path, *, pages: str | None = None) -> tuple[list[list[dict[str, Any]]], list[float], dict[str, Any]]:
    """The word boxes of an Azure recognition, in points (inch × 72), with confidence on a 0-100 scale (the same
    signals as tesseract), directly over the REST API (`jav/documents/azure_di.py`). The original recognition is kept
    (123). 279: `pages` is the page range the service analyses and bills."""
    try:
        found = azure_di.analyze(path, model=AZURE_DI_MODEL, api_version=azure_api_version(), limits=azure_limits(),
                                 pages=pages)
    except azure_di.AzureDiRefused as exc:
        # 279: nothing was analysed, so nothing is billed: the call log settles the reservation at 0
        failure = OcrUnavailableError(f"azure_di: {exc}")
        failure.known_outcome = _calls().Outcome(response=None, model=AZURE_DI_MODEL, cost_usd=Decimal(0))  # type: ignore[attr-defined]
        raise failure from exc
    except (azure_di.AzureDiError, azure_di.AzureOutcomeUnknown, OSError, ValueError) as exc:
        raise OcrUnavailableError(f"azure_di: {exc}") from exc
    save_recognition(found)  # 123: the original, for a verifiable handover to the native reader
    return azure_evidence_words(found)


def _calls():
    from jav.core import calls

    return calls


AZURE_PROVIDER = "azure_di"
# 121: `unavailable` (the call failed or its outcome is unknown); 279: `not_configured` (no endpoint and key here) and
# `not_sendable` (a file the service does not read); `unreachable` stays for the to-dos raised before 279
_ESCALATION_TODO = {"budget_exceeded", "uncertain_attempt", "unreachable", "unavailable", "no_budget",  # 265: no_budget
                    "not_configured", "not_sendable"}


def azure_recognise(path: Path) -> tuple[list[list[dict[str, Any]]], list[float], dict[str, Any]]:
    """075 (repeated security audit, S01): Azure DI through the shared call log. In a worker run
    (`jav.core.calls.current()`) the pages to be read are reserved at the Azure price from the run's Azure budget
    before the service is called; without an Azure budget, with too little of it, or after an attempt with an unknown
    outcome, the network is never reached (`AzureBlocked`). A repeated item gets the saved answer, not a second paid
    call. Every physical call also gets a ledger row, on the command-line path too. 279: an installation that switched
    the provider off is never sent anything (`switched_off`); at most `max_pages` pages are read (`azure_page_plan`); a
    start the service refused costs 0 in the call log."""
    from jav.core import providers, store

    calls = _calls()
    if not providers.enabled(AZURE_PROVIDER):
        raise AzureBlocked("switched_off")
    ctx = calls.current()
    ledger_run = (ctx.budget_scope if ctx else None) or "jav-ocr"
    if ctx is not None and ctx.budget_scope is not None and not calls.has_budget(ctx.budget_scope, AZURE_PROVIDER):
        raise AzureBlocked("off")
    if ctx is None:  # 265 (code review TOOL-03): outside a run or a budgeted command Azure is never paid for
        raise AzureBlocked("no_budget")
    azure_ready(path)  # 279: no endpoint and key, or a file the service does not read: no reservation, no call-log row
    n_pages, page_range = azure_page_plan(path)

    def physical() -> calls.Outcome:
        t0 = observability.start()
        try:
            pages, confs, meta = azure_words(path, pages=page_range)
        except OcrUnavailableError as exc:
            store.ledger_add(run_id=ledger_run, step="ocr_azure", provider=AZURE_PROVIDER, model=AZURE_DI_MODEL,
                             input_tokens=None, output_tokens=None, cost_usd=None, seconds=observability.since(t0),
                             config_hash=config_hash(), error=type(exc).__name__)
            raise
        cost = AZURE_USD_PER_PAGE * len(pages)
        model = meta.get("model_id") or AZURE_DI_MODEL
        store.ledger_add(run_id=ledger_run, step="ocr_azure", provider=AZURE_PROVIDER, model=model, input_tokens=None,
                         output_tokens=None, cost_usd=float(cost), seconds=observability.since(t0), config_hash=config_hash())
        return calls.Outcome(response={"pages": pages, "confs": confs, "meta": meta}, model=model, cost_usd=cost)

    max_cost = (AZURE_USD_PER_PAGE * n_pages).quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
    sha = _sha256(path)
    try:
        result = calls.invoke(run_id=ctx.budget_scope or "jav-ocr", step_id=f"{AZURE_PROVIDER}:ocr:{sha[:16]}", provider=AZURE_PROVIDER,
                              model=AZURE_DI_MODEL, max_cost_usd=max_cost, budget_scope=ctx.budget_scope, request_hash=sha, fn=physical)
    except calls.BudgetExceeded as exc:
        raise AzureBlocked("budget_exceeded") from exc
    except calls.UncertainAttempt as exc:
        raise AzureBlocked("uncertain_attempt") from exc
    out = result.response
    return out["pages"], out["confs"], out["meta"]


def escalation_review_reasons(signals: dict[str, Any] | None) -> list[str]:
    """075: a to-do when weak local text went on because the Azure escalation was blocked by the budget or by an
    uncertain earlier attempt; not when the recipe switch is off (the user chose local recognition). 121: also when
    Azure could not be reached for the document or the call failed."""
    reason = (signals or {}).get("escalation_blocked")
    return [f"ocr:escalation_blocked:{reason}"] if reason in _ESCALATION_TODO else []


AZURE_RECOGNITION_KIND = "azure_recognition"


def recognition_digest(evidence: dict[str, Any]) -> str:
    """123: the sha256 of an original Azure recognition's canonical JSON (sorted keys, no spaces)."""
    canonical = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def save_recognition(evidence: dict[str, Any]) -> str:
    """123: keep the original recognition (word polygons, page size, unit, angle) once, under its digest, so that a
    later step can verify where each recognised word came from. Returns the digest."""
    from jav.core import store

    sha = recognition_digest(evidence)
    store.save_artifact(AZURE_RECOGNITION_KIND, sha, evidence)
    return sha


def load_recognition(sha: str) -> dict[str, Any]:
    """123: a kept original recognition; KeyError when it is missing, ValueError when its content no longer matches
    its digest."""
    from jav.core import store

    evidence = store.load_artifact(AZURE_RECOGNITION_KIND, sha)
    if evidence is None:
        raise KeyError(sha)
    if recognition_digest(evidence) != sha:
        raise ValueError("The kept Azure recognition does not match its digest")
    return evidence


def azure_evidence_words(evidence: dict[str, Any]) -> tuple[list[list[dict[str, Any]]], list[float], dict[str, Any]]:
    pages: list[list[dict[str, Any]]] = []
    confs: list[float] = []
    for page in evidence["pages"]:
        scale = 72.0 if page.get("unit") == "inch" else 1.0
        words: list[dict[str, Any]] = []
        for w in page["words"]:
            poly = w.get("polygon") or []
            text = pdfmod.normalize_dashes((w.get("content") or "").strip())  # 066 Á33
            if len(poly) < 8 or not text:
                continue
            xs, ys = poly[0::2], poly[1::2]
            conf = float(w["confidence"]) * 100 if w.get("confidence") is not None else -1.0
            words.append({"text": text, "x0": min(xs) * scale, "x1": max(xs) * scale, "top": min(ys) * scale, "bottom": max(ys) * scale, "conf": conf})
            if conf >= 0:
                confs.append(conf)
        pages.append(words)
    meta = {"model_id": evidence.get("model_id"), "api_version": evidence.get("api_version"),
            "recognition_sha256": recognition_digest(evidence)}
    return pages, confs, meta


def _tesseract_args(psm: int | None = None) -> list[str]:
    return ["-l", _TESS["lang"], "--psm", str(psm if psm is not None else _TESS["psm"]), "--oem", str(_TESS["oem"]),
            "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0"]


def tessdata_dir() -> Path:
    """The language data of the native recogniser: `JAV_TESSDATA_DIR` when set (153, review F2: a second checkout or a
    worktree has no `tools/tessdata` of its own), else the configured folder of this checkout."""
    return Path(os.environ["JAV_TESSDATA_DIR"]) if os.environ.get("JAV_TESSDATA_DIR") else PROJECT_ROOT / _TESS["tessdata_dir"]


def _run_tesseract(png: Path, out_base: Path, *, psm: int | None = None, eng: str = "native") -> str:
    """OCR of one page image with the native tesseract (`--tessdata-dir tools/tessdata`); returns the TSV text. 279:
    `eng` is kept for the callers' signature; the Docker engine is gone, so it is always the native one."""
    cmd = [native_exe(), str(png), str(out_base), "--tessdata-dir", str(tessdata_dir()), *_tesseract_args(psm)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=float(_TESS["timeout_s"]), check=True)
        return Path(str(out_base) + ".tsv").read_text(encoding="utf-8")
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as exc:
        # 265 (code review AI-02): a hung or failed engine is an unavailability (`ocr:unavailable:OcrEngineFailed`, the
        # item goes on with a to-do), not a general error retried twice
        raise OcrEngineFailed(f"the OCR engine ({eng}) failed on {png.name}: {type(exc).__name__}"
                              f"{_missing_packs_hint()}") from exc


def _missing_packs_hint() -> str:
    """278: a fresh installation's commonest cause of a failed native run, named in the failure."""
    lacking = tessdata.missing(tessdata_dir())
    if not lacking:
        return ""
    return (f"; the language pack(s) {', '.join(lacking)} are missing from {tessdata_dir()} "
            "(python -m jav.cli ocr --fetch-langs)")


# --- page images ------------------------------------------------------------------------------


def render_pages(path: str | Path, out_dir: Path, *, dpi: int = DPI, max_pages: int | None = None) -> list[Path]:
    """PDF -> page images (PNG) with pypdfium2 (no poppler). Greyscale by default, `dpi` resolution; at most
    `max_pages` pages. 077: rendered in the isolated PDF reader (`jav/documents/isolated_pdf.py`); over its time or memory limit
    `PdfRenderLimit` (a to-do, like `PageTooLarge`)."""
    from jav.documents import isolated_pdf

    max_pages = max_pages or int(_CFG["max_pages"])
    max_mp = pdfmod.input_limits().max_page_megapixels
    try:
        result = isolated_pdf.run(isolated_pdf.render_pages, kind="render", path=str(path), out_dir=str(out_dir), dpi=dpi,
                                  max_pages=max_pages, grayscale=bool(_CFG.get("grayscale", True)), max_megapixels=max_mp)
    except isolated_pdf.PdfReaderLimit as exc:
        raise PdfRenderLimit(str(exc)) from exc
    if "too_large" in result:
        page, w, h = result["too_large"]
        raise PageTooLarge(f"page {page} ({w:.0f} x {h:.0f} pt) is over {max_mp:g} MP at {dpi} dpi")
    return [Path(p) for p in result["pages"]]


def page_sizes(path: str | Path) -> list[tuple[float, float]]:
    """Page sizes in points (pypdfium2), for normalising the word layer; the same reference for every OCR engine.
    Unreadable PDF (e.g. an image file, corrupt, or over the isolated reader's limits): [] — no word layer, the OCR
    result still stands."""
    from jav.documents import isolated_pdf

    try:
        sizes = isolated_pdf.run(isolated_pdf.page_sizes, kind="read", path=str(path))
    except (isolated_pdf.PdfReaderLimit, isolated_pdf.PdfReaderError) as exc:
        log.warning("no page sizes for %s: %s", Path(path).name, exc)
        return []
    return [tuple(s) for s in sizes] if sizes else []


# --- TSV -> word boxes (in points) ---------------------------------------------------------------


def parse_tsv(tsv_text: str, *, dpi: int = DPI) -> tuple[list[dict[str, Any]], list[float]]:
    """Tesseract TSV word rows (`level` 5) -> `{text, x0, x1, top, bottom, conf}` in points (72 / dpi), plus the
    confidences."""
    scale = 72.0 / dpi
    words: list[dict[str, Any]] = []
    confs: list[float] = []
    for r in csv.DictReader(io.StringIO(tsv_text), delimiter="\t", quoting=csv.QUOTE_NONE):
        if r.get("level") != _TSV_LEVEL_WORD:
            continue
        text = pdfmod.normalize_dashes((r.get("text") or "").strip())  # 066 Á33
        if not text:
            continue
        try:
            left, top, width, height, conf = int(r["left"]), int(r["top"]), int(r["width"]), int(r["height"]), float(r["conf"])
        except (KeyError, ValueError):
            continue
        words.append({"text": text, "x0": left * scale, "x1": (left + width) * scale, "top": top * scale, "bottom": (top + height) * scale, "conf": conf})
        if conf >= 0:
            confs.append(conf)
    return words, confs


def confidence_signals(confs: list[float]) -> dict[str, float]:
    """The recognition's mean word confidence (0-1) and the share of weak words, from word confidences on 0-100."""
    return {"mean_conf": round(statistics.mean(confs) / 100.0, 4) if confs else 0.0,
            "low_conf_ratio": round(sum(1 for c in confs if c < LOW_CONF_WORD) / len(confs), 4) if confs else 1.0}


def line_tolerance(pages: list[list[dict[str, Any]]]) -> float:
    heights = [w["bottom"] - w["top"] for page in pages for w in page if w["bottom"] > w["top"]]
    if not heights:
        return 3.0
    return max(3.0, 0.45 * statistics.median(heights))  # skewed scans: line threshold ~ half the letter height


# --- cache + entry point -------------------------------------------------------------------------


def cache_key(path: Path, eng: str) -> str:
    ver = engine_version(eng).replace(" ", "_").replace("/", "_")[:40]
    return f"{_sha256(path)}_{CACHE_HASH}_{ver}"


def rekey_cache(old_conf: dict[str, Any], cache_dir: Path | None = None) -> int:
    """076: a one-off move of the cache files written under an older config's key (up to `ocr.json` 1.0.0 the key held
    the whole file's hash) to the current key. Allowed only when the older config's output settings equal the current
    ones: then the cached text is exactly what a new OCR would read, and nothing is read or paid for again. An existing
    file under the new key is never overwritten; a second run moves nothing. Returns the number of files moved. 279: a
    retired engine's section (`_RETIRED_SECTIONS`) is left out of the comparison, so dropping the Docker engine keeps
    every native and Azure text; the Docker engine's own texts are keyed by its version and are never read again."""

    def current(conf: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in output_settings(conf).items() if k not in _RETIRED_SECTIONS}

    if current(old_conf) != current(_CFG):
        raise ValueError("the older OCR config differs in a setting that changes the recognised text; its cache is not reused")
    cache_dir = CACHE_DIR if cache_dir is None else cache_dir
    whole = hashlib.sha256(("ocr" + cfg.canonical(old_conf)).encode("utf-8")).hexdigest()[: cfg.HASH_LEN]  # = cfg.config_hash
    moved = 0
    for old_key in (whole, output_hash(old_conf)):
        if old_key == CACHE_HASH:
            continue
        for f in sorted(cache_dir.glob(f"*_{old_key}_*.json")):
            target = f.with_name(f.name.replace(f"_{old_key}_", f"_{CACHE_HASH}_", 1))
            if not target.exists():
                f.rename(target)
                moved += 1
    return moved


def _to_pdftext(path: Path, data: dict[str, Any], *, cached: bool) -> PdfText:
    layout = [LineLayout.model_validate(ln) for ln in data["layout"]]
    lines = [ln.text for ln in layout]
    text = "\n".join(lines)
    ok = text_layer_ok(text)
    signals = {**data["signals"], "cached": cached, "engine": data["engine"], "engine_version": data["engine_version"], "config_hash": config_hash()}
    # 045: old cache files have no word or page-size data; the word layer is then empty (no boxes), same lines
    return PdfText(path=str(path), text=text, lines=lines, layout=layout, page_count=data["page_count"], has_text_layer=False,
                   text_source="ocr" if ok else None, ocr=signals, words=data.get("words") or [],
                   page_sizes=[tuple(s) for s in data.get("page_sizes") or []])


def _note_azure_reuse(path: Path, key: str) -> None:
    """082: in a worker run, text taken from an earlier Azure recognition is a ledger row at 0 USD under the item's
    flow identifier (`<run>:<fingerprint16>`; a document's identifier is its content fingerprint), so the cost view
    counts it among the answers reused from earlier, as it does an earlier JEV answer. Outside a run (measurements, the
    command line) nothing is written."""
    from jav.core import store
    from jav.core import calls

    ctx = calls.current()
    if ctx is None or ctx.budget_scope is None:
        return
    store.ledger_add(run_id=f"{ctx.budget_scope}:{_sha256(path)[:16]}", step="ocr_azure", provider=AZURE_PROVIDER,
                     model=AZURE_DI_MODEL, input_tokens=None, output_tokens=None, cost_usd=0.0, seconds=0.0, cached=True,
                     cache_key=key, config_hash=config_hash())


def ocr_pdf(
    path: str | Path, *, page_count: int | None = None, use_cache: bool = True, psm: int | None = None, engine_name: str | None = None,
    max_pages: int | None = None,
) -> PdfText:
    """OCR of one PDF: from the cache if present; otherwise page images + tesseract per page (or Azure DI, directly)
    + the shared layout builder. `has_text_layer` stays False (a fact), `text_source="ocr"` if the recognised
    text is usable; the `ocr` dict holds the quality signals. The engine is part of the cache key: a new engine means a
    new OCR."""
    path = Path(path)
    eng = engine(engine_name)  # OcrUnavailableError if there is no engine
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = cache_key(path, eng) + (f"_psm{psm}" if psm is not None and eng != "azure_di" else "")
    # 231 (U-A2): more pages than a processed document is recognised on is another result (its own cache entry)
    wider = max_pages is not None and max_pages > int(_CFG["max_pages"]) and eng != "azure_di"
    key += f"_pages{max_pages}" if wider else ""
    cache_file = CACHE_DIR / f"{key}.json"
    # 265 (code review AI-04): a broken cache file reads as missing (recognised again), never failing every later item
    cached = jsonfile.read_tolerant(cache_file) if use_cache else None
    if isinstance(cached, dict):
        if not cached.get("words") and eng != "azure_di":
            cached = _backfill_words(path, cached, cache_file, psm=psm, eng=eng)
        if eng == "azure_di":
            _note_azure_reuse(path, key)
        return _to_pdftext(path, cached, cached=True)

    t0 = time.perf_counter()
    extra: dict[str, Any] = {}
    if eng == "azure_di":
        pages, all_conf, extra = azure_recognise(path)
        n_pages = len(pages)
    else:
        with tempfile.TemporaryDirectory(prefix="jav_ocr_") as tmp:
            tmp_dir = Path(tmp)
            pngs = render_pages(path, tmp_dir, max_pages=max_pages if wider else None)
            pages = []
            all_conf = []
            for png in pngs:
                tsv = _run_tesseract(png, tmp_dir / png.stem, psm=psm, eng=eng)
                words, confs = parse_tsv(tsv)
                pages.append(words)
                all_conf.extend(confs)
        n_pages = len(pngs)
    layout = build_layout(pages, y_tol=line_tolerance(pages))
    n_words = sum(len(p) for p in pages)
    signals = {
        **confidence_signals(all_conf),
        "words": n_words,
        "pages_ocr": n_pages,
        "dpi": DPI if eng != "azure_di" else None,
        "psm": (psm if psm is not None else int(_TESS["psm"])) if eng != "azure_di" else None,
        "seconds": round(time.perf_counter() - t0, 2),
        **extra,
    }
    data = {
        "path": str(path), "page_count": page_count if page_count is not None else n_pages, "engine": eng,
        "engine_version": engine_version(eng), "config_hash": config_hash(), "signals": signals,
        "layout": [ln.model_dump() for ln in layout],
        "words": pages,  # 045: word boxes in points, with the line number (set by build_layout) - for the word layer
        "page_sizes": page_sizes(path),
    }
    if use_cache:
        jsonfile.write_atomic(cache_file, data)  # 265 (AI-04): whole or not at all
    return _to_pdftext(path, data, cached=False)


def _backfill_words(path: Path, cached: dict[str, Any], cache_file: Path, *, psm: int | None, eng: str) -> dict[str, Any]:
    """048: a pre-045 cache entry has no word or page-size data, so such a document had no word layer (no boxes, no
    paging to the fields in the UI). The local engine is free and deterministic: we rerun it and write the word data
    into the entry ONLY if the re-read lines match the stored ones letter for letter - so the text (and with it the
    cache key of the earlier JEV requests) does not change. On a mismatch the entry stays unchanged."""
    fresh = ocr_pdf(path, page_count=cached.get("page_count"), use_cache=False, psm=psm, engine_name=eng)
    if fresh.lines != [ln["text"] for ln in cached["layout"]]:
        return cached
    cached = {**cached, "words": fresh.words, "page_sizes": [list(s) for s in fresh.page_sizes], "words_backfilled": True}
    jsonfile.write_atomic(cache_file, cached)  # 265 (AI-04)
    return cached


# 227 (plan R3b): the escalation is a decision rule, read through the loader when it applies (`cfg.Section`); the
# engine's own settings above stay as loaded (they change the text and its cache key)
ESCALATION = cfg.Section("ocr", "escalation")


def ocr_with_escalation(path: str | Path, *, page_count: int | None = None, use_cache: bool = True) -> tuple[PdfText, bool]:
    """The flow's OCR step: the default engine (auto / env); if the result is weak by the policy's `ocr.escalate_*`
    thresholds and escalation is enabled (configs/ocr.json), the text of the more accurate, paid engine (`azure_di`)
    goes on. Returns (PdfText, whether escalated). If escalation is unavailable, the local result stays; 121: the
    reason is kept in the signals (`escalation_blocked`), and the flow raises a to-do for it (`escalation_review_reasons`).
    279: with no local engine on the machine, Azure stands in when the rule allows it (`_without_local`)."""
    try:
        first = ocr_pdf(path, page_count=page_count, use_cache=use_cache)
    except NoOcrEngine as missing:
        return _without_local(path, page_count=page_count, use_cache=use_cache, missing=missing)
    if first.ocr is None:
        return first, False
    # 218 (P3b): what the decision reads goes with the text that goes on (`escalation`), traced with the document's save
    inputs: dict[str, Any] = {"forced": bool(os.environ.get(ENGINE_ENV)), "enabled": bool(ESCALATION.get("enabled")),
                              "engine": ESCALATION.get("engine"), "attempt": None,
                              "first": {k: first.ocr.get(k) for k in ("engine", "mean_conf", "low_conf_ratio")}}
    first.ocr["escalation"] = inputs
    if not escalation_rule(inputs)["attempt"]:
        return first, False
    try:
        second = ocr_pdf(path, page_count=page_count, use_cache=use_cache, engine_name=ESCALATION["engine"])
    except AzureBlocked as exc:  # 075: kept in the signals; the flow raises a to-do for a budget or uncertainty block
        first.ocr["escalation_blocked"] = exc.reason
        inputs["attempt"] = {"blocked": exc.reason}
        return first, False
    except OcrUnavailableError:  # 121: the call failed or its outcome is unknown; before 121 this was silent
        first.ocr["escalation_blocked"] = "unavailable"
        inputs["attempt"] = {"blocked": "unavailable"}
        return first, False
    inputs["attempt"] = {"read": bool(second.ocr), "mean_conf": second.ocr.get("mean_conf") if second.ocr else None}
    if escalation_rule(inputs)["text"] == "escalated":
        second.ocr["escalated_from"] = first.ocr.get("engine")
        second.ocr["escalation"] = inputs
        if not second.words and first.words:
            # 049: the old Azure cache has no word data (calling it again is paid). The text stays Azure's; the word
            # layer (boxes, paging to the field) is built from the local OCR's word positions; anything not found there
            # gets no box.
            second.words, second.page_sizes = first.words, first.page_sizes
            second.ocr["words_from"] = first.ocr.get("engine")
        return second, True
    return first, False


def _without_local(path: str | Path, *, page_count: int | None, use_cache: bool, missing: NoOcrEngine) -> tuple[PdfText, bool]:
    """279: no local engine on this machine. A missing local text is the weakest there is, so the rule asks the paid
    engine at once when it would escalate at all (escalation on, no engine forced), within the run's Azure budget as
    always. If Azure is blocked or fails, the missing engine stands (an `ocr:unavailable:NoOcrEngine` to-do) and the
    block's reason goes to the log."""
    inputs: dict[str, Any] = {"forced": bool(os.environ.get(ENGINE_ENV)), "enabled": bool(ESCALATION.get("enabled")),
                              "engine": ESCALATION.get("engine"), "attempt": None,
                              "first": {"engine": None, "mean_conf": None, "low_conf_ratio": None}}
    if not escalation_rule(inputs)["attempt"]:
        raise missing
    try:
        second = ocr_pdf(path, page_count=page_count, use_cache=use_cache, engine_name=ESCALATION["engine"])
    except OcrUnavailableError as exc:
        log.warning("no local OCR engine, and Azure could not stand in for %s: %s", Path(path).name, exc)
        raise missing from exc
    inputs["attempt"] = {"read": bool(second.ocr), "mean_conf": second.ocr.get("mean_conf") if second.ocr else None}
    if second.ocr is not None:
        second.ocr["escalated_from"] = None
        second.ocr["escalation"] = inputs
    return second, True


# --- 218 (plan P3 P3b): the escalation as a pure rule, traced with the document's save --------------------------------

ESCALATION_POINT = "ocr.escalation"


def quality_limits() -> dict[str, float]:
    """The OCR quality thresholds (`configs/policy.json` `ocr`: the to-dos of weak text, the escalation), read when
    asked. 227 (plan R3c): this section of the shared rule file is read here only; the decision rules
    (`jav.ai.policy.ocr_review_reasons`) ask this module."""
    return {k: float(v) for k, v in cfg.load("policy").get("ocr", {}).items()}


def ocr_should_escalate(mean_conf: float | None, low_conf_ratio: float | None) -> bool:
    """Weak local OCR (below / above the policy's `ocr.escalate_*` thresholds) -> switch to the more accurate, paid
    engine (configs/ocr.json `escalation`); the decision is data, the signals stay raw in the state. 227 (plan R3c):
    this layer's rule (until then the AI layer's)."""
    limits = quality_limits()
    if mean_conf is not None and mean_conf < limits.get("escalate_min_mean_conf", 0.0):
        return True
    return low_conf_ratio is not None and low_conf_ratio > limits.get("escalate_max_low_conf_ratio", 1.0)


def escalation_rule(inputs: dict[str, Any]) -> dict[str, Any]:
    """Whether a document's local OCR text is asked of the more accurate, paid engine, and which text goes on: not
    when an engine is forced for a measurement (`forced`), escalation is off (`configs/ocr.json` `escalation`) or the
    local text came from the paid engine already; otherwise when the local text is weak by the policy's
    `ocr.escalate_*` thresholds. The attempt's outcome is an input (`attempt`): blocked (the run's budget, an uncertain
    earlier attempt, unreachable: the local text goes on, with a to-do for a block that is not the recipe switch), or
    read: the paid text goes on unless it is weaker. `text` is None when the rule asks for an attempt that was not made
    (a changed rule replayed on a document the earlier one did not escalate). 279: no local text at all (no local
    engine on the machine, `first.engine` None) is asked like a weak one."""
    first, tried = inputs["first"], inputs["attempt"]
    no_local = first["engine"] is None
    attempt = (not inputs["forced"] and inputs["enabled"]
               and (no_local or (first["engine"] != inputs["engine"]
                                 and ocr_should_escalate(first["mean_conf"], first["low_conf_ratio"]))))
    if not attempt:
        return {"attempt": False, "text": "local", "reasons": []}
    if tried is None:
        return {"attempt": True, "text": None, "reasons": []}
    if "blocked" in tried:
        return {"attempt": True, "text": "local", "reasons": escalation_review_reasons({"escalation_blocked": tried["blocked"]})}
    better = tried["read"] and (tried["mean_conf"] or 0) >= (first["mean_conf"] or 0)
    return {"attempt": True, "text": "escalated" if better else "local", "reasons": []}


ESCALATION_KEYS = {"ocr.json": ("escalation.enabled", "escalation.engine"),
                   "policy.json": ("ocr.escalate_min_mean_conf", "ocr.escalate_max_low_conf_ratio")}


def trace_escalation(c: Any, inputs: dict[str, Any] | None, *, doc_id: str, run_id: str | None) -> None:
    """The escalation's decision in the caller's write transaction (the document's save); nothing for a text that was
    not recognised here (a text layer, no engine, or a state recognised before the trace)."""
    if inputs is not None:
        trace.record_in(c, ESCALATION_POINT, subject=("document", doc_id), inputs=inputs, outcome=escalation_rule(inputs),
                        keys=ESCALATION_KEYS, run_id=run_id)


trace.register(trace.Point(
    ESCALATION_POINT, owner=__name__, files=("ocr.json", "policy.json"), rule=escalation_rule,
    what="whether a document's weak local OCR text is asked of the more accurate, paid engine, which text goes on, and "
         "the to-do of an escalation the run's budget or an uncertain earlier attempt blocked",
    not_for="the recognition itself (the engines' confidences are inputs) or the to-dos of the text that goes on (weak "
            "words, pages left out: the extraction's earlier to-dos)"))


AZURE_CHECK_FILE = RUNS_DIR / "azure-check.json"  # 279: the last free check of the endpoint and key (no secret in it)


def check_azure() -> dict[str, Any]:
    """279: the free check of this installation's Azure endpoint and key (`azure_di.check`: the resource's details,
    nothing analysed, not billed, not in the call log); its outcome is kept for the status views. A provider switched
    off is not asked."""
    from datetime import datetime, timezone

    from jav.core import providers

    if not providers.enabled(AZURE_PROVIDER):
        found = azure_di.CheckResult(False, "switched_off", azure_di.endpoint_host())
    else:
        found = azure_di.check(api_version=azure_api_version(), timeout_s=float(_CFG["azure_di"].get("check_timeout_s", 15)))
    out = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": found.ok, "reason": found.reason,
           "host": found.host, "custom_models": found.custom_models}
    jsonfile.write_atomic(AZURE_CHECK_FILE, out)
    log.info("Azure check: %s", "ok" if found.ok else found.reason)
    return out


def azure_status() -> dict[str, Any]:
    """279: this installation's Azure state, without a call and without the key: whether the endpoint and key are
    set, whether the provider is switched on, the endpoint's host, the model, the API version, the page limit, the
    price and the last free check (`check_azure`; None before the first)."""
    from jav.core import providers

    last = jsonfile.read_tolerant(AZURE_CHECK_FILE)
    return {"configured": azure_di.configured(), "enabled": providers.enabled(AZURE_PROVIDER),
            "host": azure_di.endpoint_host(), "model": AZURE_DI_MODEL, "api_version": azure_api_version(),
            "max_pages": int(_CFG["max_pages"]), "usd_per_page": str(AZURE_USD_PER_PAGE),
            "escalation": bool(ESCALATION.get("enabled")), "last_check": last if isinstance(last, dict) else None}


def status() -> dict[str, Any]:
    """Admin / preflight: which engine, version, language packs, cache size; 279: and the Azure state."""
    out: dict[str, Any] = {"config_version": cfg.version("ocr"), "config_hash": config_hash(), "native_exe": native_exe(),
                           "azure_direct": azure_di.configured(),  # 121: kept for its readers; the same as azure.configured
                           "azure": azure_status(), "engine_env": os.environ.get(ENGINE_ENV)}
    try:
        out["engine"] = engine()
        out["engine_version"] = engine_version(out["engine"])
    except OcrUnavailableError as exc:
        out["engine"] = None
        out["error"] = str(exc)
    packs = tessdata.state(tessdata_dir())  # 278: the required ones missing, and pinned ones that differ
    out["tessdata"] = packs["present"]
    out["tessdata_dir"] = packs["folder"]
    out["tessdata_missing"] = packs["missing"]
    out["tessdata_differs"] = packs["differs"]
    out["cache_files"] = len(list(CACHE_DIR.glob("*.json"))) if CACHE_DIR.exists() else 0
    return out


if __name__ == "__main__":  # quick manual test: python -m jav.documents.ocr <pdf>
    r = ocr_pdf(sys.argv[1], use_cache=False)
    print(json.dumps(r.ocr, ensure_ascii=False))
    print("\n".join(r.lines[:80]))
