"""OCR chain (BACKLOG 7, B5): PDF without text -> page image -> tesseract word boxes -> the shared line / cell builder.

Reuse (CLAUDE.md §3): follows the legacy sidecar (`10_AIFLOW_V4/sidecar/app/providers/tesseract_ocr.py`) - PDF to page
image (there pdf2image + poppler, here pypdfium2, already in the venv), tesseract `image_to_data` (here the CLI's TSV:
the same table, with word-level confidence), the mean word confidence as a quality signal. What is new: the word boxes
go through the same line and cell reconstruction as a PDF with a text layer (`jav/pdf.py: build_layout`), so the
candidate finders, the JEV state and the verification questions work regardless of the source. The Hungarian + English
language packs came from the legacy sidecar's Docker image (`tools/tessdata`, tessdata_fast).

Engine (configs/ocr.json `engine`): `auto` = native tesseract if present (5.4 installed on the machine; ~7-10 s / page),
otherwise the legacy sidecar image via `docker run` (the same command in the container; ~30× slower on this machine,
because the Docker VM is shared with many other containers) - if neither exists, `OcrUnavailableError` (the flow goes
to the `needs_ocr` terminal and does not crash).

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
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import ROUND_CEILING, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from jav import cfg, pdf as pdfmod
from jav.adapters import azure_di
from jav.config import AZURE_DI_MODEL, AZURE_USD_PER_PAGE, OLD_DATA_ROOT, PROJECT_ROOT
from jav.models import LineLayout
from jav.pdf import PdfText, build_layout, text_layer_ok

log = logging.getLogger("jav.ocr")

_CFG = cfg.load("ocr")
CONFIG_HASH = cfg.config_hash("ocr")  # the whole file's identity (call log, quality signals)

# 076: settings that do not change what the OCR reads - where things are on this machine, time limits, the escalation
# rule (the engine that ran is in the key anyway), notes and the version record. `None` drops the whole section.
_NOT_OUTPUT: dict[str, tuple[str, ...] | None] = {
    "meta": None,
    "cache_dir": None,
    "escalation": None,
    "tesseract": ("timeout_s", "exe_candidates"),
    # 121: the REST API version is in the engine version instead (`engine_version`), so the earlier texts stay reusable
    "azure_di": ("sidecar_url", "data_root", "container_root", "timeout_s", "api_version", "poll_interval_s"),
}


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
CACHE_DIR = PROJECT_ROOT / _CFG["cache_dir"]
LOW_CONF_WORD: float = float(_CFG["quality"]["low_conf_word"])
_TSV_LEVEL_WORD = "5"


class OcrUnavailableError(RuntimeError):
    """No runnable OCR engine (neither native tesseract nor the Docker image)."""


class AzureBlocked(OcrUnavailableError):
    """075: the Azure call was not made in a worker run. `reason`: `off` (the run has no Azure budget: the recipe switch
    is off), `budget_exceeded` (the page reservation does not fit the run's Azure budget) or `uncertain_attempt` (an
    earlier attempt for this document has an unknown outcome; it is not repeated automatically). 121: `unreachable`
    (no direct Azure endpoint and key, and the legacy sidecar cannot see the document); this one is raised outside a
    worker run too."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"azure_di: {reason}")
        self.reason = reason


class PageTooLarge(OcrUnavailableError):
    """067: a page image at the recognition resolution would exceed the `input_limits.max_page_megapixels` limit of
    `configs/service.json`; the process raises a to-do (`ocr:unavailable:PageTooLarge`) and no page image is made."""


