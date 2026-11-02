"""Budgeted native interpretation through the existing provider receipt ledger."""
from __future__ import annotations

import logging

from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Mapping

from jav.documents import native_results
from jav.core import store
from jav.documents.native_contracts import Failed, NativeLimits, ReceiptRef, Rejected, Succeeded, Uncertain
from jav.ai import engine as engines, native_verification
from jav.documents.readers import providers
from jav.documents.readers.pipeline import digest, json_bytes
from jav.documents.readers.receipts import InterpretationRejected
from jav.core import calls

log = logging.getLogger(__name__)


def estimate_limits(params: Mapping[str, Any]) -> NativeLimits:
    """Bound the actual GPT request and the judgement service's request plus its alias resolution (265: the service
    of the setting's engine, `jav.ai.engine.of_params`; none for an engine without one)."""
    from jav.core.config import OPENAI_MODEL, OPENAI_SETTINGS, openai_price
    if params.get("arm") == "S":
        raise ValueError("Native interpretation does not support the S path")
    transfer, output = 80_000, 4000
    price = openai_price(OPENAI_MODEL)
    amounts = {"openai": calls.estimate_max_cost(input_bytes=transfer, max_output_tokens=output,
        usd_per_mtok=(Decimal(str(price[0])), Decimal(str(price[1]))),
        repeats=1 + int(OPENAI_SETTINGS["sdk_max_retries"]))}
    engine = engines.of_params(params)
    if engine.judged:
        # The adapters serialise spaces around structural JSON tokens. Twice
        # the canonical transfer bound also covers that envelope; the separate
        # allowance covers JEV's small, budgeted model-alias probe.
        adapter = engines.judge_adapter(engine.judge)()
        amounts[adapter.provider] = adapter.max_cost_for(transfer * 2 + 4096)
    return NativeLimits(max_transfer_bytes=transfer, max_output_tokens=output, provider_limits_usd=amounts)


def azure_recognition(read_path: Path, *, source_path: str, sha256: str) -> tuple[str | None, str | None]:
    """124 (the owner's decision of 2026-10-07): a scan that continued into general facts without an Azure text from
    detection is recognised by Azure here, but only in a run whose budget has an Azure part (the recipe's Azure
    switch); an earlier recognition of the same document is reused from the OCR cache at no cost. The reader itself
    never calls a provider. Returns (the kept recognition's digest, None), or (None, why there is none): `off` (no
    Azure budget: local OCR, as chosen), a blocked or failed call (`jav.documents.ocr.escalation_review_reasons`), or
    `no_original` (an Azure text cached before 123, kept without its original; it is not taken over or paid again)."""
    from jav.documents import ocr

    ctx = calls.current()
    if ctx is None or ctx.budget_scope is None or not calls.has_budget(ctx.budget_scope, ocr.AZURE_PROVIDER):
        return None, "off"
    try:
        recognised = ocr.ocr_pdf(read_path, engine_name=ocr.AZURE_PROVIDER)
    except ocr.AzureBlocked as exc:
        return None, exc.reason
    except ocr.OcrUnavailableError:
        return None, "unavailable"
    digest_ = (recognised.ocr or {}).get("recognition_sha256")
    return (digest_, None) if digest_ else (None, "no_original")


def _receipts(graph_id: str, replayed: dict[int, tuple[bool, int | None]]) -> tuple[ReceiptRef, ...]:
    result = []
    with store.connect() as c:
        for row in c.execute("SELECT * FROM invocations WHERE run_id=? ORDER BY id", (graph_id,)):
            artifact = c.execute("SELECT payload FROM artifacts WHERE kind=? AND artifact_id=?",
                                 (calls.RESPONSE_KIND, str(row["id"]))).fetchone()
            was_replayed, reused_from = replayed.get(row["id"], (False, None))
            result.append(ReceiptRef(receipt_id=f"invocation:{row['id']}", invocation_id=row["id"],
                provider=row["provider"], run_id=row["run_id"], step_id=row["step_id"],
                request_sha256=row["request_hash"], response_sha256=digest(json_bytes(json.loads(artifact[0]))) if artifact else None,
                artifact_kind=calls.RESPONSE_KIND if artifact else None, artifact_id=str(row["id"]) if artifact else None,
                call_status=row["status"], cost_known=bool(row["cost_known"]),
                cost_usd=Decimal(row["cost_usd"]) if row["cost_known"] else None,
                replayed=was_replayed, reused_from=reused_from))
    return tuple(result)


def _failure_reason(error: Exception) -> str:
    """Translate only known boundary errors, without exposing document content."""
    if isinstance(error, calls.BudgetExceeded):
        return "The configured provider budget is exhausted"
    if isinstance(error, ValueError):
        message = str(error)
        if "transfer bound" in message or "Source view exceeds" in message:
            return "The provider request exceeds the configured transfer limit"
        if "budget" in message:
            return "An explicit matching provider budget is required"
        if message == "No readable source elements are available for interpretation":
            return message
    return "Interpretation stopped: " + type(error).__name__


