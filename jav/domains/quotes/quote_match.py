"""Which item of the seller's price list a requested item is (191, plan F-quote-package B4b).

Plain-language summary (DECISIONS 191): the quote proposes, for each item of the request, the price list item it is.
Code decides first: an item code written in the request is that item. Otherwise one request per requested item asks
three questions together (`configs/callsites/quote_match.json`): which item of the list it is (a Choice over the list's
items, by name, code, unit and group, plus none), whether the list sells such a thing at all, and whether the request
says enough to tell one item (several monitors, and no size asked). JEV answers them, or GPT with the same texts when
the application runs without JEV (`configs/gpt_quote_match.json`, `jav/ai/gpt_choice.py`). No price goes to the model: code
prices the line (`jav/domains/quotes/quote_pricing.py`).

An answer is marked with the default policy bands (`jav/ai/policy.py`, call site `quote.match`): `sure` (the list sells it,
the request is specific, and the choice is clear), `not_listed` (the list sells nothing of the kind, or none is chosen),
or `check` (anything between: the likely items are named as candidates). Nothing is decided here: a person reviews every
line of the quote (B5). The raw answer is kept with the mark, so a later band can be applied without asking again.

- `match(requested, context, prices, engine, run_id)`: one requested item's proposal;
- `golden(engine, limits, ...)`: the invented golden set's 37 requested items, each judged against its expected match.

Layer: business module of the quotes domain; its JEV questions go through the adapter (`ask`), its GPT ones through
`jav/ai/gpt_choice.py`, both under the caller's budget scope (`jav/core/calls.py`).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from typesafe_sdk import Choice, Noul

from jav.ai import policy
from jav.core import cfg
from jav.domains.quotes import price_lists
from jav.ai.jev import get_adapter
from jav.ai.jev import disabled as jev_disabled
from jav.core.config import RUNS_DIR
from jav.core import calls
from jav.tablequery import fold

REQUEST_ID = "quote_match"
CALLSITE = "quote.match"  # the policy bands' call site (the default set)
NONE = "none"
ENGINES = ("jev", "gpt")
PROVIDERS = {"jev": "jev", "gpt": "openai"}
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_WORD = re.compile(r"[0-9a-z]+")


def _site() -> dict[str, Any]:
    return cfg.load(f"callsite:{REQUEST_ID}")


def jev_hash() -> str:
    return cfg.config_hash(f"callsite:{REQUEST_ID}")


def gpt_hash() -> str:
    return cfg.config_hash(f"callsite:{REQUEST_ID}", "gpt_quote_match")


# --- code first ----------------------------------------------------------------------------------------------------------


def code_match(text: str, prices: price_lists.PriceList) -> price_lists.Item | None:
    """The item whose code the requested text names as a whole word (letter case aside); None if none or several do."""
    folded = fold(text)
    found = [i for i in prices.items if re.search(rf"(?<![0-9a-z]){re.escape(fold(i.sku))}(?![0-9a-z])", folded)]
    return found[0] if len(found) == 1 else None


def options(text: str, prices: price_lists.PriceList) -> list[price_lists.Item]:
    """The items offered: all of them, or from a longer list the `max_options` sharing the most words with the requested
    text (in the list's order)."""
    most = int(_site()["state"]["max_options"])
    if len(prices.items) <= most:
        return list(prices.items)
    words = set(_WORD.findall(fold(text)))
    shared = {i.sku: len(words & set(_WORD.findall(fold(f"{i.sku} {i.name} {i.category or ''}")))) for i in prices.items}
    kept = set(sorted(shared, key=lambda sku: -shared[sku])[:most])
    return [i for i in prices.items if i.sku in kept]


def option_keys(items: list[price_lists.Item]) -> list[str]:
    """The option names the model sees: an item's code when it can be one, else `item_<n>`."""
    keys: list[str] = []
    for n, item in enumerate(items, 1):
        key = item.sku if _KEY.match(item.sku) and item.sku.lower() != NONE and item.sku not in keys else f"item_{n}"
        keys.append(key)
    return keys


def _clip(text: Any) -> str:
    return str(text or "")[: int(_site()["state"]["max_text_chars"])]


def build_state(requested: dict[str, Any], context: list[str], items: list[price_lists.Item]) -> dict[str, Any]:
    """The requested item as written, the request's other items, and the price list as lines (no price)."""
    item = {"text": _clip(requested.get("description")), "quantity": str(requested.get("quantity") or ""),
            "unit": str(requested.get("unit") or "")}
    return {"requested_item": item, "request_items": [_clip(c) for c in context],
            "price_list": [f"{i.sku}: {i.name} (unit: {i.unit}{'; group: ' + i.category if i.category else ''})" for i in items]}


def _criterion(item: price_lists.Item) -> dict[str, str]:
    out = {"what": item.name, "code": item.sku, "unit": item.unit}
    return {**out, "group": item.category} if item.category else out


def build_questions(items: list[price_lists.Item]) -> dict[str, Choice | Noul]:
    q = _site()["questions"]
    criteria: dict[str, Any] = {key: _criterion(item) for key, item in zip(option_keys(items), items)}
    criteria[NONE] = q["item"]["none"]
    return {"item": Choice(instructions=q["item"]["instructions"], criteria=criteria),
            "listed": Noul(instructions=q["listed"]["instructions"], criteria=q["listed"]["criteria"]),
            "specific": Noul(instructions=q["specific"]["instructions"], criteria=q["specific"]["criteria"])}


def gpt_fields(items: list[price_lists.Item]) -> dict[str, list[str]]:
    return {"item": [*option_keys(items), NONE], "listed": ["yes", "no"], "specific": ["yes", "no"]}


def gpt_instructions(items: list[price_lists.Item]) -> str:
    """The same questions and option texts as JEV's, as one instruction text for GPT."""
    q = _site()["questions"]
    rows = [f"- {key}: {item.name} (code {item.sku}; unit {item.unit}{'; group ' + item.category if item.category else ''})"
            for key, item in zip(option_keys(items), items)]
    rows.append(f"- {NONE}: {q['item']['none']['what']} Not for: {q['item']['none']['not_for']}")
    return "\n\n".join([cfg.load("gpt_quote_match")["preamble"],
                        f"item: {q['item']['instructions']}\nOptions:\n" + "\n".join(rows),
                        f"listed: {q['listed']['instructions']} Answer yes or no.",
                        f"specific: {q['specific']['instructions']} Answer yes or no."])


# --- asking and judging --------------------------------------------------------------------------------------------------


def _judged(items: list[price_lists.Item], choice: str | None, dist: dict[str, float], confidence: float,
            listed: float, specific: float) -> dict[str, Any]:
    """The answer in the stored form, with its mark: the option keys mapped back to item codes."""
    by_key = dict(zip(option_keys(items), (i.sku for i in items)))
    distribution = {by_key.get(k, k): round(float(v), 4) for k, v in dist.items()}
    sku = by_key.get(choice or "")
    listed_band, specific_band = policy.noul_band(listed, CALLSITE), policy.noul_band(specific, CALLSITE)
    if sku is None or listed_band == "no":
        mark = "not_listed" if listed_band != "yes" else "check"
    elif listed_band == "yes" and specific_band != "no" and policy.choice_band(confidence, dist, CALLSITE) == "auto":
        mark = "sure"
    else:
        mark = "check"
    cand = _site()["candidates"]
    candidates = [k for k, p in sorted(distribution.items(), key=lambda kv: -kv[1])
                  if k != NONE and p >= float(cand["min_probability"])][: int(cand["max"])]
    # a line marked not listed proposes no item; the model's choice stays beside it (`choice`)
    proposed = None if mark == "not_listed" else sku
    return {"mark": mark, "sku": proposed, "choice": sku, "probability": distribution.get(sku) if sku else None,
            "confidence": round(confidence, 4), "listed": round(listed, 4), "specific": round(specific, 4),
            "candidates": candidates, "distribution": distribution}


def ask_jev(requested: dict[str, Any], context: list[str], items: list[price_lists.Item], *, run_id: str,
            use_cache: bool = True) -> dict[str, Any]:
    r = get_adapter().ask(REQUEST_ID, build_state(requested, context, items), build_questions(items), run_id=run_id,
                          use_cache=use_cache, config_hash=jev_hash())
    ch = r.response.choices["item"]
    out = _judged(items, ch.choice, {str(k): float(v) for k, v in dict(ch.probabilities).items()}, float(ch.confidence),
                  float(r.response.nouls["listed"].noul), float(r.response.nouls["specific"].noul))
    return {**out, "engine": "jev", "method": "jev", "measured": True, "model": r.call.model, "cost_usd": float(r.call.cost_usd)}


def _gpt():
    from jav.ai import gpt_choice  # loaded with the first GPT question (it brings openai and pydantic_ai)

    return gpt_choice


def _limits():
    g = cfg.load("gpt_quote_match")
    return _gpt().Limits(config_hash=gpt_hash(), max_output_tokens=int(g["max_output_tokens"]), top_logprobs=int(g["top_logprobs"]))


def ask_gpt(requested: dict[str, Any], context: list[str], items: list[price_lists.Item], *, run_id: str) -> dict[str, Any]:
    g = _gpt()
    a = g.ask(REQUEST_ID, gpt_instructions(items), json.dumps(build_state(requested, context, items), ensure_ascii=False),
              gpt_fields(items), run_id=run_id, limits=_limits())
    dist = {k: v for k, v in a.probabilities["item"].items() if k != g.OTHER_BRANCHES}
    confidence = a.confidence["item"]
    dist = dist or {a.values["item"]: float(confidence or 0.0)}
    out = _judged(items, a.values["item"], dist, float(confidence if confidence is not None else 0.0),
                  g.yes_probability(a.values["listed"], a.confidence["listed"]),
                  g.yes_probability(a.values["specific"], a.confidence["specific"]))
    return {**out, "engine": "gpt", "method": "gpt", "measured": a.measured, "model": a.call.model,
            "cost_usd": float(a.call.cost_usd)}


def match(requested: dict[str, Any], context: list[str], prices: price_lists.PriceList, *, engine: str, run_id: str,
          use_cache: bool = True) -> dict[str, Any]:
    """One requested item's proposal: an item code written in it (code, no call), else the engine's answer. The GPT
    engine runs with JEV switched off, so it cannot ask JEV even by mistake."""
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}: one of {ENGINES}")
    named = code_match(str(requested.get("description") or ""), prices)
    if named is not None:
        return {"mark": "sure", "sku": named.sku, "probability": 1.0, "confidence": 1.0, "listed": 1.0, "specific": 1.0,
                "candidates": [named.sku], "distribution": {named.sku: 1.0}, "engine": engine, "method": "code",
                "measured": True, "model": None, "cost_usd": 0.0}
    items = options(str(requested.get("description") or ""), prices)
    if engine == "jev":
        return ask_jev(requested, context, items, run_id=run_id, use_cache=use_cache)
    with jev_disabled():
        return ask_gpt(requested, context, items, run_id=run_id)


