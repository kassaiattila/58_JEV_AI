"""Budgeted native interpretation through the existing provider receipt ledger."""
from __future__ import annotations

from decimal import Decimal
import json
from typing import Any, Mapping

from jav import native_results, store
from jav.native_contracts import Failed, NativeLimits, ReceiptRef, Rejected, Succeeded, Uncertain
from jav.readers import providers
from jav.readers.pipeline import digest, json_bytes
from jav.readers.receipts import InterpretationRejected
from jav.runtime import calls


def estimate_limits(params: Mapping[str, Any]) -> NativeLimits:
    """Bound the actual GPT request and the JEV request plus alias resolution."""
    from jav.config import JEV_RETRY, JEV_USD_PER_MTOK, OPENAI_MODEL, OPENAI_SETTINGS, openai_price
    if params.get("arm") == "S":
        raise ValueError("Native interpretation does not support the S path")
    transfer, output = 80_000, 4000
    price = openai_price(OPENAI_MODEL)
    amounts = {"openai": calls.estimate_max_cost(input_bytes=transfer, max_output_tokens=output,
        usd_per_mtok=(Decimal(str(price[0])), Decimal(str(price[1]))),
        repeats=1 + int(OPENAI_SETTINGS["sdk_max_retries"]))}
    if params.get("jev", "on") != "off":
        # JEV's adapter serialises spaces around structural JSON tokens. Twice
        # the canonical transfer bound also covers that envelope; the separate
        # allowance covers its small, budgeted model-alias probe.
        amounts["jev"] = calls.estimate_max_cost(input_bytes=transfer * 2 + 4096, max_output_tokens=0,
            usd_per_mtok=(Decimal(str(JEV_USD_PER_MTOK)), Decimal(0)),
            repeats=1 + int(JEV_RETRY.get("max_retries", 0)))
    return NativeLimits(max_transfer_bytes=transfer, max_output_tokens=output, provider_limits_usd=amounts)


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
              jev: bool, use_cache: bool, limits: NativeLimits) -> str:
    """Return a saved terminal outcome reference, without repeating settled work."""
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

    def gpt_receipt(result):
        replayed[result.invocation_id] = (result.replayed, result.reused_from)

    def jev_receipt(reply):
        if not reply.cached:
            return
        # The adapter uses cached=True for both file-cache and same-step ledger
        # replay. The latter retains its original invocation and original cost.
        with store.connect() as c:
            for row in c.execute("SELECT i.id,a.payload FROM invocations i JOIN artifacts a ON a.kind=? "
                "AND a.artifact_id=CAST(i.id AS TEXT) WHERE i.run_id=? AND i.provider='jev' "
                "AND i.step_id LIKE 'jev:reader_semantic_support:%' ORDER BY i.id DESC",
                (calls.RESPONSE_KIND, graph_id)):
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
            provider="jev", run_id=graph_id, step_id="reader_semantic_support", request_sha256=reply.cache_key,
            response_sha256=response_sha, artifact_kind="native_cached_response", artifact_id=artifact_id,
            call_status="cached", cost_known=True, cost_usd=Decimal(0), replayed=True))

    interpretation, failure = None, None
    try:
        ctx = calls.current()
        if ctx is None or ctx.budget_scope != work_run_id:
            raise ValueError("Native processing needs the matching work-run budget scope")
        for provider in ("openai", "jev") if jev else ("openai",):
            if not calls.has_budget(work_run_id, provider):
                raise ValueError("Native processing needs an explicit provider budget")
        if not any(e.text for r in delivery.bundle.results for e in r.elements):
            raise ValueError("No readable source elements are available for interpretation")
        with calls.use_run(budget_scope=work_run_id, reuse=use_cache):
            interpretation = providers.extract_gpt(delivery, run_id=graph_id, isolated_store=store.active_path(),
                max_transfer_bytes=limits.max_transfer_bytes, max_output_tokens=limits.max_output_tokens,
                receipt_observer=gpt_receipt)
            if jev:
                from jav.adapters.jev import JevAdapter
                interpretation = providers.verify_jev(delivery, interpretation, run_id=graph_id,
                    isolated_store=store.active_path(), max_transfer_bytes=limits.max_transfer_bytes,
                    adapter=JevAdapter(cache_dir=store.current_path().parent / "native" / "provider_cache"),
                    use_cache=use_cache, receipt_observer=jev_receipt)
    except Exception as exc:
        # This is the explicit terminal application boundary. Keep only a safe
        # error class publicly; the existing call log retains private diagnostics.
        failure = exc
    receipts = _receipts(graph_id, replayed) + tuple(cached_refs)
    if failure is None:
        outcome = Succeeded(receipt_refs=receipts)
    elif any(r.call_status in {"reserved", "uncertain"} for r in receipts):
        outcome = Uncertain(receipt_refs=receipts, reason="Provider outcome is uncertain; automatic retry is disabled")
    elif isinstance(failure, InterpretationRejected):
        outcome = Rejected(receipt_refs=receipts, reason="The received provider answer failed validation")
    else:
        outcome = Failed(receipt_refs=receipts, reason=_failure_reason(failure))
    return native_results.save_outcome(graph_id=graph_id, run_id=work_run_id, item_id=item_id,
        reading_id=reading_id, outcome=outcome, interpretation=interpretation if failure is None else None)