def interpret(*, work_run_id: str, item_id: str, graph_id: str, reading_id: str,
              engine: str, use_cache: bool, limits: NativeLimits) -> str:
    """Return a saved terminal outcome reference, without repeating settled work. `engine` (265): the AI engine; its
    judgement service checks the GPT facts (until 265 `jev: bool`); an engine without one leaves them unchecked."""
    previous = native_results.outcome_for_graph(graph_id)
    if previous is not None:
        data, _, _ = native_results.load_outcome(previous)
        if (data["run_id"], data["item_id"], data["reading_id"]) != (work_run_id, item_id, reading_id):
            raise native_results.NativeIntegrityError("Saved graph outcome belongs to another work item")
        return previous
    delivery = native_results.load_reading(reading_id)
    previous_receipts = _receipts(graph_id, {})
    if any(ref.call_status in {"reserved", "uncertain", "failed"} for ref in previous_receipts):
        uncertain = any(ref.call_status in {"reserved", "uncertain"} for ref in previous_receipts)
        outcome_type = Uncertain if uncertain else Failed
        outcome = outcome_type(receipt_refs=previous_receipts,
                               reason="A previous provider attempt needs review; automatic retry is disabled")
        return native_results.save_outcome(graph_id=graph_id, run_id=work_run_id, item_id=item_id,
                                          reading_id=reading_id, outcome=outcome)
    replayed, cached_refs = {}, []
    judge = engines.get(engine).judge
    adapter, provider = None, None
    if judge is not None:  # the judgement service's own answers under the native cache folder
        adapter_class = engines.judge_adapter(judge)
        provider = engines.judge_provider(judge)
        adapter = adapter_class(cache_dir=store.current_path().parent / "native" / "provider_cache"
                                / getattr(adapter_class, "cache_subdir", ""))

    def gpt_receipt(result):
        replayed[result.invocation_id] = (result.replayed, result.reused_from)

    def jev_receipt(reply):
        if not reply.cached:
            return
        # The adapter uses cached=True for both file-cache and same-step ledger
        # replay. The latter retains its original invocation and original cost.
        with store.connect() as c:
            for row in c.execute("SELECT i.id,a.payload FROM invocations i JOIN artifacts a ON a.kind=? "
                "AND a.artifact_id=CAST(i.id AS TEXT) WHERE i.run_id=? AND i.provider=? "
                "AND i.step_id LIKE ? ORDER BY i.id DESC",
                (calls.RESPONSE_KIND, graph_id, provider, f"{judge}:reader_semantic_support:%")):
                if json.loads(row["payload"])["response"] == reply.response.model_dump(mode="json"):
                    replayed[row["id"]] = (True, None)
                    return
        # A file-cache hit has no new invocation. Preserve the exact reused
        # answer as a normal private artifact, without inventing a call-log row.
        payload = {"response": reply.response.model_dump(mode="json"), "cache_key": reply.cache_key}
        response_sha = digest(json_bytes(payload))
        artifact_id = graph_id + ":" + response_sha
        store.save_artifact("native_cached_response", artifact_id, payload)
        cached_refs.append(ReceiptRef(kind="saved_cache", receipt_id="cache:" + response_sha,
            provider=provider, run_id=graph_id, step_id="reader_semantic_support", request_sha256=reply.cache_key,
            response_sha256=response_sha, artifact_kind="native_cached_response", artifact_id=artifact_id,
            call_status="cached", cost_known=True, cost_usd=Decimal(0), replayed=True))

    interpretation, failure, jev_reason = None, None, None
    try:
        ctx = calls.current()
        if ctx is None or ctx.budget_scope != work_run_id:
            raise ValueError("Native processing needs the matching work-run budget scope")
        for needed in ("openai", provider) if adapter is not None else ("openai",):
            if not calls.has_budget(work_run_id, needed):
                raise ValueError("Native processing needs an explicit provider budget")
        if not any(e.text for r in delivery.bundle.results for e in r.elements):
            raise ValueError("No readable source elements are available for interpretation")
        with calls.use_run(budget_scope=work_run_id, reuse=use_cache):
            interpretation = providers.extract_gpt(delivery, run_id=graph_id, isolated_store=store.active_path(),
                max_transfer_bytes=limits.max_transfer_bytes, max_output_tokens=limits.max_output_tokens,
                receipt_observer=gpt_receipt)
            if adapter is not None:
                from jav.ai.jev import JevUnavailableError
                try:
                    interpretation = native_verification.verify_jev(delivery, interpretation, run_id=graph_id,
                        isolated_store=store.active_path(), max_transfer_bytes=limits.max_transfer_bytes,
                        adapter=adapter, use_cache=use_cache, receipt_observer=jev_receipt)
                except JevUnavailableError as exc:
                    # 160 (review AI-5): the paid GPT facts stay, without the service's support; the saved outcome
                    # carries the `<service>_unavailable:<reason>` to-do of the other flows (265: the judgement
                    # service's own, `jav.ai.engine.judge_todo`), so a resume keeps it too
                    jev_reason = f"{engines.judge_todo(judge)}:{exc.reason}"
    except Exception as exc:
        # This is the explicit terminal application boundary. Keep only a safe
        # error class publicly; the existing call log retains private diagnostics.
        # 265 (code review AI-05): the traceback goes to the process log (never the item's public outcome)
        log.exception("the native interpretation failed")
        failure = exc
    receipts = _receipts(graph_id, replayed) + tuple(cached_refs)
    if failure is None:
        outcome = Succeeded(receipt_refs=receipts, reason=jev_reason)
    elif any(r.call_status in {"reserved", "uncertain"} for r in receipts):
        outcome = Uncertain(receipt_refs=receipts, reason="Provider outcome is uncertain; automatic retry is disabled")
    elif isinstance(failure, InterpretationRejected):
        outcome = Rejected(receipt_refs=receipts, reason="The received provider answer failed validation")
    else:
        outcome = Failed(receipt_refs=receipts, reason=_failure_reason(failure))
    return native_results.save_outcome(graph_id=graph_id, run_id=work_run_id, item_id=item_id,
        reading_id=reading_id, outcome=outcome, interpretation=interpretation if failure is None else None)
