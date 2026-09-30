"""Doc-extract validator engine — PARITY PORT of flows/doc-extract/validator-engine.mjs.

Phase 2 (engine port): a byte-faithful Python reimplementation behind POST /validate. The JS
mirror in the doc-extract 'Shape and validate' Code node (and validator-engine.mjs) is the parity
ORACLE until the soak proves diff=0, then deleted.

PARITY DISCIPLINE — replicate the JS semantics VERBATIM:
  - the money parse uses FLOAT (JS Number() = IEEE-754 double = Python float) + Math.round, which
    is `_js_round(x) = floor(x + 0.5)`. Do NOT 'improve' to Decimal here — that would change
    rounding at .5 boundaries and break parity with the live mirror. (The Decimal-money invariant
    is enforced where the sidecar MINTS money — cost_usd — not in this behaviour-preserving port.)
  - the comparison math is all INTEGER minor-units (no float), exactly like the JS.
  - detail strings embed JS-formatted numbers; we format `minor / 10^decimals` via Decimal division
    (str(Decimal(n)/Decimal(d))) which reproduces JS String(n/d) for these int/{1,100} cases.

API: run_validation(datapoints, rules) -> {valid, checks:[{name,ok,code,detail?}], flags:[...], datapoints}

The opt-in utility_statement_balance check is new: its strict Decimal-string arithmetic is
independent of the legacy money parser and does not change the JS-parity validators.
"""
from __future__ import annotations

import math
import re
from decimal import Decimal, localcontext

# ---------------------------------------------------------------------------
# JS-coercion helpers (faithful to the operations the engine actually performs)
# ---------------------------------------------------------------------------

_UNDEF = object()  # JS `undefined` sentinel (distinct from None == JS `null`)


def _js_round(x: float) -> int:
    """JS Math.round(x) == floor(x + 0.5) for the values this engine sees."""
    return math.floor(x + 0.5)


