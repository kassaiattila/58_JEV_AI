"""121: Azure Document Intelligence (`prebuilt-read`) called directly over its REST API.

Before 121 the paid OCR escalation went only through the legacy sidecar's `/parse`, which reads only files under the
legacy project's data folder; a document from any other folder never reached Azure. Here the document's bytes are sent
straight to the service: one request starts the analysis, then its result is read until it is ready.

Reuse (CLAUDE.md §3): ported from the legacy sidecar (`10_AIFLOW_V4/sidecar/app/providers/azure_di.py`, which uses the
azure-ai-documentintelligence 1.0.2 SDK, and `sidecar/app/ocr_evidence.py` `capture_azure`). The standard library's HTTP
client replaces the SDK, and the result becomes the same evidence dictionary the sidecar saves, so `jav/ocr.py`
`azure_evidence_words` reads both. The cost, the budget and the call log stay in `jav/ocr.py` `azure_recognise`.

Errors: `AzureDiError` is a definite failure (not configured, refused, an error answer, a failed analysis); the
service did not produce a result to pay for. `AzureOutcomeUnknown` means the analysis was accepted, so it may be billed,
but its result could not be read; the call log records it as uncertain and it is never repeated automatically.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from jav.config import AZURE_DI_ENV_VARS

ENDPOINT_ENV, KEY_ENV = AZURE_DI_ENV_VARS
_KEY_HEADER = "Ocp-Apim-Subscription-Key"
MAX_RESPONSE_BYTES = 64 * 1024 * 1024  # a 12-page result is far below; a larger answer is refused, not read into memory
_MAX_POLL_S = 10.0


class AzureDiError(RuntimeError):
    """A definite failure: the request was refused or not sent, or the analysis failed."""


class AzureOutcomeUnknown(RuntimeError):
    """The analysis was accepted but its result could not be read (lost answer, time limit, unexpected address)."""


def configured() -> bool:
    """Whether the endpoint and the key are both set (the local `.env`; never printed or logged)."""
    return bool(os.environ.get(ENDPOINT_ENV, "").strip() and os.environ.get(KEY_ENV, "").strip())


def _endpoint() -> urllib.parse.SplitResult:
    raw = os.environ.get(ENDPOINT_ENV, "").strip()
    if not raw or not os.environ.get(KEY_ENV, "").strip():
        raise AzureDiError(f"azure_di: {ENDPOINT_ENV} and {KEY_ENV} are not both set")
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme != "https" or not parts.hostname:
        raise AzureDiError(f"azure_di: {ENDPOINT_ENV} must be an https address")
    return parts


def _read_json(resp: Any) -> dict[str, Any]:
    body = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise AzureOutcomeUnknown("azure_di: the result is larger than the allowed size")
    return json.loads(body.decode("utf-8"))


def _retry_after(resp: Any, default: float) -> float:
    try:
        return min(_MAX_POLL_S, max(0.0, float(resp.headers.get("Retry-After"))))
    except (TypeError, ValueError):
        return default


def analyze_read(path: Path, *, model: str, api_version: str, timeout_s: float, poll_s: float) -> dict[str, Any]:
    """Recognise the text of `path` with `model`; returns the evidence dictionary (pages, words with polygons in the
    page's unit, confidence 0-1, the model and API version). `timeout_s` bounds the whole call, polling included."""
    endpoint = _endpoint()
    key = os.environ[KEY_ENV].strip()
    base = urllib.parse.urlunsplit((endpoint.scheme, endpoint.netloc, endpoint.path.rstrip("/"), "", ""))
    url = f"{base}/documentintelligence/documentModels/{urllib.parse.quote(model)}:analyze?api-version={urllib.parse.quote(api_version)}"
    deadline = time.monotonic() + float(timeout_s)
    start = urllib.request.Request(url, data=Path(path).read_bytes(), method="POST",
                                   headers={_KEY_HEADER: key, "Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(start, timeout=max(1.0, float(timeout_s))) as resp:
            operation = resp.headers.get("Operation-Location")
            wait = _retry_after(resp, poll_s)
    except urllib.error.HTTPError as exc:
        raise AzureDiError(f"azure_di: the service refused the analysis (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise AzureDiError(f"azure_di: the service could not be reached ({exc.reason})") from exc
    # From here the analysis is accepted and may be billed: every failure is an unknown outcome, raised without its
    # transport cause, so that the call log does not read a later connection error as "never sent".
    op = urllib.parse.urlsplit(operation or "")
    if op.scheme != "https" or op.hostname != endpoint.hostname:
        raise AzureOutcomeUnknown("azure_di: the result address is missing or on another host; the key is not sent there")
    while True:
        if time.monotonic() >= deadline:
            raise AzureOutcomeUnknown(f"azure_di: no result within {timeout_s} s")
        time.sleep(wait)
        poll = urllib.request.Request(operation, method="GET", headers={_KEY_HEADER: key})
        try:
            with urllib.request.urlopen(poll, timeout=max(1.0, deadline - time.monotonic())) as resp:
                answer = _read_json(resp)
                wait = _retry_after(resp, poll_s)
        except AzureOutcomeUnknown:
            raise
        except (OSError, ValueError) as exc:
            raise AzureOutcomeUnknown(f"azure_di: the result could not be read ({type(exc).__name__})") from None
        status = answer.get("status")
        if status == "succeeded":
            return evidence(answer.get("analyzeResult") or {})
        if status == "failed":
            code = ((answer.get("error") or {}).get("code")) or "unknown"
            raise AzureDiError(f"azure_di: the analysis failed ({code})")
        if status not in ("notStarted", "running"):
            raise AzureOutcomeUnknown(f"azure_di: unexpected analysis status {status!r}")


def evidence(result: dict[str, Any]) -> dict[str, Any]:
    """The REST `analyzeResult` as the sidecar's evidence dictionary (`capture_azure`): the original words, polygons
    and confidences, unchanged."""
    pages = []
    for page in result.get("pages") or []:
        words = [{"content": w.get("content"), "polygon": w.get("polygon"), "confidence": w.get("confidence"),
                  "span": w.get("span")} for w in page.get("words") or []]
        pages.append({"page_number": page.get("pageNumber"), "width": page.get("width"), "height": page.get("height"),
                      "unit": page.get("unit"), "angle": page.get("angle"), "words_present": page.get("words") is not None,
                      "words": words, "lines": [ln.get("content") for ln in page.get("lines") or []]})
    return {"provider": "azure_di", "content": result.get("content"), "model_id": result.get("modelId"),
            "api_version": result.get("apiVersion"), "pages": pages}
