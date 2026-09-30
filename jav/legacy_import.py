"""047 T1.4: a régi projekt (10_AIFLOW_V4) korábbi eredményeinek behozatala ÖSSZEVETÉSRE.

A felhasználó döntése (2026-09-28, DECISIONS 046/3): a régi eredmények csak olvasva, az irat ujjlenyomata (sha256 =
a mi `doc_id`-nk) szerint párosítva, „régi rendszer” jelöléssel jönnek be; nem helyességi bizonyíték, és az új
eredményt semmi nem írja felül (külön tábla).

Forrás (CLAUDE.md §3: csak fájl, a régi üzemi adatbázist nem olvassuk): a régi köteg-exportok
`data/output/intake-batches/<köteg>/manifest.csv` (`document_id` → `sha256`, `doc_type`) és
`osszesitett-adatok.csv` (soronként egy irat, a mezők lapítva: `line_items.1.description`). A
`doc-extract-bare/<futás>/result.json` fájlokban nincs ujjlenyomat és mezőérték, ezért kimaradnak.

Összevetés (`compare`): iratonként a legutóbbi új futás adatai és a régi adatok, a típuscsomag normalizálásával
(pénz, dátum, adószám egységes alakban); mezőnként azonos / eltér / csak a régiben / csak az újban.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from jav import store

PRODUCER = "legacy:10_AIFLOW_V4"

store.register_schema("legacy_results", """
CREATE TABLE IF NOT EXISTS legacy_results (
    doc_id        TEXT NOT NULL,              -- sha256 a fájl tartalmáról (a mi doc_id-nk)
    legacy_id     TEXT NOT NULL,              -- a régi projekt dokumentum-azonosítója
    producer      TEXT NOT NULL,
    doc_type      TEXT,
    datapoints    TEXT NOT NULL,              -- JSON, a lapított oszlopokból visszaállítva
    is_valid      INTEGER,
    needs_review  INTEGER,
    source        TEXT NOT NULL,              -- a köteg mappája (a régi data/output alatt)
    imported_at   TEXT NOT NULL,
    PRIMARY KEY (doc_id, legacy_id)
);
""")

_META = {"doc_type", "id", "run_id", "created_at", "review_status", "ml_confidence", "detect_margin", "is_valid", "needs_review",
         "source_path", "source_filename", "target_filename"}


class LegacyRow(BaseModel):
    doc_id: str
    legacy_id: str
    doc_type: str | None
    datapoints: dict[str, Any]
    is_valid: bool | None
    needs_review: bool | None
    source: str


def _bool(v: str | None) -> bool | None:
    return {"true": True, "false": False}.get((v or "").strip().lower())


def _unflatten(row: dict[str, str]) -> dict[str, Any]:
    """`a.1.b` → a[0].b; üres cella nem adat; üres tétel elmarad."""
    out: dict[str, Any] = {}
    lists: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for col, val in row.items():
        if col in _META or val is None or val.strip() == "":
            continue
        parts = col.split(".")
        if len(parts) >= 3 and parts[1].isdigit():
            lists[parts[0]].setdefault(int(parts[1]), {})[".".join(parts[2:])] = val
        elif len(parts) == 2 and parts[1].isdigit():
            lists[parts[0]].setdefault(int(parts[1]), {})["*"] = val
        else:
            out[col] = val
    for name, items in lists.items():
        out[name] = [it["*"] if set(it) == {"*"} else it for _, it in sorted(items.items()) if it]
    return out


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_batches(root: Path) -> list[LegacyRow]:
    """A régi köteg-exportok (`<root>/intake-batches/*/`) sorai ujjlenyomattal; jegyzék nélküli sor kimarad."""
    rows: list[LegacyRow] = []
    for batch in sorted((root / "intake-batches").glob("*/")):
        manifest, summary = batch / "manifest.csv", batch / "osszesitett-adatok.csv"
        if not manifest.exists() or not summary.exists():
            continue
        sha = {m["document_id"]: m for m in _read_csv(manifest)}
        for r in _read_csv(summary):
            m = sha.get(r.get("id", ""))
            if not m or len(m.get("sha256", "")) != 64:
                continue
            rows.append(LegacyRow(doc_id=m["sha256"], legacy_id=r["id"], doc_type=r.get("doc_type") or m.get("doc_type"),
                                  datapoints=_unflatten(r), is_valid=_bool(r.get("is_valid")), needs_review=_bool(r.get("needs_review")),
                                  source=f"intake-batches/{batch.name}"))
    return rows


def import_batches(root: Path) -> dict[str, int]:
    rows = read_batches(root)
    inserted = 0
    with store.connect() as c:
        for r in rows:
            cur = c.execute(
                "INSERT OR IGNORE INTO legacy_results(doc_id, legacy_id, producer, doc_type, datapoints, is_valid, needs_review, source, imported_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (r.doc_id, r.legacy_id, PRODUCER, r.doc_type, json.dumps(r.datapoints, ensure_ascii=False),
                 None if r.is_valid is None else int(r.is_valid), None if r.needs_review is None else int(r.needs_review),
                 r.source, store._now()))
            inserted += cur.rowcount
    return {"rows": len(rows), "inserted": inserted}


def _canon(doc_type: str, dp: dict[str, Any]) -> dict[str, Any]:
    """A típuscsomag normalizálása mindkét oldalra (pénz, dátum, adószám egységes alakban); ismeretlen típus: nyersen."""
    from jav import typepack

    try:
        pack = typepack.get(doc_type)
    except FileNotFoundError:
        return {k: v for k, v in dp.items() if not isinstance(v, list)}
    rec, _ = pack.normalize(dp)
    return {k: v for k, v in rec.to_datapoints(pack.header_fields).items() if k != "line_items"}


def compare() -> dict[str, Any]:
    """Iratonként a legutóbbi új eredmény és a régi eredmény; típus- és mezőszintű egyezés. NEM pontosság."""
    fields: dict[str, dict[str, int]] = defaultdict(lambda: {"same": 0, "different": 0, "only_legacy": 0, "only_new": 0})
    docs = type_agree = 0
    with store.connect() as c:
        legacy = c.execute("SELECT doc_id, doc_type, datapoints FROM legacy_results").fetchall()
        for doc_id, legacy_type, legacy_dp in legacy:
            new = c.execute("SELECT doc_type, datapoints FROM datapoints WHERE doc_id = ? ORDER BY created_at DESC LIMIT 1", (doc_id,)).fetchone()
            if new is None:
                continue
            docs += 1
            new_type, new_dp = new
            type_agree += int(new_type == legacy_type)
            a, b = _canon(new_type, json.loads(new_dp)), _canon(legacy_type or new_type, json.loads(legacy_dp))
            for f in sorted(set(a) | set(b)):
                va, vb = a.get(f), b.get(f)
                if va in (None, "") and vb in (None, ""):
                    continue
                key = "only_legacy" if va in (None, "") else "only_new" if vb in (None, "") else "same" if str(va) == str(vb) else "different"
                fields[f][key] += 1
    return {"documents": docs, "legacy_rows": len(legacy), "type_agree": type_agree, "fields": dict(fields),
            "note": "agreement with the legacy system's output, not accuracy (neither side is a human label)"}