def _js_str(v) -> str:
    """JS String(v) for the value kinds that reach detail strings."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if v == math.floor(v) and math.isfinite(v):
            return str(int(v))
        return repr(v)
    return str(v)


def _dp_str(dp: dict, key: str) -> str:
    """JS `'' + dp[key]`: 'undefined' when the key is absent, else String(value)."""
    if key not in dp:
        return "undefined"
    return _js_str(dp[key])


def _money_str(minor: int, decimals: int) -> str:
    """JS String(minor / 10**decimals) for an integer minor-unit value (int/{1,100})."""
    return str(Decimal(minor) / Decimal(10 ** decimals))


_SPACES = re.compile("[ \t\r\n  ]")  # space, tab, CR, LF, nbsp, narrow-no-break (verbatim)
_TRAIL_DEC = re.compile(r"[.,]([0-9]{1,2})$")
_NUM_SEP = re.compile(r"[.,]")


def _js_number(s: str):
    """JS Number(s): '' / whitespace -> 0.0; a numeric literal -> float; else None (NaN)."""
    s2 = s.strip()
    if s2 == "":
        return 0.0
    try:
        n = float(s2)
    except ValueError:
        return None
    return n  # isfinite check happens at the call site (NaN/inf handled there)


def to_minor_units(value, decimals=2):
    """Unified money parser (invoice HU-format + bank negative-sign handling) -> minor units."""
    if decimals is None:
        decimals = 2
    if value is None:
        return None
    if isinstance(value, bool):
        # JS typeof true === 'boolean' -> NOT the number path -> String(true/false) -> not numeric.
        s = "true" if value else "false"
    elif isinstance(value, (int, float)):
        if not math.isfinite(value):
            return None
        return _js_round(value * math.pow(10, decimals))
    else:
        s = str(value).strip()
    if not s:
        return None
    s = _SPACES.sub("", s)
    neg = s[0:1] == "-"
    if neg:
        s = s[1:]
    m = _TRAIL_DEC.search(s)
    if m:
        dec = m.group(1)
        sep = s[len(s) - len(dec) - 1]
        thousand = "." if sep == "," else ","
        s = s.replace(thousand, "")
        s = s.replace(sep, ".", 1)
    else:
        s = _NUM_SEP.sub("", s)
    n = _js_number(s)
    if n is None or not math.isfinite(n):
        return None
    return (-1 if neg else 1) * _js_round(n * math.pow(10, decimals))


def signed_minor(tx, decimals=2):
    if decimals is None:
        decimals = 2
    amt = to_minor_units(tx.get("amount") if isinstance(tx, dict) else None, decimals)
    if amt is None:
        return None
    mag = abs(amt)
    direction = str((tx or {}).get("direction")).lower()
    return -mag if direction == "debit" else mag


TOL_MINOR = 1  # bank-statement tolerance: one rounding fillér, never a transcription error
HU_TAXID_WEIGHTS = [9, 7, 3, 1, 9, 7, 3]


# ---------------------------------------------------------------------------
# JS Date.parse — byte-faithful to V8 at UTC for the year-first date forms the
# validator's date fields carry. The n8n container (TZ=UTC, where the OLD inline mirror
# ran) is the ground truth. Covers ISO date/datetime (T or space sep), HU-dotted/slash/
# spaced year-first (1-2 digit month/day, optional trailing dot, spaces around the
# separators), partial (YYYY / YYYY-MM), and V8's day-overflow ROLLOVER (e.g. 2022-02-30
# -> Mar 2 — the reachable OCR-digit-misread class). month in [1,12], day in [1,31], time
# HH:MM[:SS] range-checked (V8 does NOT roll the time over) — else NaN. Verified against a
# 45-vector n8n-container Date.parse battery: 0 reachable divergence (only the 5-digit-year
# form, unreachable, is a strict-subset reject). validator-parity.mjs carries the fixtures.
# Cutover-port fidelity: this fixes the matcher-class strict/lenient divergence (P2 #4 verify).
# ---------------------------------------------------------------------------
_YEAR_FIRST = re.compile(
    r"^\s*([0-9]{4})"
    r"(?:\s*[-./]\s*([0-9]{1,2})"
    r"(?:\s*[-./]\s*([0-9]{1,2}))?)?"
    r"\.?"
    r"(?:[ T]\s*([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?)?"
    r"\s*$"
)


def _date_ms(s: str):
    """JS Date.parse(s) in ms (UTC), or None (NaN) — byte-faithful to V8 at UTC."""
    import datetime

    m = _YEAR_FIRST.match(s)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) is not None else 1
    day = int(m.group(3)) if m.group(3) is not None else 1
    if not (1 <= month <= 12) or not (1 <= day <= 31):
        return None
    hh = int(m.group(4)) if m.group(4) is not None else 0
    mm = int(m.group(5)) if m.group(5) is not None else 0
    ss = int(m.group(6)) if m.group(6) is not None else 0
    if hh > 23 or mm > 59 or ss > 59:
        return None
    try:
        base = datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)
        d = base + datetime.timedelta(days=day - 1, hours=hh, minutes=mm, seconds=ss)
    except (ValueError, OverflowError):
        return None
    return int(d.timestamp() * 1000)


def _parse_for_order(v):
    """date_order's inner parse: falsy -> _UNDEF; NaN -> None; else ms timestamp."""
    if not v:
        return _UNDEF
    return _date_ms(str(v))


# ---------------------------------------------------------------------------
# Named validators — (datapoints, field?) -> {ok, code, detail?}
# ---------------------------------------------------------------------------


def vat_consistency(dp):
    decimals = 0 if str(dp.get("currency") or "").upper() == "HUF" else 2
    net = to_minor_units(dp.get("net_total"), decimals)
    vat = to_minor_units(dp.get("vat_total"), decimals)
    gross = to_minor_units(dp.get("gross_total"), decimals)
    if net is None or vat is None or gross is None:
        return {"ok": False, "code": "totals.unparseable",
                "detail": "net=" + _dp_str(dp, "net_total") + " vat=" + _dp_str(dp, "vat_total")
                          + " gross=" + _dp_str(dp, "gross_total")}
    tol = 1 if decimals == 0 else 2
    diff = abs(net + vat - gross)
    if diff <= tol:
        return {"ok": True, "code": "totals.ok"}
    return {"ok": False, "code": "totals.mismatch",
            "detail": "net+vat-gross=" + _money_str(net + vat - gross, decimals)
                      + " (" + (str(dp.get("currency")) if dp.get("currency") else "?") + ")"}


def date_order(dp):
    issue = _parse_for_order(dp.get("issue_date"))
    ful = _parse_for_order(dp.get("fulfillment_date"))
    due = _parse_for_order(dp.get("due_date"))
    if issue is None or ful is None or due is None:
        return {"ok": False, "code": "dates.unparseable",
                "detail": "issue=" + _dp_str(dp, "issue_date") + " ful=" + _dp_str(dp, "fulfillment_date")
                          + " due=" + _dp_str(dp, "due_date")}
    if issue is not _UNDEF and due is not _UNDEF and due < issue:
        return {"ok": False, "code": "dates.due_before_issue"}
    return {"ok": True, "code": "dates.ok"}


