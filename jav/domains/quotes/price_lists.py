"""Price lists: the seller's items and prices, their versions, and the rules that change a price (191, plan
F-quote-package B2).

Plain-language summary (DECISIONS 191): a person uploads the seller's price list as an Excel or CSV file, one row per
item with its code, name, unit, net unit price and (optionally) its category; the headers may be Hungarian or English
(`configs/price_lists.json`). The upload is checked: a refused file is not stored, and the check names every problem
with its row. A stored list is a version: a draft first, then made active (the active version before it is
superseded); a list can be retired. The rules that change a price (a volume discount: a line of a category from a
quantity on costs a percent less), the currency and the VAT rate are set on the settings page, not in the file, and
changing them makes a new draft version with the same items. So a version never changes, and a quote names the one it
was priced from by its number and fingerprint (which covers the items, the rules, the currency and the VAT rate).

An Excel file is read through the isolated native reader (`jav/readers/isolation.py`, its default limits); a CSV file
with the standard library, its separator (semicolon, comma or tab) found from its first line. No AI call.

Layer: business module of the quotes domain (`jav/domains/quotes/__init__.py`): the check and the store.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import secrets
from decimal import Decimal
from pathlib import PurePath
from typing import Any

from pydantic import BaseModel, ConfigDict

from jav import cfg, store
from jav.numbers import AmbiguousNumber, read_input
from jav.clock import utc_stamp as _now

CONFIG = "price_lists"
STATES = ("draft", "active", "superseded", "retired")
KEYS = ("sku", "name", "unit", "unit_price", "category")  # the columns, in the order a check names them

store.register_schema("price_lists", """
-- 191 (plan F-quote-package B2): a seller's price list, each upload or change of its settings a version that never
-- changes; the file it was read from is kept with every version
CREATE TABLE IF NOT EXISTS price_lists (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    price_list    TEXT NOT NULL,      -- the list's identifier, the same for all its versions
    name          TEXT NOT NULL,
    version       INTEGER NOT NULL,
    state         TEXT NOT NULL,      -- draft, active, superseded, retired
    change        TEXT NOT NULL,      -- upload: a file; settings: the rules, the currency or the VAT rate
    based_on      INTEGER,            -- a settings change: the version it started from
    currency      TEXT NOT NULL,
    vat_percent   TEXT NOT NULL,
    items         TEXT NOT NULL,      -- JSON: the items as read, in the file's order
    discounts     TEXT NOT NULL,      -- JSON: the rules, sorted by category and quantity
    fingerprint   TEXT NOT NULL,      -- sha256 of the items, the rules, the currency and the VAT rate
    file_name     TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    content       BLOB NOT NULL,
    checks        TEXT NOT NULL,      -- JSON: the upload's check (its warnings, the columns it found)
    made_by       TEXT NOT NULL,
    made_at       TEXT NOT NULL,
    activated_by  TEXT,
    activated_at  TEXT,
    retired_by    TEXT,
    retired_at    TEXT,
    UNIQUE (price_list, version)
);
""")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Item(_Model):
    sku: str
    name: str
    unit: str
    unit_price: Decimal  # net, in the list's currency
    category: str | None = None


class Discount(_Model):
    """A rule: a line of this category from `min_quantity` on costs `percent` less."""

    category: str
    min_quantity: Decimal
    percent: Decimal


class PriceList(_Model):
    """One version of a price list, as a quote is priced from it."""

    price_list: str
    name: str
    version: int
    state: str
    currency: str
    vat_percent: Decimal
    items: tuple[Item, ...]
    discounts: tuple[Discount, ...]
    fingerprint: str

    def item(self, sku: str) -> Item | None:
        return next((i for i in self.items if i.sku == sku), None)


class PriceListRefused(ValueError):
    """An upload or a change of the settings whose check found problems (`check`: the check as a dict)."""

    def __init__(self, check: dict[str, Any]) -> None:
        super().__init__("the price list was refused: " + "; ".join(
            f"{p['code']} {p['where']}".strip() for p in check["problems"]))
        self.check = check


class PriceListNotFound(KeyError):
    """No such price list or version."""


class PriceListStateError(ValueError):
    """The price list or version is not in a state that allows this (an active version made active again, a list
    without an active version retired, a change of the settings that changes nothing)."""


def config() -> dict[str, Any]:
    return cfg.load(CONFIG)


def _problem(code: str, where: str = "", detail: str = "") -> dict[str, str]:
    return {"code": code, "where": where, "detail": detail}


# --- reading a file -------------------------------------------------------------------------------------------------

_BRACKETED = re.compile(r"\s*[(\[][^)\]]*[)\]]\s*$")  # a trailing note: "Unit price (EUR)", "Price [HUF]"


def _header(text: str) -> str:
    """A header as the config lists it: lower case, the spaces collapsed, a trailing colon or bracketed note left out."""
    text = " ".join(str(text).split()).lower().rstrip(":").strip()
    return _BRACKETED.sub("", text).strip()


class _Unreadable(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code, self.detail = code, detail


# a sheet's cells: row -> column -> (kind, text), the kinds of the native reader (`jav/readers/contracts.py`)
Cells = dict[int, dict[int, tuple[str, str]]]


def _csv_cells(content: bytes) -> dict[str, Cells]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _Unreadable("unreadable", "not UTF-8 text") from exc
    first = text.splitlines()[0] if text else ""
    delimiter = max((";", ",", "\t"), key=first.count)
    rows: Cells = {}
    for r, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), 1):
        rows[r] = {c: ("text", value) for c, value in enumerate(row, 1) if value.strip()}
    return {"CSV": rows}


def _xlsx_cells(content: bytes, file_name: str) -> dict[str, Cells]:
    from jav.readers.isolation import run
    from jav.readers.limits import DEFAULT_LIMITS, ReadFailure

    try:
        response = run(content, file_name, DEFAULT_LIMITS)
    except ReadFailure as exc:
        raise _Unreadable("unreadable", exc.code) from exc
    sheets: dict[str, Cells] = {}
    for element in response.get("elements", []):
        if element.get("kind") != "cell" or element.get("hidden"):
            continue
        locator, cell = element["locator"], element["cell"]
        value = (cell.get("cached_value") or {"kind": "empty", "lexical": None}) if cell.get("formula") else cell["value"]
        if value.get("lexical") is None or not str(value["lexical"]).strip():
            continue
        sheets.setdefault(locator["sheet"], {}).setdefault(locator["row"], {})[locator["column"]] = (
            value["kind"], str(value["lexical"]))
    return sheets


def _cells(content: bytes, file_name: str) -> dict[str, Cells]:
    suffix = PurePath(file_name).suffix.lower()
    if suffix == ".csv":
        return _csv_cells(content)
    if suffix == ".xlsx":
        return _xlsx_cells(content, file_name)
    raise _Unreadable("not_a_table", suffix)


def _header_row(rows: Cells, known: dict[str, str], limit: int) -> tuple[int | None, dict[str, int], dict[str, str]]:
    """The first row within `limit` that names every required column; else (None, the best row's columns, its
    headers). `known`: a config header -> its column key."""
    best: tuple[int | None, dict[str, int], dict[str, str]] = (None, {}, {})
    required = {k for k, c in config()["columns"].items() if c["required"]}
    for r in sorted(rows)[:limit]:
        found: dict[str, int] = {}
        written: dict[str, str] = {}
        for c, (_kind, text) in sorted(rows[r].items()):
            key = known.get(_header(text))
            if key and key not in found:
                found[key], written[key] = c, text.strip()
        if required <= set(found):
            return r, found, written
        if len(found) > len(best[1]):
            best = (None, found, written)
    return best


def _price(kind: str, text: str) -> tuple[Decimal | None, str | None]:
    """A unit price and, when it cannot be read, the problem's code."""
    if kind in ("integer", "decimal"):
        value = Decimal(text)
    elif kind == "text":
        try:
            value = Decimal(read_input(text, kind="money"))
        except AmbiguousNumber:
            return None, "price_ambiguous"
        except ValueError:
            return None, "price_not_number"
    else:
        return None, "price_not_number"
    return (None, "price_negative") if value < 0 else (value, None)


