"""Task proposal from an email (058 K5.3): the business part of the legacy `10_AIFLOW_V4/flows/email-actions-bare`.

- **Proposal (GPT, Pydantic AI):** at most a few concrete human to-dos per email from the legacy action vocabulary, with
  the legacy v1.3.0 instruction verbatim (`jav/prompts/email_tasks_prompt.md`). Every to-do needs evidence: a JSON
  pointer into the input + a verbatim quote. The intent-recognition result is only a fallible hint (`intent_proposals`).
- **Gate (code):** the rules of the legacy `flow.py` `gate_result` / `_message_evidence` / `_field_claim` and of
  `shadowanalysis.evidence`. The evidence quote appears verbatim at the location pointed to, which can only be the
  email's subject or body; the deadline can only be a YYYY-MM-DD that appears verbatim; the assignee only a name /
  address that appears verbatim; an unknown action, an empty title or any faulty evidence drops the whole to-do, with a
  reason code. The evidence proves the origin, not the correctness.
- **A human decides:** even an accepted proposal is only a proposal (`approval="proposed"`); only a human can accept or
  dismiss it.

Difference from the legacy flow: attachment data are not evidence (they are produced as separate items in the same run),
so in the input an attachment appears only with its name and recognised type; emails to be archived are skipped
(`configs/email_tasks.json`), and since 066 Á28 so are emails suspected of an injected instruction and emails without
an intent result.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from jav import cfg, store
from jav.config import OPENAI_MODEL, OPENAI_SETTINGS, OPENAI_USD_PER_MTOK, PROMPTS_DIR, get_openai_key, load_prompt, openai_price
from jav.runtime import calls

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

CFG = cfg.load("email_tasks")
PROMPT_FILE = CFG["prompt_file"]
# 067 (066 Á18): besides the settings, the content of the instruction file is also part of the identifier
CONFIG_HASH = cfg.combine(cfg.config_hash("email_tasks"), cfg.file_digest(PROMPTS_DIR / PROMPT_FILE))
ACTIONS = tuple(CFG["actions"])
Action = Literal["review_invoice", "review_payment", "reply", "provide_document", "review_contract", "clarify", "review_information"]
assert set(ACTIONS) == set(Action.__args__), "az akció-szótár és a kimeneti séma eltér"


# --- GPT output (the structure of the legacy config/email_tasks/schema.json) --------------------------------------


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pointer: str
    quote: str


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    title: str
    due_date: str | None
    due_date_evidence: list[Evidence]
    assignee_hint: str | None
    assignee_evidence: list[Evidence]
    evidence: list[Evidence]


class MessageTasks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str
    tasks: list[Task]


class TaskOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[MessageTasks]


# --- input -------------------------------------------------------------------------------------------------------


def snapshot(*, message_id: str, subject: str, body: str, body_status: str, attachments: list[dict[str, Any]]) -> dict[str, Any]:
    """The proposal input: one email with its original subject and body (evidence can come only from these)."""
    completeness = "partial" if body_status == "capped" else "complete"
    return {"schema_version": 1, "messages": [{
        "message_id": message_id, "subject": subject or "", "body": (body or "")[: CFG["max_body_chars"]],
        "body_completeness": completeness,
        "attachments": [{"filename": a.get("filename"), "doc_type": a.get("doc_type")} for a in attachments],
    }]}


def request_payload(snap: dict[str, Any], intent_hint: dict[str, Any] | None) -> dict[str, Any]:
    """The user message: the snapshot, the source catalogue (as in legacy recipe 1.1) and the intent hint."""
    msg = snap["messages"][0]
    catalog = {"records": [{"record_id": msg["message_id"], "record_pointer": "/messages/0",
                            "field_pointers": {f: f"/messages/0/{f}" for f in CFG["evidence"]["allowed_fields"]}}]}
    hints = [{"message_id": msg["message_id"], **intent_hint}] if intent_hint else []
    return {"input_snapshot": snap, "source_catalog": catalog, "intent_proposals": hints}


# --- gate (the rules of the legacy gate) -----------------------------------------------------------------------------


def _resolve(doc: Any, pointer: str) -> Any:
    """Resolves an RFC 6901 JSON pointer; a non-existent location raises KeyError."""
    if pointer == "":
        return doc
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    cur = doc
    for raw in pointer[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            if not re.fullmatch(r"0|[1-9]\d*", part) or int(part) >= len(cur):
                raise KeyError(pointer)
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(pointer)
    return cur


def evidence(snap: dict[str, Any], refs: list[dict[str, Any]] | None, index: int = 0) -> tuple[list[dict[str, str]], list[str]]:
    """Checks the evidence (legacy `shadowanalysis.evidence` + `_message_evidence`): at least one, at most
    `max_refs`; each points to this email's subject or body, and the quote appears there verbatim."""
    ev = CFG["evidence"]
    prefix = f"/messages/{index}/"
    if not refs or len(refs) > ev["max_refs"]:
        return [], ["missing_or_unbounded_evidence"]
    accepted, issues = [], []
    for ref in refs:
        pointer, quote = ref.get("pointer"), ref.get("quote")
        if not isinstance(pointer, str) or not isinstance(quote, str):
            issues.append("invalid_evidence_shape")
            continue
        if not pointer.startswith(prefix):
            issues.append("evidence_outside_record")
            continue
        if not quote.strip() or len(quote) > ev["max_quote_chars"]:
            issues.append("invalid_evidence_quote")
            continue
        try:
            value = _resolve(snap, pointer)
        except KeyError:
            issues.append("evidence_pointer_missing")
            continue
        if not isinstance(value, str) or quote not in value:
            issues.append("evidence_quote_mismatch")
            continue
        if pointer[len(prefix):] not in ev["allowed_fields"]:
            issues.append("noncontent_evidence")
            continue
        accepted.append({"pointer": pointer, "quote": quote})
    if not accepted:
        issues.append("content_evidence_missing")
    return accepted, sorted(set(issues))