_TAXID_NON_HU = re.compile(r"[^0-9 \t.\-]")
_DIGITS_ONLY = re.compile(r"[^0-9]")


def hu_tax_id(dp, field):
    tax_id = dp.get(field)
    if not tax_id:
        return {"ok": False, "code": "taxid.missing"}
    raw = str(tax_id).strip()
    d = _DIGITS_ONLY.sub("", raw)
    if _TAXID_NON_HU.search(raw) or len(d) != 11:
        return {"ok": True, "code": "taxid.foreign", "detail": raw}
    s = 0
    for i in range(7):
        s += int(d[i]) * HU_TAXID_WEIGHTS[i]
    check = (10 - (s % 10)) % 10
    if check != int(d[7]):
        return {"ok": False, "code": "taxid.checkdigit", "detail": "expected " + str(check) + ", got " + d[7]}
    vat_code = int(d[8])
    if vat_code < 1 or vat_code > 5:
        return {"ok": False, "code": "taxid.vatcode", "detail": "A=" + str(vat_code)}
    county = int(d[9:11])
    county_ok = (2 <= county <= 20) or (22 <= county <= 44) or county == 51
    if not county_ok:
        return {"ok": False, "code": "taxid.county", "detail": "KK=" + d[9:11]}
    return {"ok": True, "code": "taxid.ok"}


# IBAN strip class: space, TAB, U+00A0 NBSP, dash — verbatim from validator-engine.mjs
# iban_check (NBSP is routine in printed/PDF/OCR'd bank docs; the P2 offline-port had
# dropped U+00A0 -> a real parity break caught by the cutover #4 adversarial-verify).
_IBAN_STRIP = re.compile("[ \t -]")
_IBAN_SHAPE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$")
_DIGITS_FULL = re.compile(r"^[0-9]+$")
_ALPHA = re.compile(r"[A-Z]")


def iban_check(dp, field):
    account = dp.get(field)
    if not account:
        return {"ok": False, "code": "account.missing"}
    s = _IBAN_STRIP.sub("", str(account)).upper()
    if _IBAN_SHAPE.match(s):
        if s.startswith("HU") and len(s) != 28:
            return {"ok": False, "code": "iban.hu_length", "detail": str(len(s)) + " chars"}
        rearranged = s[4:] + s[0:4]
        expanded = _ALPHA.sub(lambda c: str(ord(c.group(0)) - 55), rearranged)
        remainder = 0
        for i in range(0, len(expanded), 7):
            remainder = int(str(remainder) + expanded[i:i + 7]) % 97
        return {"ok": True, "code": "iban.ok"} if remainder == 1 else {"ok": False, "code": "iban.checksum"}
    if _DIGITS_FULL.match(s) and (len(s) == 16 or len(s) == 24):
        return {"ok": True, "code": "account.hu_domestic"}
    return {"ok": False, "code": "account.format", "detail": s[0:40]}


def running_balance_check(dp):
    txs = dp.get("transactions") if isinstance(dp.get("transactions"), list) else []
    with_bal = [t for t in txs if t and t.get("running_balance") is not None]
    if len(with_bal) == 0:
        return {"ok": True, "code": "balance.na"}
    bal = to_minor_units(dp.get("opening_balance"), 2)
    if bal is None:
        return {"ok": False, "code": "balance.opening_unparseable", "detail": _js_str(dp.get("opening_balance"))}
    for i in range(len(txs)):
        t = txs[i]
        s = signed_minor(t, 2)
        if s is None:
            return {"ok": False, "code": "balance.amount_unparseable", "detail": "line " + str(i + 1)}
        bal += s
        if t.get("running_balance") is None:
            continue
        rb = to_minor_units(t.get("running_balance"), 2)
        if rb is None:
            return {"ok": False, "code": "balance.running_unparseable", "detail": "line " + str(i + 1)}
        if abs(bal - rb) > TOL_MINOR:
            return {"ok": False, "code": "balance.discontinuity",
                    "detail": "line " + str(i + 1) + ": expected " + _money_str(rb, 2) + ", computed " + _money_str(bal, 2)}
    return {"ok": True, "code": "balance.ok"}


def closing_balance_check(dp):
    open_b = to_minor_units(dp.get("opening_balance"), 2)
    close = to_minor_units(dp.get("closing_balance"), 2)
    if open_b is None or close is None:
        return {"ok": False, "code": "closing.unparseable",
                "detail": "open=" + _dp_str(dp, "opening_balance") + " close=" + _dp_str(dp, "closing_balance")}
    txs = dp.get("transactions") if isinstance(dp.get("transactions"), list) else []
    s = 0
    for i in range(len(txs)):
        sm = signed_minor(txs[i], 2)
        if sm is None:
            return {"ok": False, "code": "closing.amount_unparseable", "detail": "line " + str(i + 1)}
        s += sm
    if abs(open_b + s - close) <= TOL_MINOR:
        return {"ok": True, "code": "closing.ok"}
    return {"ok": False, "code": "closing.mismatch", "detail": "open+S-close=" + _money_str(open_b + s - close, 2)}