class PdfRenderLimit(OcrUnavailableError):
    """077: rendering the page images went over the isolated PDF reader's time or memory limit (`jav/isolated_pdf.py`,
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


@lru_cache(maxsize=1)
def docker_available() -> bool:
    if _CFG["engine"] == "native" or not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(["docker", "image", "inspect", _CFG["docker"]["image"]], capture_output=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


ENGINE_ENV = "JAV_OCR_ENGINE"  # runtime override (native / docker / azure_di) for measurements; config = default


@lru_cache(maxsize=None)
def engine(want: str | None = None) -> str:
    """`native` | `docker` | `azure_di`, by the requested engine (parameter > env > config `engine`: auto / native /
    docker / azure_di) and by availability; an error if none works. `azure_di` is PAID: `auto` never picks it."""
    want = want or os.environ.get(ENGINE_ENV) or _CFG["engine"]
    if want == "azure_di":
        return "azure_di"
    if want in ("auto", "native") and native_exe():
        return "native"
    if want in ("auto", "docker") and docker_available():
        return "docker"
    raise OcrUnavailableError(
        f"nincs OCR-motor ({want}): natív tesseract ({', '.join(_TESS['exe_candidates'])}) és a Docker-kép ({_CFG['docker']['image']}) sem elérhető"
    )


# 121: the REST API version every Azure text cached before 121 was read with (the legacy sidecar's SDK 1.0.2)
_AZURE_FIRST_API = "2024-11-30"


@lru_cache(maxsize=None)
def engine_version(eng: str) -> str:
    """The engine's version line (part of the cache key: a different binary / model may give a different result).
    121: Azure's carries the REST API version only when it differs from the one the earlier texts were read with."""
    if eng == "azure_di":
        api = str(_CFG["azure_di"].get("api_version") or _AZURE_FIRST_API)
        return "azure_di prebuilt-read" + ("" if api == _AZURE_FIRST_API else f" {api}")
    if eng == "native":
        out = subprocess.run([native_exe(), "--version"], capture_output=True, text=True, timeout=30)
    else:
        out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "tesseract", _CFG["docker"]["image"], "--version"], capture_output=True, text=True, timeout=120)
    first = ((out.stdout or "") + (out.stderr or "")).strip().splitlines()
    return (first[0] if first else "tesseract ?").strip()


# --- Azure Document Intelligence via the legacy sidecar ----------------------------------------------

# The original a source instance was copied from, with the fingerprint recorded when it was added (see `azure_alias`).
_AZURE_ALIAS: ContextVar[tuple[Path, str] | None] = ContextVar("jav_azure_alias", default=None)


@contextmanager
def azure_alias(original: str | None, sha256: str) -> Iterator[None]:
    """While a flow reads a document from its source instance (under `store/sources/`, which the sidecar cannot see),
    the Azure call may use the original instead, exactly as before source instances: only if the original lies under
    the sidecar's data folder and its content is still the one that was added. `original=None`: no alias."""
    token = _AZURE_ALIAS.set((Path(original), sha256) if original else None)
    try:
        yield
    finally:
        _AZURE_ALIAS.reset(token)


def _sidecar_relative(path: Path, data_root: Path) -> Path:
    """The path relative to the sidecar's data folder; a source instance falls back to its unchanged original."""
    try:
        return path.resolve().relative_to(data_root.resolve())
    except ValueError:
        alias = _AZURE_ALIAS.get()
        if alias is None:
            raise
        original, sha256 = alias
        rel = original.resolve().relative_to(data_root.resolve())  # ValueError: not under it either
        from jav import source_instances

        if not source_instances.intact(original, sha256):
            raise ValueError(f"the original changed since it was added: {original}") from None
        return rel


def _sidecar_root() -> Path:
    # 076: the sidecar's `/data` mount is the legacy project's data folder (`JAV_LEGACY_ROOT`), not a path in the config
    az = _CFG["azure_di"]
    return Path(az["data_root"]) if az.get("data_root") else OLD_DATA_ROOT


def azure_route(path: Path) -> str:
    """121: `direct` when the Azure endpoint and key are set (any readable document), otherwise `sidecar` when the
    legacy sidecar can see the document; `AzureBlocked("unreachable")` when neither, before any reservation or call."""
    if azure_di.configured():
        return "direct"
    try:
        _sidecar_relative(path, _sidecar_root())
    except ValueError:
        raise AzureBlocked("unreachable") from None
    return "sidecar"


def azure_words(path: Path, *, run_id: str = "jav-ocr") -> tuple[list[list[dict[str, Any]]], list[float], dict[str, Any]]:
    """The word boxes of an Azure recognition, in points (inch × 72), with confidence on a 0-100 scale (the same
    signals as tesseract). 121: directly over the REST API when it is configured (`jav/adapters/azure_di.py`);
    otherwise the legacy sidecar's `/parse` (chain: azure_di) and the evidence file it saves, for a PDF under the
    sidecar's `/data` mount."""
    import json as _json
    import urllib.request

    az = _CFG["azure_di"]
    if azure_route(path) == "direct":
        try:
            found = azure_di.analyze_read(path, model=AZURE_DI_MODEL, api_version=str(az.get("api_version") or _AZURE_FIRST_API),
                                          timeout_s=float(az["timeout_s"]), poll_s=float(az.get("poll_interval_s", 1.0)))
        except (azure_di.AzureDiError, azure_di.AzureOutcomeUnknown, OSError, ValueError) as exc:
            raise OcrUnavailableError(f"azure_di: {exc}") from exc
        return azure_evidence_words(found)
    data_root = _sidecar_root()
    try:
        rel = _sidecar_relative(path, data_root)
    except ValueError as exc:
        raise OcrUnavailableError(f"azure_di: a PDF nincs a sidecar adat-mappája alatt ({data_root}): {path}") from exc
    container_path = f"{az['container_root']}/{rel.as_posix()}"
    body = _json.dumps({"path": container_path, "chain": ["azure_di"], "ai_run_id": run_id}).encode("utf-8")
    req = urllib.request.Request(f"{az['sidecar_url']}/parse", data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=float(az["timeout_s"])) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise OcrUnavailableError(f"azure_di: a sidecar nem válaszolt ({az['sidecar_url']}): {exc}") from exc
    if result.get("provider_used") != "azure_di" or not result.get("evidence_ref"):
        raise OcrUnavailableError(f"azure_di: nem futott le (provider={result.get('provider_used')}, chain={result.get('fallback_chain')})")
    evidence = _json.loads((data_root / result["evidence_ref"]["path"]).read_text(encoding="utf-8"))
    return azure_evidence_words(evidence)