def _field_claim(snap: dict[str, Any], value: Any, refs: list[dict[str, Any]], *, is_date: bool = False) -> tuple[Any, list[str]]:
    """Deadline / assignee: null only with empty evidence; non-null only if the value appears verbatim in its own quote
    (a date must also be canonical YYYY-MM-DD)."""
    if value is None:
        return None, ([] if not refs else ["evidence_without_field_value"])
    accepted, issues = evidence(snap, refs)
    if not isinstance(value, str) or not value.strip() or not any(value in r["quote"] for r in accepted):
        issues.append("field_value_not_in_source_quote")
    if is_date:
        try:
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                issues.append("noncanonical_deadline")
        except ValueError:
            issues.append("noncanonical_deadline")
    return (value if not issues else None), sorted(set(issues))


_QUOTE_SHOWN_CHARS = 500  # this much of a dropped proposal's quote is kept for display


def _rejected(snap: dict[str, Any], n: int, task: dict[str, Any], parts: dict[str, list[str]]) -> dict[str, Any]:
    """062: the content of a dropped proposal is kept too (title, deadline, assignee, quotes checked one by one), along
    with which part failed — so it can be judged afterwards whether dropping it was justified. `details` is the old,
    merged list of reason codes."""
    quotes = []
    for part, key in (("evidence", "evidence"), ("due_date", "due_date_evidence"), ("assignee", "assignee_evidence")):
        for ref in task.get(key) or []:
            if isinstance(ref, dict):
                quote = ref.get("quote") if isinstance(ref.get("quote"), str) else ""
                quotes.append({"part": part, "pointer": ref.get("pointer"), "quote": quote[:_QUOTE_SHOWN_CHARS],
                               "ok": bool(evidence(snap, [ref])[0])})
    return {"code": "task_evidence_failed", "index": n, "action": task.get("action"),
            "title": task.get("title") if isinstance(task.get("title"), str) else None,
            "due_date": task.get("due_date"), "assignee_hint": task.get("assignee_hint"),
            "details": sorted({e for errs in parts.values() for e in errs}),
            "failed_parts": [p for p, errs in parts.items() if errs], "quotes": quotes}


def _norm_title(title: str) -> str:
    return " ".join(title.casefold().split()).rstrip(".!")


