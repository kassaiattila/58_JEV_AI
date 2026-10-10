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
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

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
    PRIMARY KEY (line_id, engine)
);
""")


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


def lines_to_ask(wp_id: str) -> tuple[list[tuple[dict[str, Any], list[dict[str, Any]]]], dict[str, Any]]:
    """The package's lines a person still has to decide (`preselect.line_states`), each with its preselected invoices,
    and the exchange rates of the snapshot."""
    ws = reconcile_package.workspace(wp_id)
    rates = reconcile_package.scoped_snapshot(wp_id)[0].get("fx_rates") or {}
    states = set(_site()["preselect"]["line_states"])
    return [(ln, preselect(ln, ws["invoices"], rates)) for ln in ws["lines"] if ln["state"] in states], rates


def estimate(wp_id: str) -> dict[str, Any]:
    """Free: how many lines and options would be asked and, per engine, the sum of the worst-case reservations made
    before each call. A finished call counts with its actual cost, so a measurement needs its actual cost plus one
    reservation, not this sum."""
    items, rates = lines_to_ask(wp_id)
    jev_max = gpt_max = Decimal(0)
    for line, invoices in items:
        facts = [option_facts(inv, line, rates) for inv in invoices]
        body = json.dumps({"state": build_state(line), "questions": {k: q.model_dump(mode="json") for k, q in build_questions(facts).items()}},
                          ensure_ascii=False)
        jev_max += calls.estimate_max_cost(input_bytes=calls.utf8_bytes(body), max_output_tokens=0,
                                           usd_per_mtok=(Decimal(str(JEV_USD_PER_MTOK)), Decimal(0)))
        gpt_max += gpt_choice.max_cost_usd(REQUEST_ID, gpt_instructions(facts), json.dumps(build_state(line), ensure_ascii=False),
                                           gpt_fields(len(facts)), _limits())
    return {"lines": len(items), "with_options": sum(1 for _l, inv in items if inv), "options": sum(len(inv) for _l, inv in items),
            "reservations_usd": {"jev": str(jev_max.quantize(Decimal("0.000001"))), "openai": str(gpt_max.quantize(Decimal("0.000001")))}}


def _save(wp_id: str, line: dict[str, Any], engine: str, answer: dict[str, Any], scope: str | None) -> None:
    dump = lambda v: json.dumps(v, ensure_ascii=False) if v is not None else None  # noqa: E731
    with store.connect() as c:
        c.execute("INSERT INTO reconcile_ai_proposals(line_id, engine, statement_doc_id, workpackage_id, options, pays,"
                  " pays_probability, pays_distribution, kind, kind_probability, kind_distribution, measured, model, config_hash,"
                  " scope, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                  " ON CONFLICT(line_id, engine) DO UPDATE SET statement_doc_id=excluded.statement_doc_id,"
                  " workpackage_id=excluded.workpackage_id, options=excluded.options, pays=excluded.pays,"
                  " pays_probability=excluded.pays_probability, pays_distribution=excluded.pays_distribution, kind=excluded.kind,"
                  " kind_probability=excluded.kind_probability, kind_distribution=excluded.kind_distribution,"
                  " measured=excluded.measured, model=excluded.model, config_hash=excluded.config_hash, scope=excluded.scope,"
                  " error=excluded.error, created_at=excluded.created_at",
                  (line["id"], engine, line["statement_id"], wp_id, dump(answer.get("options") or []), answer.get("pays"),
                   answer.get("pays_probability"), dump(answer.get("pays_distribution")), answer.get("kind"),
                   answer.get("kind_probability"), dump(answer.get("kind_distribution")), int(bool(answer.get("measured"))),
                   answer.get("model"), jev_hash() if engine == "jev" else gpt_hash(), scope, answer.get("error"),
                   datetime.now(timezone.utc).isoformat(timespec="seconds")))


def run(wp_id: str, *, engines: Iterable[str], limits: dict[str, Decimal], max_lines: int | None = None,
        use_cache: bool = True, out_dir: Path = RUNS_DIR) -> dict[str, Any]:
    """Asks the chosen engines about the package's lines to decide, under the owner's sub-budget (`limits` per
    provider: `jev`, `openai`), stores the latest answer per line and engine and writes the raw answers to a jsonl file.
    An engine that fails on a line (JEV unavailable, the budget spent, an OpenAI error) is recorded and the run goes on."""
    engines = [e for e in ENGINES if e in set(engines)]
    items, rates = lines_to_ask(wp_id)
    items = items[:max_lines] if max_lines is not None else items
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scope = f"measure-{stamp}-reconcile-ai"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"{stamp}_reconcile_ai.jsonl"
    counts: dict[str, dict[str, int]] = {e: {"asked": 0, "pays": 0, "failed": 0} for e in engines}
    with calls.measurement(scope, limits), raw.open("w", encoding="utf-8", newline="\n") as fh:
        for line, invoices in items:
            facts = [option_facts(inv, line, rates) for inv in invoices]
            row: dict[str, Any] = {"line_id": line["id"], "state": line["state"], "options": [inv["id"] for inv in invoices]}
            for engine in engines:
                try:
                    answer = (ask_jev(line, invoices, facts, run_id=scope, use_cache=use_cache) if engine == "jev"
                              else ask_gpt(line, invoices, facts, run_id=scope))
                except (JevUnavailableError, calls.BudgetExceeded, calls.UncertainAttempt) as exc:
                    answer = {"options": row["options"], "measured": False, "error": f"{type(exc).__name__}: {exc}"}
                except Exception as exc:  # noqa: BLE001 - an OpenAI or schema error is recorded for this line, the run goes on
                    answer = {"options": row["options"], "measured": False, "error": f"{type(exc).__name__}: {exc}"}
                _save(wp_id, line, engine, answer, scope)
                counts[engine]["asked"] += 1
                counts[engine]["pays"] += answer.get("pays") is not None
                counts[engine]["failed"] += answer.get("error") is not None
                row[engine] = answer
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"scope": scope, "raw": str(raw), "lines": len(items), "counts": counts, "usage": calls.budget_usage(scope),
            "jev_config": jev_hash(), "gpt_config": gpt_hash()}


def proposals(line_ids: Iterable[str]) -> dict[str, dict[str, dict[str, Any]]]:
    """The stored answers of the lines, per line and engine, with the needs-no-invoice reason the kind suggests and
    whether the kind expects an invoice (for the pairing page)."""
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
                    "error": r["error"], "created_at": r["created_at"]}
    return out