AZURE_PROVIDER = "azure_di"
# 121: `unreachable` (no route to Azure for this document) and `unavailable` (the call failed or its outcome is unknown)
_ESCALATION_TODO = {"budget_exceeded", "uncertain_attempt", "unreachable", "unavailable"}


def azure_recognise(path: Path) -> tuple[list[list[dict[str, Any]]], list[float], dict[str, Any]]:
    """075 (repeated security audit, S01): Azure DI through the shared call log. In a worker run
    (`jav.runtime.calls.current()`) the document's page count is reserved at the Azure price from the run's Azure budget
    before the sidecar is called; without an Azure budget, with too little of it, or after an attempt with an unknown
    outcome, the network is never reached (`AzureBlocked`). A repeated item gets the saved answer, not a second paid
    call. Every physical call also gets a ledger row, on the command-line path too."""
    from jav import store
    from jav.runtime import calls

    ctx = calls.current()
    ledger_run = (ctx.budget_scope if ctx else None) or "jav-ocr"

    def physical() -> calls.Outcome:
        t0 = time.perf_counter()
        try:
            pages, confs, meta = azure_words(path)
        except OcrUnavailableError as exc:
            store.ledger_add(run_id=ledger_run, step="ocr_azure", provider=AZURE_PROVIDER, model=AZURE_DI_MODEL,
                             input_tokens=None, output_tokens=None, cost_usd=None, seconds=round(time.perf_counter() - t0, 3),
                             config_hash=CONFIG_HASH, error=type(exc).__name__)
            raise
        cost = AZURE_USD_PER_PAGE * len(pages)
        model = meta.get("model_id") or AZURE_DI_MODEL
        store.ledger_add(run_id=ledger_run, step="ocr_azure", provider=AZURE_PROVIDER, model=model, input_tokens=None,
                         output_tokens=None, cost_usd=float(cost), seconds=round(time.perf_counter() - t0, 3), config_hash=CONFIG_HASH)
        return calls.Outcome(response={"pages": pages, "confs": confs, "meta": meta}, model=model, cost_usd=cost)

    if ctx is not None and ctx.budget_scope is not None and not calls.has_budget(ctx.budget_scope, AZURE_PROVIDER):
        raise AzureBlocked("off")
    azure_route(path)  # 121: no route, no call: neither a reservation nor a "failed" call-log row
    if ctx is None:  # the command-line / measurement path: no run budget (as for JEV and OpenAI there), but ledgered
        out = physical().response
        return out["pages"], out["confs"], out["meta"]
    n_pages = len(page_sizes(path)) or pdfmod.input_limits().max_pages
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
    meta = {"model_id": evidence.get("model_id"), "api_version": evidence.get("api_version")}
    return pages, confs, meta


def _tesseract_args(psm: int | None = None) -> list[str]:
    return ["-l", _TESS["lang"], "--psm", str(psm if psm is not None else _TESS["psm"]), "--oem", str(_TESS["oem"]),
            "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0"]


def _run_tesseract(png: Path, out_base: Path, *, psm: int | None = None, eng: str = "native") -> str:
    """OCR of one page image; returns the TSV text. Native: `--tessdata-dir tools/tessdata`; Docker: the tessdata
    inside the image."""
    timeout = float(_TESS["timeout_s"])
    if eng == "native":
        tessdata = PROJECT_ROOT / _TESS["tessdata_dir"]
        cmd = [native_exe(), str(png), str(out_base), "--tessdata-dir", str(tessdata), *_tesseract_args(psm)]
    else:
        work = png.parent
        cmd = ["docker", "run", "--rm", "-v", f"{work}:/work", "--entrypoint", "tesseract", _CFG["docker"]["image"],
               f"/work/{png.name}", f"/work/{out_base.name}", *_tesseract_args(psm)]
        timeout *= 20  # an order of magnitude slower in the VM
    subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)
    return Path(str(out_base) + ".tsv").read_text(encoding="utf-8")


