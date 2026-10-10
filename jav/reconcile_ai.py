"""134 (backlog F-pre-matching P3): AI proposals for the statement lines a reconciliation package still has to decide.

The owner's decisions of 2026-10-10 (DECISIONS 134): pair the statement lines and the invoices in advance with code and
with AI, JEV and GPT compared on the same lines, and let a person validate. Code (`jav/reconcile.py`) proposes a pair
only with an exactly equal amount and a signal; on a household's card statement most lines name a shop or a payment
app, so most of them stay without a candidate. Two judgements per line (`configs/callsites/reconcile_line.json`):

- **Which invoice it pays** (`pays`): a Choice over the invoices code preselected (`preselect`: the package's own and
  unclaimed invoices with something left to pay, in the invoice's payment window, within `amount_share` of the line's
  amount or among the code's candidates, at most `max_options`), plus `none`. JEV does no arithmetic and compares no
  dates, so every option carries the facts code computed (`option_facts`: how the amounts compare, when the line was
  booked relative to the issue and due dates, the payment method). Not asked when nothing is preselected.
- **What kind of payment it is** (`line_kind`): a utility or telecom bill, a subscription, a retail purchase, a transfer
  to a person, an own transfer, a bank fee, a tax ... A kind maps to a needs-no-invoice reason a person may accept
  (`kind_marks`) or says that an invoice is expected (`kind_expects_invoice`).

JEV gets both questions in one request (`JevAdapter.ask`, request-hash cache, ledger); GPT gets the same texts in one
structured request (`jav/gpt_choice.py`, `configs/gpt_reconcile.json`). The raw answers (choice, probability,
distribution) are kept per line and engine in `reconcile_ai_proposals`; nothing is decided, no threshold is applied.
`run` asks under the owner's sub-budget (`calls.measurement`: a provider without a limit is never called) and writes the
raw answers to `runs/<stamp>_reconcile_ai.jsonl`; an engine's failure on a line is recorded and the run goes on.

136 (DECISIONS 136, the owner chose once per partner): a run asks only about the lines without an answer of the engine (`redo`
asks them all again), and the kind of payment once per partner (`reconcile.name_key` of the counterparty name, as on the
pairing page). A line without preselected invoices takes over the answer its partner's line already has - from an
earlier run or from this one - without a call; the stored row names the line that was asked (`asked_line_id`). A line
with preselected invoices is still asked on its own, as which invoice it pays is its own question; a line through a
payment app (it pays many suppliers, 131) or without a name is asked alone. A failed answer is never lent.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from typesafe_sdk import Choice

from jav import cfg, gpt_choice, reconcile, reconcile_package, store
from jav.adapters.jev import JevUnavailableError, get_adapter
from jav.candidates import trim_after_legal_form
from jav.config import JEV_USD_PER_MTOK, RUNS_DIR
from jav.runtime import calls

ENGINES = ("jev", "gpt")
NONE = "none"
REQUEST_ID = "reconcile_line"

store.register_schema("reconcile_ai", """
-- 134: the AI's raw answers about one statement line, per engine (the latest); a person decides, nothing is applied
CREATE TABLE IF NOT EXISTS reconcile_ai_proposals (
    line_id           TEXT NOT NULL,
    engine            TEXT NOT NULL,      -- jev | gpt
    statement_doc_id  TEXT NOT NULL,
    workpackage_id    TEXT,
    options           TEXT NOT NULL,      -- JSON: the invoice ids offered, in option order (empty: `pays` not asked)
    pays              TEXT,               -- the chosen invoice id; NULL: none, not asked or failed
    pays_probability  REAL,               -- of the chosen option (none included)
    pays_distribution TEXT,               -- JSON: invoice id or "none" -> probability
    kind              TEXT,
    kind_probability  REAL,
    kind_distribution TEXT,               -- JSON: kind -> probability
    measured          INTEGER NOT NULL,   -- 0: GPT gave no log-probabilities (the choice alone)
    model             TEXT,
    config_hash       TEXT NOT NULL,
    scope             TEXT,               -- the budget scope of the measurement
    error             TEXT,
    created_at        TEXT NOT NULL,
    asked_line_id     TEXT,               -- 136: the partner's line that was asked, when this line took its kind over
    PRIMARY KEY (line_id, engine)
);
""")


def _migrate(conn: Any) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(reconcile_ai_proposals)")}
    if cols and "asked_line_id" not in cols:  # 136
        conn.execute("ALTER TABLE reconcile_ai_proposals ADD COLUMN asked_line_id TEXT")


store.register_migration("reconcile_ai", _migrate)


def _site() -> dict[str, Any]:
    return cfg.load("callsite:reconcile_line")


def jev_hash() -> str:
    return cfg.config_hash("callsite:reconcile_line")


def gpt_hash() -> str:
    return cfg.config_hash("gpt_reconcile", "callsite:reconcile_line")


def _limits() -> gpt_choice.Limits:
    g = cfg.load("gpt_reconcile")
    return gpt_choice.Limits(config_hash=gpt_hash(), max_output_tokens=int(g["max_output_tokens"]), top_logprobs=int(g["top_logprobs"]))


def _money(value: Any) -> Decimal | None:
    try:
        return abs(reconcile.money(str(value)))
    except ValueError:
        return None


def _payment(line: dict[str, Any]) -> dict[str, Any]:
    """The line as the core's helpers take it: what is left of it to pair, its currency and statement type."""
    return {"amount": str(_money(line.get("rest")) or ""), "currency": line.get("currency"), "statement_type": line.get("statement_type")}