def read(content: bytes, file_name: str) -> tuple[dict[str, Any], list[Item]]:
    """The check of a price list file and, when it has no problem, its items in the file's order. The check: `ok`,
    `problems` and `warnings` (each a code, where - `Sheet!row` - and a detail), the sheet read, the headers found per
    column, the number of items and their categories."""
    conf = config()
    check: dict[str, Any] = {"ok": False, "problems": [], "warnings": [], "sheet": None, "columns": {}, "items": 0,
                             "categories": []}
    try:
        sheets = _cells(content, file_name)
    except _Unreadable as exc:
        check["problems"].append(_problem(exc.code, "", exc.detail))
        return check, []
    known = {_header(h): key for key, col in conf["columns"].items() for h in col["headers"]}
    chosen = None
    best: tuple[int | None, dict[str, int], dict[str, str]] = (None, {}, {})
    for sheet, rows in sheets.items():
        head, found, written = _header_row(rows, known, conf["header_rows"])
        if head is not None:
            chosen = (sheet, head, found, written)
            break
        if len(found) > len(best[1]):
            best = (head, found, written)
    if chosen is None:
        required = [k for k in KEYS if conf["columns"][k]["required"]]
        check["problems"] += [_problem("missing_column", "", k) for k in required if k not in best[1]]
        return check, []
    sheet, head, found, written = chosen
    check["sheet"], check["columns"] = sheet, {k: written[k] for k in KEYS if k in written}
    others = [s for s in sheets if s != sheet and sheets[s]]
    if others:
        check["warnings"].append(_problem("other_sheets", "", ", ".join(others)))
    items: list[Item] = []
    seen: set[str] = set()
    for r in sorted(rows for rows in sheets[sheet] if rows > head):
        cells = {k: sheets[sheet][r].get(c) for k, c in found.items()}
        if not any(cells.values()):
            continue
        where = f"{sheet}!{r}"
        texts = {k: (v[1].strip() if v else "") for k, v in cells.items()}
        problems = []
        if not texts["sku"]:
            problems.append("sku_missing")
        elif texts["sku"].casefold() in seen:
            problems.append("duplicate_sku")
        for key in ("name", "unit"):
            if not texts[key]:
                problems.append(f"{key}_missing")
        price, wrong = (None, "price_missing") if cells["unit_price"] is None else _price(*cells["unit_price"])
        if wrong:
            problems.append(wrong)
        check["problems"] += [_problem(code, where, texts["sku"]) for code in problems]
        if texts["sku"]:
            seen.add(texts["sku"].casefold())
        if not problems and price is not None:
            items.append(Item(sku=texts["sku"], name=texts["name"], unit=texts["unit"], unit_price=price,
                              category=texts.get("category") or None))
    if not items and not check["problems"]:
        check["problems"].append(_problem("no_items"))
    if len(items) > conf["max_items"]:
        check["problems"].append(_problem("too_many_items", "", str(len(items))))
    check["ok"] = not check["problems"]
    check["items"] = len(items)
    check["categories"] = sorted({i.category for i in items if i.category})
    return check, items if check["ok"] else []