# --- page images ------------------------------------------------------------------------------


def render_pages(path: str | Path, out_dir: Path, *, dpi: int = DPI, max_pages: int | None = None) -> list[Path]:
    """PDF -> page images (PNG) with pypdfium2 (no poppler). Greyscale by default, `dpi` resolution; at most
    `max_pages` pages. 077: rendered in the isolated PDF reader (`jav/isolated_pdf.py`); over its time or memory limit
    `PdfRenderLimit` (a to-do, like `PageTooLarge`)."""
    from jav import isolated_pdf

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
    from jav import isolated_pdf

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


def _y_tolerance(pages: list[list[dict[str, Any]]]) -> float:
    heights = [w["bottom"] - w["top"] for page in pages for w in page if w["bottom"] > w["top"]]
    if not heights:
        return 3.0
    return max(3.0, 0.45 * statistics.median(heights))  # skewed scans: line threshold ~ half the letter height


# --- cache + entry point -------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_key(path: Path, eng: str) -> str:
    ver = engine_version(eng).replace(" ", "_").replace("/", "_")[:40]
    return f"{_sha256(path)}_{CACHE_HASH}_{ver}"


def rekey_cache(old_conf: dict[str, Any], cache_dir: Path | None = None) -> int:
    """076: a one-off move of the cache files written under an older config's key (up to `ocr.json` 1.0.0 the key held
    the whole file's hash) to the current key. Allowed only when the older config's output settings equal the current
    ones: then the cached text is exactly what a new OCR would read, and nothing is read or paid for again. An existing
    file under the new key is never overwritten; a second run moves nothing. Returns the number of files moved."""
    if output_settings(old_conf) != output_settings(_CFG):
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
    signals = {**data["signals"], "cached": cached, "engine": data["engine"], "engine_version": data["engine_version"], "config_hash": CONFIG_HASH}
    # 045: old cache files have no word or page-size data; the word layer is then empty (no boxes), same lines
    return PdfText(path=str(path), text=text, lines=lines, layout=layout, page_count=data["page_count"], has_text_layer=False,
                   text_source="ocr" if ok else None, ocr=signals, words=data.get("words") or [],
                   page_sizes=[tuple(s) for s in data.get("page_sizes") or []])


def _note_azure_reuse(path: Path, key: str) -> None:
    """082: in a worker run, text taken from an earlier Azure recognition is a ledger row at 0 USD under the item's
    flow identifier (`<run>:<fingerprint16>`; a document's identifier is its content fingerprint), so the cost view
    counts it among the answers reused from earlier, as it does an earlier JEV answer. Outside a run (measurements, the
    command line) nothing is written."""
    from jav import store
    from jav.runtime import calls

    ctx = calls.current()
    if ctx is None or ctx.budget_scope is None:
        return
    store.ledger_add(run_id=f"{ctx.budget_scope}:{_sha256(path)[:16]}", step="ocr_azure", provider=AZURE_PROVIDER,
                     model=AZURE_DI_MODEL, input_tokens=None, output_tokens=None, cost_usd=0.0, seconds=0.0, cached=True,
                     cache_key=key, config_hash=CONFIG_HASH)


def ocr_pdf(
    path: str | Path, *, page_count: int | None = None, use_cache: bool = True, psm: int | None = None, engine_name: str | None = None
) -> PdfText:
    """OCR of one PDF: from the cache if present; otherwise page images + tesseract per page (or Azure DI via the
    sidecar) + the shared layout builder. `has_text_layer` stays False (a fact), `text_source="ocr"` if the recognised
    text is usable; the `ocr` dict holds the quality signals. The engine is part of the cache key: a new engine means a
    new OCR."""
    path = Path(path)
    eng = engine(engine_name)  # OcrUnavailableError if there is no engine
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = cache_key(path, eng) + (f"_psm{psm}" if psm is not None and eng != "azure_di" else "")
    cache_file = CACHE_DIR / f"{key}.json"
    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
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
            pngs = render_pages(path, tmp_dir)
            pages = []
            all_conf = []
            for png in pngs:
                tsv = _run_tesseract(png, tmp_dir / png.stem, psm=psm, eng=eng)
                words, confs = parse_tsv(tsv)
                pages.append(words)
                all_conf.extend(confs)
        n_pages = len(pngs)
    layout = build_layout(pages, y_tol=_y_tolerance(pages))
    n_words = sum(len(p) for p in pages)
    signals = {
        "mean_conf": round(statistics.mean(all_conf) / 100.0, 4) if all_conf else 0.0,
        "low_conf_ratio": round(sum(1 for c in all_conf if c < LOW_CONF_WORD) / len(all_conf), 4) if all_conf else 1.0,
        "words": n_words,
        "pages_ocr": n_pages,
        "dpi": DPI if eng != "azure_di" else None,
        "psm": (psm if psm is not None else int(_TESS["psm"])) if eng != "azure_di" else None,
        "seconds": round(time.perf_counter() - t0, 2),
        **extra,
    }
    data = {
        "path": str(path), "page_count": page_count if page_count is not None else n_pages, "engine": eng,
        "engine_version": engine_version(eng), "config_hash": CONFIG_HASH, "signals": signals,
        "layout": [ln.model_dump() for ln in layout],
        "words": pages,  # 045: word boxes in points, with the line number (set by build_layout) - for the word layer
        "page_sizes": page_sizes(path),
    }
    if use_cache:
        cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
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
    cache_file.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
    return cached