def _left(invoice: dict[str, Any]) -> dict[str, Any]:
    return {**invoice, "amount": str(_money(invoice.get("rest")) or "")}


# --- the preselection and the facts (code) ------------------------------------------------------------------------------


def preselect(line: dict[str, Any], invoices: Iterable[dict[str, Any]], rates: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The invoices offered for one line of a package's workspace (`reconcile_package.workspace`): its own and unclaimed
    invoices with something left to pay, not rejected for this line, in the line's currency (or of another currency for a
    card line, by the conversion), in the invoice's payment window, within `amount_share` of what is left of the line or
    among the code's candidates; the code's candidates first, then the nearest amounts; at most `max_options`."""
    p = _site()["preselect"]
    rest, booked = _money(line.get("rest")), reconcile._date(line.get("booking_date"))
    if not rest or booked is None:
        return []
    payment = _payment(line)
    tied = {c["invoice_id"] for c in line.get("candidates") or []}
    rejected = set(line.get("rejected") or [])
    share = Decimal(str(p["amount_share"]))
    ranked = []
    for inv in invoices:
        left = _money(inv.get("rest"))
        if not inv.get("own") or not left or inv["id"] in rejected or reconcile._date(inv.get("issue_date")) is None:
            continue
        same = inv.get("currency") == line.get("currency")
        if not same and not (reconcile.fx_capable(payment) and reconcile.rate_need(inv)):
            continue
        start, end = reconcile.window(inv) if same else reconcile.fx_window(inv)
        if not start <= booked <= end:
            continue
        if same:
            gap = abs(rest - left) / left
        else:
            _relation, conversion = reconcile.convert(_left(inv), payment, rates)
            gap = abs(Decimal(conversion["deviation"])) if conversion else Decimal(1)
        if inv["id"] not in tied and gap > share:
            continue
        ranked.append((inv["id"] not in tied, gap, str(inv.get("issue_date")), inv["id"], inv))
    ranked.sort(key=lambda r: r[:4])
    return [r[4] for r in ranked[: int(p["max_options"])]]


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def option_facts(invoice: dict[str, Any], line: dict[str, Any], rates: dict[str, Any] | None = None) -> dict[str, str]:
    """One invoice option as the model sees it: who issued it and its number, how its amount compares with the line's,
    when the line was booked relative to its issue and due dates, and its payment method - computed here, as JEV does
    no arithmetic and compares no dates."""
    supplier = trim_after_legal_form(str(invoice.get("supplier_name") or "")).strip() or "an unknown supplier"
    facts = {"what": f"Invoice from {supplier}" + (f", number {invoice['number']}" if invoice.get("number") else "")}
    left, rest = _money(invoice.get("rest")), _money(line.get("rest"))
    whole = _money(invoice.get("amount"))
    amount = f"{left} {invoice.get('currency')}" + (f" left to pay of {whole}" if whole is not None and whole != left else "")
    if invoice.get("currency") == line.get("currency"):
        if left == rest:
            facts["amount"] = f"{amount}: the same amount as the line"
        elif left and rest:
            diff = (left - rest) / rest * 100
            facts["amount"] = f"{amount}: {abs(diff):.1f}% {'more' if diff > 0 else 'less'} than the line"
    else:
        _relation, conv = reconcile.convert(_left(invoice), _payment(line), rates)
        facts["amount"] = (f"{amount}: about {conv['converted']} {line.get('currency')} at the MNB rate of {conv['rate_day']}; "
                           f"the line is {Decimal(conv['deviation']) * 100:+.1f}% from it" if conv
                           else f"{amount}: no exchange rate known for its issue date")
    issue, booked = reconcile._date(invoice.get("issue_date")), reconcile._date(line.get("booking_date"))
    due = reconcile._date(invoice.get("due_date")) or issue
    if issue and booked and due:
        days = (booked - issue).days
        if days < 0:
            facts["timing"] = f"the line was booked {_days(-days)} before the issue date"
        elif booked <= max(due, issue):
            facts["timing"] = f"the line was booked {_days(days)} after the issue date, by the due date"
        else:
            facts["timing"] = f"the line was booked {_days(days)} after the issue date, {_days((booked - due).days)} after the due date"
    if invoice.get("payment_method"):
        facts["payment_method"] = str(invoice["payment_method"])
    return facts


def build_state(line: dict[str, Any]) -> dict[str, Any]:
    """The statement line as printed (its texts clipped), the account kind, the booking date and the amount."""
    most = int(_site()["state"]["max_text_chars"])
    out = {"account": "credit card" if line.get("statement_type") == "credit_card" else "bank account",
           "booking_date": line.get("booking_date"), "amount": f"{_money(line.get('amount'))} {line.get('currency')}"}
    if _money(line.get("rest")) != _money(line.get("amount")):
        out["left_to_pair"] = f"{_money(line.get('rest'))} {line.get('currency')}"
    for key, field in (("counterparty", "counterparty_name"), ("description", "description"), ("memo", "memo")):
        if line.get(field):
            out[key] = str(line[field])[:most]
    return {"line": out}


def option_keys(n: int) -> list[str]:
    return [f"invoice_{i}" for i in range(1, n + 1)]


def build_questions(facts: list[dict[str, str]]) -> dict[str, Choice]:
    """The JEV questions: the kind always, `pays` over the preselected invoices and `none` when there are any."""
    q = _site()["questions"]
    out = {"line_kind": Choice(instructions=q["line_kind"]["instructions"], criteria=q["line_kind"]["criteria"])}
    if facts:
        criteria: dict[str, Any] = dict(zip(option_keys(len(facts)), facts))
        criteria[NONE] = q["pays"]["none"]
        out["pays"] = Choice(instructions=q["pays"]["instructions"], criteria=criteria)
    return out


def gpt_fields(n_options: int) -> dict[str, list[str]]:
    out = {"pays": [*option_keys(n_options), NONE]} if n_options else {}
    out["line_kind"] = list(_site()["questions"]["line_kind"]["criteria"])
    return out


def gpt_instructions(facts: list[dict[str, str]]) -> str:
    """The same questions and option texts as JEV's, as one instruction text for GPT."""
    q = _site()["questions"]
    parts = [cfg.load("gpt_reconcile")["preamble"]]
    if facts:
        rows = [f"- {key}: " + "; ".join(facts_i.values()) for key, facts_i in zip(option_keys(len(facts)), facts)]
        none = q["pays"]["none"]
        rows.append(f"- {NONE}: {none['what']} Not for: {none['not_for']}")
        parts.append(f"pays: {q['pays']['instructions']}\nOptions:\n" + "\n".join(rows))
    kinds = [f"- {key}: {c['what']} Not for: {c['not_for']} Examples: {', '.join(c['examples'])}"
             for key, c in q["line_kind"]["criteria"].items()]
    parts.append(f"line_kind: {q['line_kind']['instructions']}\nKinds:\n" + "\n".join(kinds))
    return "\n\n".join(parts)


