"""Szóréteg (045 K3b): egy irat szavai oldal-relatív (0–1) keretekkel, ahogy a futás beolvasta.

A futás beolvasó lépései (`load_pdf`, `ocr_pdf`) mentik el ugyanabból a szókészletből, amelyből a sorok (`layout`)
épültek: szövegréteg, helyi OCR vagy Azure-szöveg. Így a keret pontosan arra a szövegre mutat, amelyet a modell látott,
és utólag nem kell újra (esetleg fizetősen) olvasni. A réteg tartalom szerint azonosított (`layer_id` = a szavak és
oldalméretek hash-e), az állapotban csak ez a hivatkozás van.

Koordináták: `x0, y0, x1, y1` az oldal szélességéhez/magasságához viszonyítva, bal felső sarok az origó (a pdfplumber,
a tesseract és az Azure is így ad szókeretet pontban). A szó `line_no`-ja a `layout` sorszáma (1-alapú, dokumentum-szintű).
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any

from pydantic import BaseModel, Field

from jav import store

store.register_schema("source_layer", """
CREATE TABLE IF NOT EXISTS source_layers (
    layer_id    TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    text_source TEXT,
    engine      TEXT,
    pages       TEXT NOT NULL,              -- JSON: [{page, width_pt, height_pt}]
    words       TEXT NOT NULL,              -- JSON: [{id, page, line_no, text, x0, y0, x1, y1}]
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_source_layers_doc ON source_layers(doc_id);
""")


class Page(BaseModel):
    page: int  # 1-alapú
    width_pt: float
    height_pt: float


class Word(BaseModel):
    id: int  # 0-alapú, a rétegen belül olvasási sorrendben (oldal, sor, x)
    page: int
    line_no: int | None
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


class SourceLayer(BaseModel):
    layer_id: str
    doc_id: str
    text_source: str | None = None
    engine: str | None = None
    pages: list[Page] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)

    def words_on_line(self, line_no: int) -> list[Word]:
        return sorted((w for w in self.words if w.line_no == line_no), key=lambda w: w.x0)

    def by_id(self) -> dict[int, Word]:
        return {w.id: w for w in self.words}


def _clamp(v: float) -> float:
    return round(min(1.0, max(0.0, v)), 5)


def build(doc_id: str, pages_words: list[list[dict[str, Any]]], page_sizes: list[tuple[float, float]], *,
          text_source: str | None, engine: str | None) -> SourceLayer | None:
    """A beolvasó szókészletéből réteg; oldalméret nélkül vagy szavak nélkül nincs réteg (None)."""
    if not pages_words or not page_sizes or not any(pages_words):
        return None
    pages = [Page(page=i + 1, width_pt=w, height_pt=h) for i, (w, h) in enumerate(page_sizes)]
    raw: list[tuple[int, int, float, float, dict[str, Any]]] = []
    for page_no, words in enumerate(pages_words, 1):
        if page_no > len(page_sizes):
            break
        for w in words:
            if not str(w.get("text", "")).strip():
                continue
            raw.append((page_no, int(w.get("line_no") or 0), float(w["top"]), float(w["x0"]), w))
    raw.sort(key=lambda r: (r[0], r[1], r[3], r[2]))
    out: list[Word] = []
    for page_no, line_no, _top, _x0, w in raw:
        width, height = page_sizes[page_no - 1]
        out.append(Word(id=len(out), page=page_no, line_no=line_no or None, text=str(w["text"]),
                        x0=_clamp(float(w["x0"]) / width), x1=_clamp(float(w["x1"]) / width),
                        y0=_clamp(float(w["top"]) / height), y1=_clamp(float(w.get("bottom", w["top"])) / height)))
    body = json.dumps({"pages": [p.model_dump() for p in pages], "words": [w.model_dump() for w in out]},
                      sort_keys=True, separators=(",", ":"))
    layer_id = hashlib.sha256(f"{doc_id}:{body}".encode("utf-8")).hexdigest()[:24]
    return SourceLayer(layer_id=layer_id, doc_id=doc_id, text_source=text_source, engine=engine, pages=pages, words=out)


def save(layer: SourceLayer) -> str:
    """Idempotens mentés (ugyanaz a tartalom ugyanazt az azonosítót kapja)."""
    with store.connect() as c:
        c.execute("INSERT OR IGNORE INTO source_layers(layer_id, doc_id, text_source, engine, pages, words, created_at)"
                  " VALUES (?,?,?,?,?,?,?)",
                  (layer.layer_id, layer.doc_id, layer.text_source, layer.engine,
                   json.dumps([p.model_dump() for p in layer.pages]),
                   json.dumps([w.model_dump() for w in layer.words], ensure_ascii=False), store._now()))
    return layer.layer_id


# 061: a réteg tartalom szerint azonosított és soha nem módosul (`INSERT OR IGNORE`), ezért a betöltött réteg
# megtartható; az eredmény-összeállítás így egy javítás után nem olvassa és nem alakítja át újra az összes irat szavait.
# A kulcsban az adattár útvonala is benne van (tesztek, futáshelyi adattár). A réteget a hívók csak olvassák.
_loaded: OrderedDict[tuple[str, str], SourceLayer] = OrderedDict()
_loaded_lock = threading.Lock()
_LOADED_MAX = 256


def load(layer_id: str) -> SourceLayer | None:
    key = (str(store.active_path()), layer_id)
    with _loaded_lock:
        hit = _loaded.get(key)
        if hit is not None:
            _loaded.move_to_end(key)
            return hit
    with store.connect() as c:
        row = c.execute("SELECT * FROM source_layers WHERE layer_id=?", (layer_id,)).fetchone()
    if row is None:
        return None
    layer = SourceLayer(layer_id=row["layer_id"], doc_id=row["doc_id"], text_source=row["text_source"], engine=row["engine"],
                        pages=[Page(**p) for p in json.loads(row["pages"])], words=[Word(**w) for w in json.loads(row["words"])])
    with _loaded_lock:
        _loaded[key] = layer
        while len(_loaded) > _LOADED_MAX:
            _loaded.popitem(last=False)
    return layer


def save_from_pdftext(doc_id: str, pdf: Any) -> str | None:
    """A beolvasó lépések belépési pontja: `PdfText`-ből réteg, mentve; nincs szóadat → None (a folyamat nem áll meg)."""
    ocr_info = getattr(pdf, "ocr", None) or {}
    # 049: eszkalált szövegnél a szóhelyek a helyi OCR-ből jöhetnek (`words_from`) — a réteg motorja az, ahonnan a szavak valók
    engine = (ocr_info.get("words_from") or ocr_info.get("engine")) if ocr_info else ("pdfplumber" if pdf.text_source == "pdf" else None)
    layer = build(doc_id, pdf.words, pdf.page_sizes, text_source=pdf.text_source, engine=engine)
    return save(layer) if layer is not None else None