ESCALATION: dict[str, Any] = dict(_CFG.get("escalation", {}))


def ocr_with_escalation(path: str | Path, *, page_count: int | None = None, use_cache: bool = True) -> tuple[PdfText, bool]:
    """The flow's OCR step: the default engine (auto / env); if the result is weak by the policy's `ocr.escalate_*`
    thresholds and escalation is enabled (configs/ocr.json), the text of the more accurate, paid engine (`azure_di`)
    goes on. Returns (PdfText, whether escalated). If escalation is unavailable, the local result stays; 121: the
    reason is kept in the signals (`escalation_blocked`), and the flow raises a to-do for it (`escalation_review_reasons`)."""
    from jav.policy import ocr_should_escalate

    first = ocr_pdf(path, page_count=page_count, use_cache=use_cache)
    if os.environ.get(ENGINE_ENV) or not ESCALATION.get("enabled") or first.ocr is None or first.ocr.get("engine") == ESCALATION.get("engine"):
        return first, False
    if not ocr_should_escalate(first.ocr.get("mean_conf"), first.ocr.get("low_conf_ratio")):
        return first, False
    try:
        second = ocr_pdf(path, page_count=page_count, use_cache=use_cache, engine_name=ESCALATION["engine"])
    except AzureBlocked as exc:  # 075: kept in the signals; the flow raises a to-do for a budget or uncertainty block
        first.ocr["escalation_blocked"] = exc.reason
        return first, False
    except OcrUnavailableError:  # 121: the call failed or its outcome is unknown; before 121 this was silent
        first.ocr["escalation_blocked"] = "unavailable"
        return first, False
    if second.ocr and (second.ocr.get("mean_conf") or 0) >= (first.ocr.get("mean_conf") or 0):
        second.ocr["escalated_from"] = first.ocr.get("engine")
        if not second.words and first.words:
            # 049: the old Azure cache has no word data (calling it again is paid). The text stays Azure's; the word
            # layer (boxes, paging to the field) is built from the local OCR's word positions; anything not found there
            # gets no box.
            second.words, second.page_sizes = first.words, first.page_sizes
            second.ocr["words_from"] = first.ocr.get("engine")
        return second, True
    return first, False


def status() -> dict[str, Any]:
    """Admin / preflight: which engine, version, language packs, cache size."""
    out: dict[str, Any] = {"config_version": cfg.version("ocr"), "config_hash": CONFIG_HASH, "native_exe": native_exe(), "docker_image": _CFG["docker"]["image"],
                           "azure_sidecar": _CFG["azure_di"]["sidecar_url"], "azure_direct": azure_di.configured(),  # 121
                           "engine_env": os.environ.get(ENGINE_ENV)}
    try:
        out["engine"] = engine()
        out["engine_version"] = engine_version(out["engine"])
    except OcrUnavailableError as exc:
        out["engine"] = None
        out["error"] = str(exc)
    tessdata = PROJECT_ROOT / _TESS["tessdata_dir"]
    out["tessdata"] = sorted(p.stem for p in tessdata.glob("*.traineddata")) if tessdata.exists() else []
    out["cache_files"] = len(list(CACHE_DIR.glob("*.json"))) if CACHE_DIR.exists() else 0
    return out


if __name__ == "__main__":  # quick manual test: python -m jav.ocr <pdf>
    r = ocr_pdf(sys.argv[1], use_cache=False)
    print(json.dumps(r.ocr, ensure_ascii=False))
    print("\n".join(r.lines[:80]))
