"""Azure Document Intelligence called directly over its REST API (121; 279: the only route).

The document's bytes are sent straight to the service: one request starts the analysis, then its result is read until
it is ready. Since 279 nothing else reaches Azure: the legacy sidecar route is gone, so the framework needs only its own
endpoint and key (`AZURE_DI_ENDPOINT`, `AZURE_DI_KEY` in `.env`).

Reuse (CLAUDE.md §3): ported from the legacy sidecar (`10_AIFLOW_V4/sidecar/app/providers/azure_di.py`, which uses the
azure-ai-documentintelligence 1.0.2 SDK, and `sidecar/app/ocr_evidence.py` `capture_azure`, @4256cba). The standard
library's HTTP client replaces the SDK, and the result becomes the same evidence dictionary, so `jav/documents/ocr.py`
`azure_evidence_words` reads both the texts kept from before 279 and new ones. 279 adds what the legacy code lacked: a
page range (`pages`, the service bills only the pages it analyses), a size and format check before anything is sent,
repeating a refused or throttled start (429 and 5xx, the service's advice on throttling), and a free check of the
endpoint and key (`check`, the resource details: `GET /documentintelligence/info`). The cost, the budget and the call
log stay in `jav/documents/ocr.py` `azure_recognise`.

Errors: `AzureDiError` is a definite failure (not configured, refused, an error answer, a failed analysis); the
service did not produce a result to pay for. `AzureDiRefused` is the subset where the service refused to start the
analysis (or the request never left this machine): nothing was analysed, so nothing is billed. `AzureOutcomeUnknown`
means the analysis was accepted, so it may be billed, but its result could not be read; the call log records it as
uncertain and it is never repeated automatically.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jav.core.config import AZURE_DI_ENV_VARS

ENDPOINT_ENV, KEY_ENV = AZURE_DI_ENV_VARS
_KEY_HEADER = "Ocp-Apim-Subscription-Key"
MAX_RESPONSE_BYTES = 64 * 1024 * 1024  # a 12-page result is far below; a larger answer is refused, not read into memory
_MAX_POLL_S = 10.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
"""279: a start the service refused for load or a passing fault (the service's advice: repeat with a growing wait);
any other refusal (400 bad document, 401 wrong key, 404 wrong address or model) is final."""

# 279: the inputs the service reads (Microsoft Learn, "Service quotas and limits", v4.0, read 2026-11-02): PDF and the
# image formats; the Office formats are read by this framework's own readers and never sent. The bytes go as
# `application/octet-stream`, as they always did (the service recognises the format itself).
SUFFIXES = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".heif", ".heic"})
_CONTENT_TYPE = "application/octet-stream"


class AzureDiError(RuntimeError):
    """A definite failure: the request was refused or not sent, or the analysis failed."""


class AzureDiRefused(AzureDiError):
    """279: the analysis never started: the document was not sent (too large, a format the service does not read, no
    connection) or the service refused to start it. Nothing was analysed, so nothing is billed."""


class AzureOutcomeUnknown(RuntimeError):
    """The analysis was accepted but its result could not be read (lost answer, time limit, unexpected address)."""


@dataclass(frozen=True)
class Limits:
    """279: how one analysis is sent (`configs/ocr.json` `azure_di`): the whole call's time limit, the wait between
    two reads of the result, how often a refused start is repeated and the longest wait before it, the largest file."""

    timeout_s: float
    poll_s: float = 2.0
    retries: int = 3
    retry_max_wait_s: float = 30.0
    max_file_mb: float = 500.0


def configured() -> bool:
    """Whether the endpoint and the key are both set (the local `.env`; never printed or logged)."""
    return bool(os.environ.get(ENDPOINT_ENV, "").strip() and os.environ.get(KEY_ENV, "").strip())


def endpoint_host() -> str | None:
    """279: the endpoint's host name, for the status views (an address, not a secret); None when it is not set or not
    an https address."""
    try:
        return _endpoint().hostname
    except AzureDiError:
        return None


def _endpoint() -> urllib.parse.SplitResult:
    raw = os.environ.get(ENDPOINT_ENV, "").strip()
    if not raw or not os.environ.get(KEY_ENV, "").strip():
        raise AzureDiRefused(f"azure_di: {ENDPOINT_ENV} and {KEY_ENV} are not both set")
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme != "https" or not parts.hostname:
        raise AzureDiRefused(f"azure_di: {ENDPOINT_ENV} must be an https address")
    return parts


def _base() -> tuple[urllib.parse.SplitResult, str]:
    endpoint = _endpoint()
    return endpoint, urllib.parse.urlunsplit((endpoint.scheme, endpoint.netloc, endpoint.path.rstrip("/"), "", ""))


def _read_json(resp: Any) -> dict[str, Any]:
    body = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise AzureOutcomeUnknown("azure_di: the result is larger than the allowed size")
    return json.loads(body.decode("utf-8"))


def _retry_after(resp: Any, default: float, cap: float = _MAX_POLL_S) -> float:
    try:
        return min(cap, max(0.0, float(resp.headers.get("Retry-After"))))
    except (TypeError, ValueError, AttributeError):
        return default


def check_format(path: Path) -> None:
    """279: `AzureDiRefused` for a file the service does not read (by its extension)."""
    if Path(path).suffix.lower() not in SUFFIXES:
        raise AzureDiRefused(f"azure_di: the service does not read {Path(path).suffix or 'extensionless'} files")


def check_sendable(path: Path, limits: Limits) -> None:
    """279: before any reservation or call: the format is one the service reads and the file is within its size."""
    check_format(path)
    size_mb = Path(path).stat().st_size / (1024 * 1024)
    if size_mb > limits.max_file_mb:
        raise AzureDiRefused(f"azure_di: the file is {size_mb:.1f} MB, over the {limits.max_file_mb:g} MB the service takes")


def _start(url: str, body: bytes, key: str, limits: Limits, deadline: float) -> Any:
    """The analysis request, repeated while the service refuses it for load (`RETRY_STATUSES`) or the connection
    cannot be made, at most `limits.retries` more times, waiting as the service asks (`Retry-After`) or 1, 2, 4… s."""
    attempt = 0
    while True:
        request = urllib.request.Request(url, data=body, method="POST", headers={_KEY_HEADER: key, "Content-Type": _CONTENT_TYPE})
        try:
            return urllib.request.urlopen(request, timeout=max(1.0, deadline - time.monotonic()))
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_STATUSES or attempt >= limits.retries:
                raise AzureDiRefused(f"azure_di: the service refused the analysis (HTTP {exc.code})") from exc
            wait = _retry_after(exc, 2.0 ** attempt, cap=limits.retry_max_wait_s)
        except urllib.error.URLError as exc:
            if attempt >= limits.retries:
                raise AzureDiRefused(f"azure_di: the service could not be reached ({exc.reason})") from exc
            wait = 2.0 ** attempt
        attempt += 1
        if time.monotonic() + wait >= deadline:
            raise AzureDiRefused("azure_di: the service kept refusing the analysis until the time limit")
        time.sleep(wait)


def analyze(path: Path, *, model: str, api_version: str, limits: Limits, pages: str | None = None) -> dict[str, Any]:
    """Recognise the text of `path` with `model`; returns the evidence dictionary (pages, words with polygons in the
    page's unit, confidence 0-1, the model and API version). `limits.timeout_s` bounds the whole call, repeats and
    polling included. 279: `pages` (for example "1-12") is the page range the service analyses and bills."""
    check_sendable(path, limits)
    endpoint, base = _base()
    key = os.environ[KEY_ENV].strip()
    query = {"api-version": api_version, **({"pages": pages} if pages else {})}
    url = f"{base}/documentintelligence/documentModels/{urllib.parse.quote(model)}:analyze?{urllib.parse.urlencode(query)}"
    deadline = time.monotonic() + float(limits.timeout_s)
    with _start(url, Path(path).read_bytes(), key, limits, deadline) as resp:
        operation = resp.headers.get("Operation-Location")
        wait = _retry_after(resp, limits.poll_s)
    # From here the analysis is accepted and may be billed: every failure is an unknown outcome, raised without its
    # transport cause, so that the call log does not read a later connection error as "never sent".
    op = urllib.parse.urlsplit(operation or "")
    if op.scheme != "https" or op.hostname != endpoint.hostname:
        raise AzureOutcomeUnknown("azure_di: the result address is missing or on another host; the key is not sent there")
    while True:
        if time.monotonic() >= deadline:
            raise AzureOutcomeUnknown(f"azure_di: no result within {limits.timeout_s} s")
        time.sleep(wait)
        poll = urllib.request.Request(operation, method="GET", headers={_KEY_HEADER: key})
        try:
            with urllib.request.urlopen(poll, timeout=max(1.0, deadline - time.monotonic())) as resp:
                answer = _read_json(resp)
                wait = _retry_after(resp, limits.poll_s)
        except urllib.error.HTTPError as exc:
            if exc.code in RETRY_STATUSES:  # 279: a throttled read of the result is read again, within the time limit
                wait = _retry_after(exc, limits.poll_s * 2, cap=limits.retry_max_wait_s)
                continue
            raise AzureOutcomeUnknown(f"azure_di: the result could not be read (HTTP {exc.code})") from None
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


def analyze_read(path: Path, *, model: str, api_version: str, timeout_s: float, poll_s: float) -> dict[str, Any]:
    """121's entry point, kept for its callers: `analyze` with the default limits and no page range."""
    return analyze(path, model=model, api_version=api_version, limits=Limits(timeout_s=timeout_s, poll_s=poll_s))


@dataclass(frozen=True)
class CheckResult:
    """279: the outcome of the free check. `ok`: the endpoint answered and accepted the key. `reason`: why not
    (`not_configured`, `not_https`, `refused_key` for 401/403, `not_found` for 404, `http_<code>`, `unreachable`,
    `bad_answer`). `custom_models`: what the resource reported (its custom-model count and limit), as a sign that the
    answer came from a Document Intelligence resource."""

    ok: bool
    reason: str | None = None
    host: str | None = None
    custom_models: dict[str, Any] | None = None


def check(*, api_version: str, timeout_s: float = 15.0) -> CheckResult:
    """279: a free check of the endpoint and the key: the resource's details (`GET /documentintelligence/info`, the
    SDK's `get_resource_details`), which analyse nothing and are not billed. The key is sent only to the configured
    https host; the answer is never logged."""
    if not configured():
        return CheckResult(False, "not_configured")
    try:
        endpoint, base = _base()
    except AzureDiError:
        return CheckResult(False, "not_https")
    url = f"{base}/documentintelligence/info?{urllib.parse.urlencode({'api-version': api_version})}"
    request = urllib.request.Request(url, method="GET", headers={_KEY_HEADER: os.environ[KEY_ENV].strip()})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            answer = _read_json(resp)
    except urllib.error.HTTPError as exc:
        reason = "refused_key" if exc.code in (401, 403) else "not_found" if exc.code == 404 else f"http_{exc.code}"
        return CheckResult(False, reason, endpoint.hostname)
    except (OSError, ValueError, AzureOutcomeUnknown):
        return CheckResult(False, "unreachable", endpoint.hostname)
    models = answer.get("customDocumentModels") if isinstance(answer, dict) else None
    if not isinstance(models, dict):
        return CheckResult(False, "bad_answer", endpoint.hostname)
    return CheckResult(True, None, endpoint.hostname, {k: models.get(k) for k in ("count", "limit")})


def evidence(result: dict[str, Any]) -> dict[str, Any]:
    """The REST `analyzeResult` as the evidence dictionary (the legacy sidecar's `capture_azure` shape): the original
    words, polygons and confidences, unchanged."""
    pages = []
    for page in result.get("pages") or []:
        words = [{"content": w.get("content"), "polygon": w.get("polygon"), "confidence": w.get("confidence"),
                  "span": w.get("span")} for w in page.get("words") or []]
        pages.append({"page_number": page.get("pageNumber"), "width": page.get("width"), "height": page.get("height"),
                      "unit": page.get("unit"), "angle": page.get("angle"), "words_present": page.get("words") is not None,
                      "words": words, "lines": [ln.get("content") for ln in page.get("lines") or []]})
    return {"provider": "azure_di", "content": result.get("content"), "model_id": result.get("modelId"),
            "api_version": result.get("apiVersion"), "pages": pages}
