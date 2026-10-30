"""The price lists as a Settings list (263, plan E, E1; the owner's decisions of 2026-10-30: one list everywhere): the
shared table of the price lists, each row its list's state, the version in use (else the newest) with its items and
rules, its currency and VAT rate; a row opens the list's page in Settings (`link="settings"`, section `prices`)."""

from __future__ import annotations

from typing import Any

from jav.app import datasets
from jav.app.datasets import Dataset, Rows, col
from jav.core import versions
from jav.domains.quotes import price_lists

_MARKS = {versions.ACTIVE: "done", versions.DRAFT: "trial", versions.RETIRED: "removed"}


def _state(x: dict[str, Any]) -> str:
    if x.get("retired"):
        return versions.RETIRED
    return versions.ACTIVE if x.get("active") is not None else versions.DRAFT


def _rows(_scope: dict[str, str]) -> Rows:
    cols = [
        col("name", "Name", link="settings", section="prices"),
        col("state", "State", "enum", labels="registry_state", badge=True, marks=_MARKS, group=True),
        col("version", "Version", "number"),
        col("items", "Items", "number"),
        col("rules", "Rules", "number"),
        col("currency", "Currency", "enum", group=True),
        col("vat_percent", "VAT rate (%)", "number"),
        col("made_by", "Saved by", "enum", group=True, hidden=True),
        col("made_at", "Saved", "datetime"),
    ]
    rows = []
    for x in price_lists.listing():
        v = next((v for v in x["versions"] if v["version"] == x.get("active")), x["versions"][0])
        rows.append({"_key": x["price_list"], "name": x["name"], "state": _state(x), "version": v["version"],
                     "items": v.get("items"), "rules": len(v.get("discounts") or []), "currency": v.get("currency"),
                     "vat_percent": v.get("vat_percent"), "made_by": v.get("made_by"), "made_at": v.get("made_at")})
    return cols, rows


DATASET = Dataset("settings_price_lists", "Price lists", (), _rows)


def register() -> None:
    datasets.register(DATASET, after="started_cases", module=__name__)


__all__ = ["DATASET", "register"]