# --- the settings: the rules, the currency, the VAT rate --------------------------------------------------------------

_CURRENCY = re.compile(r"^[A-Z]{3}$")


def _number(raw: object) -> Decimal | None:
    try:
        return Decimal(read_input(raw, kind="number"))
    except ValueError:  # AmbiguousNumber is a ValueError too
        return None


def _settings(discounts: list[dict[str, Any]], currency: str, vat_percent: object,
              categories: set[str]) -> tuple[list[dict[str, str]], list[Discount], str, Decimal | None]:
    """The problems of the settings, and the rules (sorted), the currency and the VAT rate as they would be stored."""
    problems: list[dict[str, str]] = []
    rules: list[Discount] = []
    if len(discounts) > config()["max_rules"]:
        problems.append(_problem("too_many_rules", "", str(len(discounts))))
    for n, rule in enumerate(discounts, 1):
        where = f"rule {n}"
        category = str(rule.get("category") or "").strip()
        quantity, percent = _number(rule.get("min_quantity")), _number(rule.get("percent"))
        if category not in categories:
            problems.append(_problem("unknown_category", where, category))
        elif quantity is None or percent is None:
            problems.append(_problem("not_a_number", where))
        elif quantity <= 0:
            problems.append(_problem("quantity_not_positive", where))
        elif not 0 < percent < 100:
            problems.append(_problem("percent_out_of_range", where))
        elif any(r.category == category and r.min_quantity == quantity for r in rules):
            problems.append(_problem("duplicate_rule", where, category))
        else:
            rules.append(Discount(category=category, min_quantity=quantity, percent=percent))
    currency = str(currency or "").strip()
    if not _CURRENCY.match(currency):
        problems.append(_problem("currency", "", currency))
    vat = _number(vat_percent)
    if vat is None or not 0 <= vat < 100:
        problems.append(_problem("vat_percent", "", str(vat_percent)))
    return problems, sorted(rules, key=lambda r: (r.category, r.min_quantity)), currency, vat