def totals_consistency(dp):
    txs = dp.get("transactions") if isinstance(dp.get("transactions"), list) else []
    debit = 0
    credit = 0
    for i in range(len(txs)):
        amt = to_minor_units(txs[i].get("amount") if isinstance(txs[i], dict) else None, 2)
        if amt is None:
            return {"ok": False, "code": "totals.amount_unparseable", "detail": "line " + str(i + 1)}
        if str(txs[i].get("direction")).lower() == "debit":
            debit += abs(amt)
        else:
            credit += abs(amt)
    td = to_minor_units(dp.get("total_debit"), 2)
    tc = to_minor_units(dp.get("total_credit"), 2)
    probs = []
    if td is not None and abs(debit - abs(td)) > TOL_MINOR:
        probs.append("debit S=" + _money_str(debit, 2) + " vs stated " + _money_str(abs(td), 2))
    if tc is not None and abs(credit - abs(tc)) > TOL_MINOR:
        probs.append("credit S=" + _money_str(credit, 2) + " vs stated " + _money_str(abs(tc), 2))
    if td is None and tc is None:
        return {"ok": True, "code": "totals.na"}
    return {"ok": True, "code": "totals.ok"} if len(probs) == 0 else {"ok": False, "code": "totals.mismatch", "detail": "; ".join(probs)}


def period_dates(dp):
    start = _date_ms(str(dp.get("period_start"))) if dp.get("period_start") else None
    end = _date_ms(str(dp.get("period_end"))) if dp.get("period_end") else None
    if start is None or end is None:
        return {"ok": True, "code": "dates.no_window"}
    txs = dp.get("transactions") if isinstance(dp.get("transactions"), list) else []
    for i in range(len(txs)):
        bd = txs[i].get("booking_date") if (txs[i] and isinstance(txs[i], dict)) else None
        d = _date_ms(str(bd)) if bd else None
        if d is None:
            continue
        if d < start or d > end + 86400000:
            return {"ok": False, "code": "dates.out_of_period", "detail": "line " + str(i + 1) + ": " + _js_str(txs[i].get("booking_date"))}
    return {"ok": True, "code": "dates.ok"}


def _statement_money(value):
    """Normalized decimal strings only; separate from the legacy JS-parity money parser."""
    if not isinstance(value, str) or not re.fullmatch(r'[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?', value):
        return None
    return Decimal(value)


def utility_statement_balance(dp):
    """Arithmetic consistency of explicitly supplied component amounts; not source completeness.

    An explicit null applied_credit means no credit was extracted. Treat it as zero only
    in this calculation; neither the input fields nor gross_total are changed.
    """
    def unavailable(detail):
        return {'ok': False, 'code': 'statement.components_unavailable', 'scope': 'arithmetic_only',
            'detail': f'Arithmetic check unavailable: {detail}'}

    if not isinstance(dp, dict):
        return unavailable('datapoints must be an object')
    due = _statement_money(dp.get('amount_due'))
    if due is None:
        return unavailable('amount_due requires a normalized decimal string')
    rows = dp.get('service_invoices')
    if not isinstance(rows, list) or not rows:
        return unavailable('service_invoices requires a nonempty list')
    amounts = []
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or not {'service_provider', 'invoice_number', 'gross_amount'} <= row.keys()
                or any(row[key] is not None and not isinstance(row[key], str)
                       for key in ('service_provider', 'invoice_number'))):
            return unavailable(f'service_invoices[{index}] is not a complete component object')
        amount = _statement_money(row['gross_amount'])
        if amount is None:
            return unavailable(f'service_invoices[{index}].gross_amount requires a normalized decimal string')
        amounts.append(amount)
    if 'applied_credit' not in dp:
        return unavailable('applied_credit requires an explicit decimal string or null')
    credit = Decimal('0') if dp['applied_credit'] is None else _statement_money(dp['applied_credit'])
    if credit is None:
        return unavailable('applied_credit requires a normalized decimal string or explicit null')
    # Retain exact addition even for large supplied values; the default Decimal context can round.
    with localcontext() as context:
        context.prec = max(28, *(len(value.as_tuple().digits) for value in [*amounts, due, credit])) + len(str(len(rows))) + 3
        total = sum(amounts, Decimal('0'))
        expected = total + credit
        matches = expected == due
    assumption = 'null_as_zero' if dp['applied_credit'] is None else 'explicit'
    return {'ok': matches, 'code': 'statement.arithmetic_match' if matches else 'statement.amount_due_mismatch',
        'scope': 'arithmetic_only', 'credit_assumption': assumption,
        'detail': f'Arithmetic only: component sum {total:f} + applied credit {credit:f} = {expected:f}; '
                  f'amount_due {due:f}. Explicit null credit is treated as zero for this check; '
                  'source completeness and semantic correctness are not verified.'}