# --- the golden set ------------------------------------------------------------------------------------------------------


def _outcome(answer: dict[str, Any], expected: Any) -> str:
    """right; flagged (a person resolves it: a check that names the expected item or candidates); missed (a sure item
    sent to not listed, or a check without the expected item); silent (marked sure, but wrong)."""
    mark, sku = answer.get("mark"), answer.get("sku")
    if answer.get("error") or mark is None:
        return "failed"
    if expected.blocker == "ambiguous":
        if mark == "check" and set(expected.candidates) <= set(answer.get("candidates") or []):
            return "right"
        return "silent" if mark == "sure" else "missed"
    if expected.blocker == "not_in_price_list":
        return "right" if mark == "not_listed" else ("silent" if mark == "sure" else "flagged")
    if mark == "sure":
        return "right" if sku == expected.sku else "silent"
    if mark == "check":
        return "flagged" if expected.sku in (answer.get("candidates") or []) else "missed"
    return "missed"


def golden(*, engine: str, limits: dict[str, Decimal], use_cache: bool = True, out_dir: Path = RUNS_DIR,
           earlier_only: bool = False) -> dict[str, Any]:
    """The invented golden set's requested items (as written in `configs/golden_quotes.json`), each matched against the
    set's price list with the engine and judged against its expected match, under the owner's sub-budget (`limits`; an
    engine without one is refused before any call; `earlier_only`: without a budget, earlier answers only). Raw rows:
    `runs/<stamp>_quote_matches.jsonl`."""
    from jav.domains.quotes import invented_golden, quote_pricing

    if earlier_only:
        if limits:
            raise ValueError("earlier answers only take no budget")
        print(calls.NO_BUDGET_NOTE)
    elif PROVIDERS[engine] not in limits:
        raise ValueError(f"no budget for: {engine}")
    data = invented_golden.load()
    prices = quote_pricing.golden_price_list(data)
    cases = [c for c in data.cases if c.expected.request is not None]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scope = f"measure-{stamp}-quote-matches"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"{stamp}_quote_matches.jsonl"
    tally: Counter[str] = Counter()
    with calls.measurement(scope, limits, reuse=use_cache) as scope, raw.open("w", encoding="utf-8", newline="\n") as fh:
        for case in cases:
            written = [i.written for i in case.expected.request.items]
            for m in case.expected.matches:
                item = case.expected.request.items[m.item]
                requested = {"description": item.written, "quantity": str(item.quantity), "unit": item.unit}
                context = [w for n, w in enumerate(written) if n != m.item]
                try:
                    answer = match(requested, context, prices, engine=engine, run_id=scope, use_cache=use_cache)
                except Exception as exc:  # noqa: BLE001 - JEV unavailable, the budget spent or an OpenAI error: recorded, the run goes on
                    answer = {"error": f"{type(exc).__name__}: {exc}"}
                outcome = _outcome(answer, m)
                tally[outcome] += 1
                fh.write(json.dumps({"case": case.id, "item": m.item, "written": item.written, "expected_sku": m.sku,
                                     "expected_blocker": m.blocker, "outcome": outcome, **answer}, ensure_ascii=False) + "\n")
    return {"scope": scope, "raw": str(raw), "items": sum(tally.values()), "tally": dict(tally),
            "usage": calls.budget_usage(scope), "jev_config": jev_hash(), "gpt_config": gpt_hash()}


def print_golden(g: dict[str, Any]) -> None:
    t = g["tally"]
    print(f"quote:matches - {g['items']} requested items: right {t.get('right', 0)}, flagged for a person "
          f"{t.get('flagged', 0)}, missed {t.get('missed', 0)}, silently wrong {t.get('silent', 0)}, failed {t.get('failed', 0)}")
    print(f"raw: {g['raw']}")


__all__ = ["CALLSITE", "ENGINES", "NONE", "PROVIDERS", "REQUEST_ID", "ask_gpt", "ask_jev", "build_questions",
           "build_state", "code_match", "golden", "gpt_fields", "gpt_instructions", "jev_hash", "gpt_hash", "match",
           "option_keys", "options", "print_golden"]