# --- asking ---------------------------------------------------------------------------------------------------------------


def _answer(options: list[str], pays: tuple[str | None, dict[str, float]] | None, kind: tuple[str | None, dict[str, float]],
            *, measured: bool, model: str | None, cost: float) -> dict[str, Any]:
    """One engine's answer in the stored form: the option keys mapped back to invoice ids."""
    by_key = dict(zip(option_keys(len(options)), options))
    out: dict[str, Any] = {"options": options, "pays": None, "pays_probability": None, "pays_distribution": None,
                           "measured": measured, "model": model, "cost_usd": cost, "error": None}
    if pays is not None:
        choice, dist = pays
        out["pays"] = by_key.get(choice or "")
        out["pays_probability"] = dist.get(choice or "") if choice else None
        out["pays_distribution"] = {by_key.get(k, k): round(float(v), 4) for k, v in dist.items()}
    choice, dist = kind
    out["kind"], out["kind_probability"] = choice, (dist.get(choice) if choice else None)
    out["kind_distribution"] = {k: round(float(v), 4) for k, v in dist.items()}
    return out


def ask_jev(line: dict[str, Any], invoices: list[dict[str, Any]], facts: list[dict[str, str]], *, run_id: str,
            use_cache: bool = True) -> dict[str, Any]:
    """Both questions about one line in one JEV request."""
    questions = build_questions(facts)
    r = get_adapter().ask(REQUEST_ID, build_state(line), questions, run_id=run_id, use_cache=use_cache, config_hash=jev_hash())
    choices = r.response.choices

    def picked(key: str) -> tuple[str | None, dict[str, float]]:
        ch = choices[key]
        return ch.choice, {str(k): float(v) for k, v in dict(ch.probabilities).items()}

    return _answer([inv["id"] for inv in invoices], picked("pays") if "pays" in questions else None, picked("line_kind"),
                   measured=True, model=r.call.model, cost=float(r.call.cost_usd))