def _merge_duplicates(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """062: within one email the same to-do appears once. Two are the same if the action, deadline and assignee match
    and either the title (ignoring case, whitespace and trailing punctuation) or the set of quotes is identical. The
    first one stays, with the union of the evidence (at most `max_refs`); `merged` = how many identical proposals
    were merged into it."""
    out: list[dict[str, Any]] = []
    for task in tasks:
        quotes = {e["quote"] for e in task["evidence"]}
        same = next((k for k in out if (k["action"], k["due_date"], k["assignee_hint"]) == (task["action"], task["due_date"], task["assignee_hint"])
                     and (_norm_title(k["title"]) == _norm_title(task["title"]) or {e["quote"] for e in k["evidence"]} == quotes)), None)
        if same is None:
            out.append(task)
            continue
        seen = {(e["pointer"], e["quote"]) for e in same["evidence"]}
        extra = [e for e in task["evidence"] if (e["pointer"], e["quote"]) not in seen]
        same["evidence"] = (same["evidence"] + extra)[: CFG["evidence"]["max_refs"]]
        same["merged"] = same.get("merged", 0) + 1
    return out


def gate(snap: dict[str, Any], output: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(accepted proposals, dropped proposals with reasons). A faulty proposal is dropped as a whole; the field is not
    nulled. Identical proposals within one email are merged (062)."""
    message_id = snap["messages"][0]["message_id"]
    rows = [m for m in output.get("messages") or [] if m.get("message_id") == message_id]
    if len(rows) != 1 or len(output.get("messages") or []) != 1:
        return [], [{"code": "unknown_or_duplicate_tasks_message"}]
    accepted, rejected = [], []
    for n, task in enumerate(rows[0].get("tasks") or []):
        refs, errors = evidence(snap, task.get("evidence"))
        task_errors = []
        if task.get("action") not in ACTIONS:
            task_errors.append("unknown_task_action")
        if not isinstance(task.get("title"), str) or not task["title"].strip():
            task_errors.append("empty_task_title")
        deadline, date_errors = _field_claim(snap, task.get("due_date"), task.get("due_date_evidence") or [], is_date=True)
        assignee, assignee_errors = _field_claim(snap, task.get("assignee_hint"), task.get("assignee_evidence") or [])
        parts = {"task": task_errors, "evidence": errors, "due_date": date_errors, "assignee": assignee_errors}
        if any(parts.values()):
            rejected.append(_rejected(snap, n, task, parts))
            continue
        accepted.append({"action": task["action"], "title": task["title"].strip(), "due_date": deadline, "assignee_hint": assignee,
                         "evidence": refs, "approval": "proposed"})
    return _merge_duplicates(accepted), rejected


# --- GPT call (through the call log and the budget, like the G-path extraction) --------------------------------------


@lru_cache(maxsize=1)
def get_agent() -> Agent[None, TaskOutput]:
    model = OpenAIChatModel(OPENAI_MODEL, provider=OpenAIProvider(api_key=get_openai_key()))
    settings = OpenAIChatModelSettings(openai_reasoning_effort=OPENAI_SETTINGS["reasoning_effort"], temperature=OPENAI_SETTINGS["temperature"])
    return Agent(model, output_type=TaskOutput, instructions=load_prompt(CFG["prompt_file"]), model_settings=settings,
                 retries=OPENAI_SETTINGS["retries"])


def _price(actual: str | None) -> tuple[float, float] | None:
    price = OPENAI_USD_PER_MTOK.get(OPENAI_MODEL)
    if price is None or actual is None or not re.fullmatch(re.escape(OPENAI_MODEL) + r"(-\d{4}-\d{2}-\d{2})?", actual):
        return None
    return price


def _physical(agent, prompt: str, *, run_id: str, limited: bool) -> calls.Outcome:
    t0 = time.perf_counter()
    kwargs: dict[str, Any] = {}
    if limited:
        kwargs = {"model_settings": {"max_tokens": CFG["max_output_tokens"]},
                  "usage_limits": UsageLimits(request_limit=1 + int(OPENAI_SETTINGS["retries"]))}
    try:
        result = agent.run_sync(prompt, **kwargs)
    except Exception as exc:
        store.ledger_add(run_id=run_id, step="email_tasks", provider="openai", model=OPENAI_MODEL, input_tokens=None, output_tokens=None,
                         cost_usd=None, seconds=round(time.perf_counter() - t0, 3), config_hash=CONFIG_HASH, error=type(exc).__name__)
        raise
    usage = result.usage() if callable(result.usage) else result.usage
    in_tok, out_tok = usage.input_tokens or 0, usage.output_tokens or 0
    actual = getattr(getattr(result, "response", None), "model_name", None) or OPENAI_MODEL
    price = _price(actual)
    cost = None if price is None else round((in_tok * price[0] + out_tok * price[1]) / 1_000_000, 6)
    store.ledger_add(run_id=run_id, step="email_tasks", provider="openai", model=actual, input_tokens=in_tok, output_tokens=out_tok,
                     cost_usd=cost, seconds=round(time.perf_counter() - t0, 3), config_hash=CONFIG_HASH)
    return calls.Outcome(response=result.output.model_dump(mode="json"), model=actual, input_tokens=in_tok, output_tokens=out_tok,
                         cost_usd=None if cost is None else Decimal(str(cost)))


def extract(snap: dict[str, Any], *, intent_hint: dict[str, Any] | None, run_id: str) -> dict[str, Any]:
    """The raw GPT proposal (before the gate). In a worker run with an up-front budget reservation and the call log;
    on a repeat the saved response is returned (no second paid request)."""
    prompt = json.dumps(request_payload(snap, intent_hint), ensure_ascii=False, sort_keys=True)
    agent = get_agent()
    ctx = calls.current()
    if ctx is None:
        return _physical(agent, prompt, run_id=run_id, limited=False).response
    price = openai_price(OPENAI_MODEL)  # 066 Á38: no budgeted call without a price (the reservation would be zero)
    max_cost = calls.estimate_max_cost(
        input_chars=len(prompt) + len(load_prompt(CFG["prompt_file"])), max_output_tokens=CFG["max_output_tokens"],
        usd_per_mtok=(Decimal(str(price[0])), Decimal(str(price[1]))), physical_attempts=1 + int(OPENAI_SETTINGS["retries"]))
    digest = hashlib.sha256((CONFIG_HASH + prompt).encode("utf-8")).hexdigest()
    result = calls.invoke(run_id=run_id, step_id=f"openai:email_tasks:{digest[:16]}", provider="openai", model=OPENAI_MODEL,
                          max_cost_usd=max_cost, budget_scope=ctx.budget_scope, request_hash=digest,
                          fn=lambda: _physical(agent, prompt, run_id=run_id, limited=True))
    return result.response


def skip_reason(next_flow: str | None, *, signals: dict[str, float] | None = None, has_intent: bool = True) -> str | None:
    """Whether the proposal is skipped for the email (decided in code): for an email to be archived
    (`configs/email_tasks.json`), and, since 066 Á28, on the signal-driven suspicious route (the yes band of the
    injected-instruction signal, policy `email.signal_routes`) and without an intent result."""
    if next_flow and any(next_flow == p or next_flow.startswith(p + ":") for p in CFG["skip_route_prefixes"]):
        return "archived_route"
    from jav.policy import email_signal_route

    if email_signal_route(signals):
        return "suspicious_signal"
    if not has_intent:
        return "no_intent"
    return None


def propose(*, message_id: str, subject: str, body: str, body_status: str, attachments: list[dict[str, Any]],
            intent_hint: dict[str, Any] | None, run_id: str) -> dict[str, Any]:
    """Proposal + gate: `{"status": "proposed", "tasks": [...], "rejected": [...]}` (dropped ones with reasons)."""
    snap = snapshot(message_id=message_id, subject=subject, body=body, body_status=body_status, attachments=attachments)
    raw = extract(snap, intent_hint=intent_hint, run_id=run_id)
    tasks, rejected = gate(snap, raw)
    return {"status": "proposed", "tasks": tasks, "rejected": rejected, "config_hash": CONFIG_HASH}