def _label(value: Decimal) -> str:
    """A number's stored text ("10", "2.5", "489000"), the canonical form `read_input` gives."""
    text = format(value.normalize(), "f")
    return "0" if text == "-0" else text


def _rules_json(rules: list[Discount] | tuple[Discount, ...]) -> list[dict[str, str]]:
    return [{"category": r.category, "min_quantity": _label(r.min_quantity), "percent": _label(r.percent)} for r in rules]


def _items_json(items: list[Item] | tuple[Item, ...]) -> list[dict[str, Any]]:
    return [{"sku": i.sku, "name": i.name, "unit": i.unit, "unit_price": _label(i.unit_price), "category": i.category}
            for i in items]


def _fingerprint(currency: str, vat: Decimal, items: list[dict[str, Any]], rules: list[dict[str, str]]) -> str:
    body = {"currency": currency, "vat_percent": _label(vat), "items": items, "discounts": rules}
    return hashlib.sha256(cfg.canonical(body).encode("utf-8")).hexdigest()


# --- the store ------------------------------------------------------------------------------------------------------

_VIEW = ("price_list", "name", "version", "state", "change", "based_on", "currency", "vat_percent", "fingerprint",
         "file_name", "sha256", "made_by", "made_at", "activated_by", "activated_at", "retired_by", "retired_at")


def _view(row: Any) -> dict[str, Any]:
    out = {k: row[k] for k in _VIEW}
    out["items"] = len(json.loads(row["items"]))
    out["discounts"] = json.loads(row["discounts"])
    out["check"] = json.loads(row["checks"])
    return out


def _row(c: Any, price_list: str, version: int) -> Any:
    row = c.execute("SELECT * FROM price_lists WHERE price_list=? AND version=?", (price_list, version)).fetchone()
    if row is None:
        raise PriceListNotFound(f"{price_list} version {version}")
    return row


def _insert(c: Any, values: dict[str, Any]) -> None:
    c.execute(f"INSERT INTO price_lists({', '.join(values)}) VALUES ({', '.join('?' * len(values))})", tuple(values.values()))