def ask_gpt(line: dict[str, Any], invoices: list[dict[str, Any]], facts: list[dict[str, str]], *, run_id: str) -> dict[str, Any]:
    """The same questions about one line in one structured GPT request."""
    fields = gpt_fields(len(facts))
    a = gpt_choice.ask(REQUEST_ID, gpt_instructions(facts), json.dumps(build_state(line), ensure_ascii=False), fields,
                       run_id=run_id, limits=_limits())

    def picked(key: str) -> tuple[str | None, dict[str, float]]:
        dist = {k: v for k, v in a.probabilities[key].items() if k != gpt_choice.OTHER_BRANCHES}
        return a.values[key], dist or {a.values[key]: float(a.confidence[key] or 0.0)}

    return _answer([inv["id"] for inv in invoices], picked("pays") if "pays" in fields else None, picked("line_kind"),
                   measured=a.measured, model=a.call.model, cost=float(a.call.cost_usd))


# --- the package -------------------------------------------------------------------------------------------------------


Item = tuple[dict[str, Any], list[dict[str, Any]]]


def _lines(wp_id: str) -> tuple[list[dict[str, Any]], list[Item], dict[str, Any]]:
    """All the package's lines (with their stored answers), the ones a person still has to decide
    (`preselect.line_states`) each with its preselected invoices, and the exchange rates of the snapshot."""
    ws = reconcile_package.workspace(wp_id)
    rates = reconcile_package.scoped_snapshot(wp_id)[0].get("fx_rates") or {}
    states = set(_site()["preselect"]["line_states"])
    return ws["lines"], [(ln, preselect(ln, ws["invoices"], rates)) for ln in ws["lines"] if ln["state"] in states], rates


def partner(line: dict[str, Any]) -> str | None:
    """136: the key a line shares its kind of payment by - the partner of the pairing page (`reconcile.name_key`); none
    for a line through a payment app (it pays many suppliers, 131) or without a name, which is asked alone."""
    return None if reconcile.through_app(line) else reconcile.name_key(line.get("counterparty_name"))


def _order(line: dict[str, Any]) -> tuple[str, str]:
    return str(line.get("booking_date") or ""), line["id"]


def _usable(answer: dict[str, Any] | None) -> bool:
    return bool(answer) and not answer.get("error") and bool(answer.get("kind"))


def _lent(answer: dict[str, Any], asked_line_id: str) -> dict[str, Any]:
    """The partner's kind of payment as another line's answer: no invoice question, no cost."""
    return {"options": [], "pays": None, "pays_probability": None, "pays_distribution": None, "kind": answer.get("kind"),
            "kind_probability": answer.get("kind_probability"), "kind_distribution": answer.get("kind_distribution"),
            "measured": bool(answer.get("measured")), "model": answer.get("model"), "cost_usd": 0.0, "error": None,
            "asked_line_id": asked_line_id}