NAMED = {
    "vat_consistency": lambda dp, field=None: vat_consistency(dp),
    "date_order": lambda dp, field=None: date_order(dp),
    "hu_tax_id": hu_tax_id,
    "iban_check": iban_check,
    "running_balance_check": lambda dp, field=None: running_balance_check(dp),
    "closing_balance_check": lambda dp, field=None: closing_balance_check(dp),
    "totals_consistency": lambda dp, field=None: totals_consistency(dp),
    "period_dates": lambda dp, field=None: period_dates(dp),
    "utility_statement_balance": lambda dp, field=None: utility_statement_balance(dp),
}


# ---------------------------------------------------------------------------
# Transforms — (datapoints) -> NEW datapoints (run BEFORE the checks)
# ---------------------------------------------------------------------------


def derive_direction_from_running_balance(dp):
    txs = dp.get("transactions") if isinstance(dp.get("transactions"), list) else []
    prev = to_minor_units(dp.get("opening_balance"), 2)
    fixed = []
    for t in txs:
        rb = to_minor_units(t.get("running_balance") if isinstance(t, dict) else None, 2)
        if rb is None or prev is None:
            fixed.append(dict(t) if isinstance(t, dict) else t)
            continue
        out = dict(t)
        out["direction"] = "credit" if rb - prev >= 0 else "debit"
        prev = rb
        fixed.append(out)
    new_dp = dict(dp)
    new_dp["transactions"] = fixed
    return new_dp


TRANSFORMS = {"derive_direction_from_running_balance": derive_direction_from_running_balance}


# ---------------------------------------------------------------------------
# Declarative field checks
# ---------------------------------------------------------------------------
_FMT_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _check_format_date(value) -> bool:
    s = str(value)
    if not _FMT_DATE.match(s):
        return False
    return _date_ms(s) is not None


def _is_missing(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def run_validation(datapoints, rules):
    rules = rules or {}
    dp = datapoints or {}
    checks = []

    transforms = rules.get("transforms") if isinstance(rules.get("transforms"), list) else []
    for name in transforms:
        tf = TRANSFORMS.get(name)
        if not tf:
            checks.append({"name": "transform", "ok": False, "code": name + ".unknown"})
            continue
        dp = tf(dp)

    required = rules.get("required") if isinstance(rules.get("required"), list) else []
    for rf in required:
        if _is_missing(dp.get(rf)):
            checks.append({"name": "required", "ok": False, "code": rf + ".missing"})
        else:
            checks.append({"name": "required", "ok": True, "code": rf + ".present"})

    fields = rules.get("fields") or {}
    for fname in fields.keys():
        rule = fields.get(fname) or {}
        val = dp.get(fname)
        if _is_missing(val):
            continue
        if rule.get("format") == "date":
            checks.append({"name": fname, "ok": True, "code": "format.ok"} if _check_format_date(val)
                          else {"name": fname, "ok": False, "code": "format.date", "detail": str(val)})
        if rule.get("regex"):
            ok = re.search(rule["regex"], str(val)) is not None
            checks.append({"name": fname, "ok": True, "code": "regex.ok"} if ok
                          else {"name": fname, "ok": False, "code": "regex.mismatch", "detail": str(val)})

    named = rules.get("named") if isinstance(rules.get("named"), list) else []
    for spec in named:
        spec = spec or {}
        fn = NAMED.get(spec.get("check"))
        if not fn:
            checks.append({"name": str(spec.get("check")), "ok": False, "code": "validator.unknown"})
            continue
        if spec.get("optional") is True and spec.get("field") and _is_missing(dp.get(spec.get("field"))):
            continue
        res = fn(dp, spec.get("field"))
        merged = {"name": spec.get("check")}
        merged.update(res)
        checks.append(merged)

    flags = [c["name"] + ":" + c["code"] for c in checks if not c["ok"]]
    return {"valid": len(flags) == 0, "checks": checks, "flags": flags, "datapoints": dp}