def add(name: str, file_name: str, content: bytes, *, actor: str, price_list: str | None = None,
        currency: str | None = None, vat_percent: object = None) -> dict[str, Any]:
    """Checks and stores an upload as a draft version: of `price_list` (its next version, with the latest version's
    settings unless given; a rule whose category the new file no longer has is left out, with a warning), or of a new
    list (the config's default currency and VAT rate unless given). `PriceListRefused` with the check."""
    name = (name or "").strip()
    if not name:
        raise ValueError("a price list needs a name")
    conf = config()
    if len(content) > conf["max_bytes"]:
        raise PriceListRefused({"ok": False, "problems": [_problem("too_large", "", str(len(content)))], "warnings": [],
                                "sheet": None, "columns": {}, "items": 0, "categories": []})
    check, items = read(content, file_name)
    if not check["ok"]:
        raise PriceListRefused(check)
    with store.connect() as c:
        store.begin_immediate(c)
        rules: list[dict[str, Any]] = []
        if price_list is None:
            price_list, version = "pl-" + secrets.token_hex(5), 1
            currency = currency or conf["currency"]["default"]
            vat_percent = conf["vat_percent"] if vat_percent is None else vat_percent
        else:
            latest = c.execute("SELECT * FROM price_lists WHERE price_list=? ORDER BY version DESC LIMIT 1",
                               (price_list,)).fetchone()
            if latest is None:
                raise PriceListNotFound(price_list)
            version = latest["version"] + 1
            currency = currency or latest["currency"]
            vat_percent = latest["vat_percent"] if vat_percent is None else vat_percent
            for rule in json.loads(latest["discounts"]):
                if rule["category"] in check["categories"]:
                    rules.append(rule)
                else:
                    check["warnings"].append(_problem("rule_dropped", "", rule["category"]))
        problems, kept, currency, vat = _settings(rules, currency, vat_percent, set(check["categories"]))
        if problems or vat is None:
            raise PriceListRefused(check | {"ok": False, "problems": problems})
        stored_items, stored_rules = _items_json(items), _rules_json(kept)
        _insert(c, {"price_list": price_list, "name": name, "version": version, "state": "draft", "change": "upload",
                    "currency": currency, "vat_percent": _label(vat), "items": json.dumps(stored_items, ensure_ascii=False),
                    "discounts": json.dumps(stored_rules, ensure_ascii=False),
                    "fingerprint": _fingerprint(currency, vat, stored_items, stored_rules), "file_name": file_name,
                    "sha256": hashlib.sha256(content).hexdigest(), "content": content,
                    "checks": json.dumps(check, ensure_ascii=False), "made_by": actor, "made_at": _now()})
    return get(price_list, version)


def change_settings(price_list: str, version: int, *, discounts: list[dict[str, Any]], currency: str,
                    vat_percent: object, actor: str) -> dict[str, Any]:
    """A new draft version from `version`, with its items and file and these rules, currency and VAT rate.
    `PriceListRefused` with the problems; `PriceListStateError` when nothing would change."""
    with store.connect() as c:
        store.begin_immediate(c)
        base = _row(c, price_list, version)
        stored_items = json.loads(base["items"])
        categories = {i["category"] for i in stored_items if i["category"]}
        problems, rules, currency, vat = _settings(discounts, currency, vat_percent, categories)
        if problems or vat is None:
            raise PriceListRefused({"ok": False, "problems": problems, "warnings": [], "sheet": None, "columns": {},
                                    "items": len(stored_items), "categories": sorted(categories)})
        stored_rules = _rules_json(rules)
        fingerprint = _fingerprint(currency, vat, stored_items, stored_rules)
        if fingerprint == base["fingerprint"]:
            raise PriceListStateError(f"{price_list} version {version}: the settings are the same")
        latest = c.execute("SELECT MAX(version) AS n FROM price_lists WHERE price_list=?", (price_list,)).fetchone()["n"]
        _insert(c, {"price_list": price_list, "name": base["name"], "version": latest + 1, "state": "draft",
                    "change": "settings", "based_on": version, "currency": currency, "vat_percent": _label(vat),
                    "items": base["items"], "discounts": json.dumps(stored_rules, ensure_ascii=False),
                    "fingerprint": fingerprint, "file_name": base["file_name"], "sha256": base["sha256"],
                    "content": base["content"], "checks": base["checks"], "made_by": actor, "made_at": _now()})
    return get(price_list, latest + 1)


def get(price_list: str, version: int) -> dict[str, Any]:
    with store.connect() as c:
        return _view(_row(c, price_list, version))


def detail(price_list: str, version: int) -> dict[str, Any]:
    """A version's view with its items (the settings page's table) and the categories its rules may name."""
    with store.connect() as c:
        row = _row(c, price_list, version)
    items = json.loads(row["items"])
    return _view(row) | {"item_rows": items, "categories": sorted({i["category"] for i in items if i["category"]})}