def _walk(engine: str, lines: list[dict[str, Any]], items: list[Item], ask: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]],
          *, redo: bool) -> Iterator[tuple[dict[str, Any], list[dict[str, Any]], str, dict[str, Any]]]:
    """136: one engine's steps over the lines to decide, as (line, its invoices, "asked" | "inherited", answer). A line
    with the engine's answer is left out (unless `redo`). The lines with preselected invoices are asked first, one by
    one; then a line without invoices takes over its partner's answer - stored earlier on any line of the package, or
    given in this run - and only a partner without one gets a call (its earliest line; the next one when it fails)."""
    answered = set() if redo else {ln["id"] for ln in lines if _usable((ln.get("ai") or {}).get(engine))}
    lenders: dict[str, tuple[str, dict[str, Any]]] = {}
    for ln in [] if redo else sorted(lines, key=_order):
        answer, key = (ln.get("ai") or {}).get(engine), partner(ln)
        if key and key not in lenders and _usable(answer):
            lenders[key] = (answer.get("asked_line_id") or ln["id"], answer)
    for line, invoices in sorted((it for it in items if it[0]["id"] not in answered), key=lambda it: (bool(not it[1]), *_order(it[0]))):
        key = partner(line)
        if not invoices and key in lenders:
            asked, answer = lenders[key]
            yield line, invoices, "inherited", _lent(answer, asked)
            continue
        answer = ask(line, invoices)
        yield line, invoices, "asked", answer
        if key and key not in lenders and _usable(answer):
            lenders[key] = (line["id"], answer)


def estimate(wp_id: str, *, redo: bool = False) -> dict[str, Any]:
    """Free: the lines to decide and, per engine, the plan of a run (`_walk`, every request taken as answered): the
    lines answered already, the requests (those with preselected invoices among them), the lines that would take a
    partner's answer over, and the sum of the worst-case reservations made before each request. A finished call counts
    with its actual cost, so a measurement needs its actual cost plus one reservation, not this sum."""
    lines, items, rates = _lines(wp_id)
    out: dict[str, Any] = {"lines": len(items), "with_options": sum(1 for _l, inv in items if inv),
                           "options": sum(len(inv) for _l, inv in items), "plan": {}, "reservations_usd": {}}
    for engine, provider in (("jev", "jev"), ("gpt", "openai")):
        total = Decimal(0)

        def planned(line: dict[str, Any], invoices: list[dict[str, Any]], engine: str = engine) -> dict[str, Any]:
            nonlocal total
            facts = [option_facts(inv, line, rates) for inv in invoices]
            if engine == "jev":
                body = json.dumps({"state": build_state(line), "questions": {k: q.model_dump(mode="json") for k, q in build_questions(facts).items()}},
                                  ensure_ascii=False)
                total += calls.estimate_max_cost(input_bytes=calls.utf8_bytes(body), max_output_tokens=0,
                                                 usd_per_mtok=(Decimal(str(JEV_USD_PER_MTOK)), Decimal(0)))
            else:
                total += gpt_choice.max_cost_usd(REQUEST_ID, gpt_instructions(facts), json.dumps(build_state(line), ensure_ascii=False),
                                                 gpt_fields(len(facts)), _limits())
            return {"kind": "planned"}

        plan = Counter(requests=0, with_options=0, inherited=0)
        for _line, invoices, how, _answer in _walk(engine, lines, items, planned, redo=redo):
            plan["requests" if how == "asked" else "inherited"] += 1
            plan["with_options"] += how == "asked" and bool(invoices)
        out["plan"][engine] = {"answered": len(items) - plan["requests"] - plan["inherited"], **plan}
        out["reservations_usd"][provider] = str(total.quantize(Decimal("0.000001")))
    return out


