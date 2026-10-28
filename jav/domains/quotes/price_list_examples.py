"""An invented price list as a process's example material (231, stage U, U1e; the owner's decision of 2026-10-28).

Plain-language summary: the IT quote prices a request from the newest active price list, and the live store had none,
so the quote could not be tried. The golden set of quotes (`configs/golden_quotes.json`) holds an invented seller's
price list with its discount rules; a process names it as example material (`{"kind": "price_list", "name":
"golden_quotes"}`). Installed, the examples' machine uploads the seller's sheet as a new list with the set's rules,
and the person installing it makes it active (the four eyes of the shared examples library); installed again, it
changes nothing. It is taken out only while no case keeps it and only if the machine made every version of it. The
golden set is read here as the file holds it (its reader, `invented_golden.py`, is the measurement's), and the sheet
is the seller's list as a CSV file, one row per item under the set's own column names.

- `list_name(golden)`: the example list's name (the seller's name and the list's version).
- `register()`: the example kind `price_list` for the shared examples library.

Layer: the quotes domain; it uses the price lists and the shared examples library.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from jav.core import cfg, identity, store
from jav.core.user_messages import explained
from jav.domains.quotes import price_lists

__all__ = ["KIND", "list_name", "register"]

KIND = "price_list"


def _golden(name: str) -> dict[str, Any]:
    return cfg.load(name)


def list_name(golden: dict[str, Any]) -> str:
    """The example list's name: the invented seller's name and the list's version."""
    return f"{golden['seller']['name']} {golden['price_list']['version']}"


def _sheet(prices: dict[str, Any]) -> bytes:
    """The seller's list as a CSV file: a header row of the set's column names, one row per item."""
    keys = ("sku", "name", "unit", "unit_price", "category")
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow([prices["columns"][k] for k in keys])
    writer.writerows([[item[k] for k in keys] for item in prices["items"]])
    return out.getvalue().encode("utf-8")


def _rows(name: str) -> list[Any]:
    """Every version of the example list (by its name), oldest first."""
    with store.connect() as c:
        return c.execute("SELECT price_list, version, state, made_by_id FROM price_lists WHERE name=? ORDER BY id",
                         (list_name(_golden(name)),)).fetchall()


def _state(name: str) -> dict[str, Any]:
    from jav.app import examples

    rows = _rows(name)
    active = [r for r in rows if r["state"] == "active"]
    state = examples.INSTALLED if active else examples.PARTIAL if rows else examples.MISSING
    return {"state": state, "example": bool(rows) and all(examples.is_example(r["made_by_id"]) for r in rows),
            "title": list_name(_golden(name))}


def _install(name: str, maker: identity.Who, approver: identity.Who) -> None:
    """The seller's sheet uploaded by `maker` with the set's rules and made active by `approver`; a list already
    there is made active if it is not."""
    golden = _golden(name)
    prices = golden["price_list"]
    rows = _rows(name)
    if any(r["state"] == "active" for r in rows):
        return
    if rows:
        latest = rows[-1]
        price_lists.activate(latest["price_list"], latest["version"], actor=approver)
        return
    # U3 (the backlog's example price list version): the sheet and its rules in one version
    made = price_lists.add(list_name(golden), "price_list.csv", _sheet(prices), actor=maker, currency=prices["currency"],
                           vat_percent=prices["vat_percent"], discounts=list(prices.get("discounts") or []))
    price_lists.activate(made["price_list"], made["version"], actor=approver)


def _remove(name: str, maker_id: str) -> None:
    """Every version of the example list taken out in one transaction, once no case keeps it and the examples'
    machine made all of them; otherwise nothing goes."""
    from jav.app import examples
    from jav.core.process import cases

    rows = _rows(name)
    if not rows:
        return
    if any(r["made_by_id"] != maker_id for r in rows):
        raise explained(examples.ExampleRefused, "a person made {{things}}: it is not example material to remove",
                        things=list_name(_golden(name)))
    ids = sorted({r["price_list"] for r in rows})
    with store.connect() as c:
        store.begin_immediate(c)
        if holding := cases.holding_in(c, [f'"{i}@' for i in ids]):
            raise explained(examples.ExampleInUse, "the example material stays: the cases {{cases}} keep it",
                            cases=", ".join(holding))
        c.executemany("DELETE FROM price_lists WHERE price_list=?", [(i,) for i in ids])


def register() -> None:
    from jav.app import examples

    examples.register(KIND, examples.ExampleKind(_state, _install, _remove))