def _model(row: Any) -> PriceList:
    return PriceList(price_list=row["price_list"], name=row["name"], version=row["version"], state=row["state"],
                     currency=row["currency"], vat_percent=Decimal(row["vat_percent"]),
                     items=tuple(Item(**i) for i in json.loads(row["items"])),
                     discounts=tuple(Discount(**d) for d in json.loads(row["discounts"])),
                     fingerprint=row["fingerprint"])


def version(price_list: str, version: int) -> PriceList:
    """A version as a quote is priced from it."""
    with store.connect() as c:
        return _model(_row(c, price_list, version))


def active(price_list: str) -> PriceList | None:
    with store.connect() as c:
        row = c.execute("SELECT * FROM price_lists WHERE price_list=? AND state='active'", (price_list,)).fetchone()
    return _model(row) if row is not None else None


def active_lists() -> list[dict[str, Any]]:
    """The active version of every list a quote can be priced from, newest list first: its identifier, name, version,
    currency, VAT rate, items and rules (191, B3)."""
    with store.connect() as c:
        rows = c.execute("SELECT * FROM price_lists WHERE state='active' ORDER BY id DESC").fetchall()
    return [{k: v[k] for k in ("price_list", "name", "version", "currency", "vat_percent", "items", "discounts", "fingerprint")}
            for v in map(_view, rows)]


def mark() -> tuple[Any, ...]:
    """What changes when a list is added, changed, activated or retired (a quote package's list mark)."""
    with store.connect() as c:
        return tuple(c.execute("SELECT COUNT(*), MAX(made_at), MAX(activated_at), MAX(retired_at) FROM price_lists").fetchone())


def content(price_list: str, version: int) -> tuple[bytes, str]:
    """The file a version was read from, and its file name."""
    with store.connect() as c:
        row = _row(c, price_list, version)
    return bytes(row["content"]), row["file_name"]


def listing() -> list[dict[str, Any]]:
    """Every price list, newest first, each with its versions (newest first), its active version and whether it is
    retired."""
    with store.connect() as c:
        rows = c.execute("SELECT * FROM price_lists ORDER BY id DESC").fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        v = _view(r)
        entry = out.setdefault(r["price_list"], {"price_list": r["price_list"], "name": r["name"], "active": None,
                                                 "retired": False, "versions": []})
        entry["versions"].append(v)
        if v["state"] == "active":
            entry["active"] = v["version"]
        if v["state"] == "retired":
            entry["retired"] = True
    return list(out.values())


def activate(price_list: str, version: int, *, actor: str) -> dict[str, Any]:
    """Makes the version the list's active one (a draft, or an earlier version again); the active one before it is
    superseded. A retired list comes back with it."""
    with store.connect() as c:
        store.begin_immediate(c)
        if _row(c, price_list, version)["state"] == "active":
            raise PriceListStateError(f"{price_list} version {version} is already active")
        c.execute("UPDATE price_lists SET state='superseded' WHERE price_list=? AND state IN ('active', 'retired')",
                  (price_list,))
        c.execute("UPDATE price_lists SET state='active', activated_by=?, activated_at=?, retired_by=NULL, retired_at=NULL"
                  " WHERE price_list=? AND version=?", (actor, _now(), price_list, version))
    return get(price_list, version)


def retire(price_list: str, *, actor: str) -> dict[str, Any]:
    """Retires the list: its active version is no longer offered for a new quote."""
    with store.connect() as c:
        store.begin_immediate(c)
        row = c.execute("SELECT version FROM price_lists WHERE price_list=? AND state='active'", (price_list,)).fetchone()
        if row is None:
            raise PriceListStateError(f"{price_list} has no active version")
        c.execute("UPDATE price_lists SET state='retired', retired_by=?, retired_at=? WHERE price_list=? AND version=?",
                  (actor, _now(), price_list, row["version"]))
    return get(price_list, row["version"])


__all__ = ["CONFIG", "KEYS", "STATES", "Discount", "Item", "PriceList", "PriceListNotFound", "PriceListRefused",
           "PriceListStateError", "activate", "active", "active_lists", "add", "change_settings", "config", "content",
           "detail", "get", "listing", "mark", "read", "retire", "version"]