def _save(wp_id: str, line: dict[str, Any], engine: str, answer: dict[str, Any], scope: str | None) -> None:
    dump = lambda v: json.dumps(v, ensure_ascii=False) if v is not None else None  # noqa: E731
    with store.connect() as c:
        c.execute("INSERT INTO reconcile_ai_proposals(line_id, engine, statement_doc_id, workpackage_id, options, pays,"
                  " pays_probability, pays_distribution, kind, kind_probability, kind_distribution, measured, model, config_hash,"
                  " scope, error, created_at, asked_line_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                  " ON CONFLICT(line_id, engine) DO UPDATE SET statement_doc_id=excluded.statement_doc_id,"
                  " workpackage_id=excluded.workpackage_id, options=excluded.options, pays=excluded.pays,"
                  " pays_probability=excluded.pays_probability, pays_distribution=excluded.pays_distribution, kind=excluded.kind,"
                  " kind_probability=excluded.kind_probability, kind_distribution=excluded.kind_distribution,"
                  " measured=excluded.measured, model=excluded.model, config_hash=excluded.config_hash, scope=excluded.scope,"
                  " error=excluded.error, created_at=excluded.created_at, asked_line_id=excluded.asked_line_id",
                  (line["id"], engine, line["statement_id"], wp_id, dump(answer.get("options") or []), answer.get("pays"),
                   answer.get("pays_probability"), dump(answer.get("pays_distribution")), answer.get("kind"),
                   answer.get("kind_probability"), dump(answer.get("kind_distribution")), int(bool(answer.get("measured"))),
                   answer.get("model"), jev_hash() if engine == "jev" else gpt_hash(), scope, answer.get("error"),
                   datetime.now(timezone.utc).isoformat(timespec="seconds"), answer.get("asked_line_id")))


def run(wp_id: str, *, engines: Iterable[str], limits: dict[str, Decimal], max_lines: int | None = None,
        use_cache: bool = True, redo: bool = False, out_dir: Path = RUNS_DIR) -> dict[str, Any]:
    """Asks the chosen engines about the package's lines to decide, under the owner's sub-budget (`limits` per
    provider: `jev`, `openai`): only the lines without an answer (all with `redo`) and the kind of payment once per
    partner (`_walk`). Stores the latest answer per line and engine and writes one raw row per line and engine to a
    jsonl file. An engine that fails on a line (JEV unavailable, the budget spent, an OpenAI error) is recorded and the
    run goes on."""
    engines = [e for e in ENGINES if e in set(engines)]
    lines, items, rates = _lines(wp_id)
    items = items[:max_lines] if max_lines is not None else items
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scope = f"measure-{stamp}-reconcile-ai"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"{stamp}_reconcile_ai.jsonl"
    counts = {e: {"asked": 0, "inherited": 0, "skipped": 0, "pays": 0, "failed": 0} for e in engines}

    def asker(engine: str) -> Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]]:
        def ask(line: dict[str, Any], invoices: list[dict[str, Any]]) -> dict[str, Any]:
            facts = [option_facts(inv, line, rates) for inv in invoices]
            try:
                return (ask_jev(line, invoices, facts, run_id=scope, use_cache=use_cache) if engine == "jev"
                        else ask_gpt(line, invoices, facts, run_id=scope))
            except (JevUnavailableError, calls.BudgetExceeded, calls.UncertainAttempt) as exc:
                return {"options": [inv["id"] for inv in invoices], "measured": False, "error": f"{type(exc).__name__}: {exc}"}
            except Exception as exc:  # noqa: BLE001 - an OpenAI or schema error is recorded for this line, the run goes on
                return {"options": [inv["id"] for inv in invoices], "measured": False, "error": f"{type(exc).__name__}: {exc}"}
        return ask

    with calls.measurement(scope, limits), raw.open("w", encoding="utf-8", newline="\n") as fh:
        for engine in engines:
            steps = 0
            for line, _invoices, how, answer in _walk(engine, lines, items, asker(engine), redo=redo):
                _save(wp_id, line, engine, answer, scope)
                steps += 1
                counts[engine][how] += 1
                counts[engine]["pays"] += answer.get("pays") is not None
                counts[engine]["failed"] += answer.get("error") is not None
                fh.write(json.dumps({"engine": engine, "line_id": line["id"], "state": line["state"], "how": how, **answer},
                                    ensure_ascii=False) + "\n")
            counts[engine]["skipped"] = len(items) - steps
    return {"scope": scope, "raw": str(raw), "lines": len(items), "counts": counts, "usage": calls.budget_usage(scope),
            "jev_config": jev_hash(), "gpt_config": gpt_hash()}


def _pays_outcome(answer: dict[str, Any], paid: set[str], marked: bool) -> str:
    if not answer["options"]:
        return "not_offered" if paid else "not_asked"
    if paid and not paid & set(answer["options"]):
        return "not_offered"  # the preselection missed the invoice the person paired
    if marked:
        return "right" if answer["pays"] is None else "wrong"
    return "right" if answer["pays"] in paid else "missed" if answer["pays"] is None else "wrong"


def _kind_outcome(answer: dict[str, Any], marked: str | None) -> str:
    if marked:
        return "no_suggestion" if answer["suggested_mark"] is None else "agrees" if answer["suggested_mark"] == marked else "differs"
    return "agrees" if answer["expects_invoice"] else "differs" if answer["suggested_mark"] else "no_suggestion"


def evaluate(wp_id: str) -> dict[str, Any]:
    """135 (plan 134 P2): the stored answers against a person's decisions on the package's lines; free and read only.
    The person's decision is the reference: a line paired with invoices, or marked as needing no invoice with a reason;
    lines still open or left out are not counted. Per engine:

    - `pays`: `right` when the engine chose an invoice the person paired, or none for a marked line; `missed` when it
      chose none for a paired line; `wrong` for another invoice, or one for a marked line; `not_offered` when the
      invoice the person paired was not among the options (the preselection missed it); `not_asked` for a marked line
      without options.
    - `kind`: for a marked line `agrees` when the reason the kind suggests is the person's, `differs` when it suggests
      another, `no_suggestion` when it suggests none; for a paired line `agrees` when the kind expects an invoice,
      `differs` when it suggests a needs-no-invoice reason.

    An engine's failed answer counts as `failed` in both. Agreement with a person is measured here, not between the
    models (DECISIONS 134)."""
    ws = reconcile_package.workspace(wp_id)
    tally = {e: {"pays": Counter(), "kind": Counter()} for e in ENGINES}
    rows = []
    for ln in ws["lines"]:
        paid = {a["invoice_id"] for a in ln["allocations"]}
        marked = (ln.get("mark") or {}).get("category")
        if not ln.get("ai") or not (paid or marked):
            continue
        row: dict[str, Any] = {"line_id": ln["id"], "decision": "marked" if marked else "paired", "reason": marked}
        for engine, answer in ln["ai"].items():
            pays, kind = (("failed", "failed") if answer["error"] else
                          (_pays_outcome(answer, paid, bool(marked)), _kind_outcome(answer, marked)))
            tally[engine]["pays"][pays] += 1
            tally[engine]["kind"][kind] += 1
            row[engine] = {"pays": pays, "kind": kind}
        rows.append(row)
    return {"workpackage_id": wp_id, "lines_decided": len(rows), "rows": rows,
            "engines": {e: {k: dict(sorted(v.items())) for k, v in t.items()} for e, t in tally.items()}}


def proposals(line_ids: Iterable[str]) -> dict[str, dict[str, dict[str, Any]]]:
    """The stored answers of the lines, per line and engine, with the needs-no-invoice reason the kind suggests and
    whether the kind expects an invoice (for the pairing page); `asked_line_id` names the partner's line that was asked
    when the line took its kind over (136)."""
    ids = sorted(set(line_ids))
    site = _site()
    marks, expects = site["kind_marks"], set(site["kind_expects_invoice"])
    out: dict[str, dict[str, dict[str, Any]]] = {}
    if not ids:
        return out
    with store.connect() as c:
        for start in range(0, len(ids), 500):  # stays under the SQLite parameter limit
            chunk = ids[start:start + 500]
            for r in c.execute(f"SELECT * FROM reconcile_ai_proposals WHERE line_id IN ({','.join('?' * len(chunk))})", chunk):
                out.setdefault(r["line_id"], {})[r["engine"]] = {
                    "pays": r["pays"], "pays_probability": r["pays_probability"], "options": json.loads(r["options"] or "[]"),
                    "kind": r["kind"], "kind_probability": r["kind_probability"], "suggested_mark": marks.get(r["kind"] or ""),
                    "expects_invoice": (r["kind"] in expects) if r["kind"] else None, "measured": bool(r["measured"]),
                    "kind_distribution": json.loads(r["kind_distribution"]) if r["kind_distribution"] else None,
                    "model": r["model"], "asked_line_id": r["asked_line_id"], "error": r["error"], "created_at": r["created_at"]}
    return out
