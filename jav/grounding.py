"""Source location (045 K3b, B2): for every extracted field, the words of the word layer the value comes from, and
their box.

Code-based, deterministic, no AI call (CLAUDE.md §4: format and source matching happen in code). It follows the
behaviour of the V4 `grounding/local.py`: better no box than a wrong box.

Methods (`method`):
- `pick` (S path): the selected candidate in its own line, with the words of the printed text span (`raw`) — an exact
  location; a span wrapped onto the next line(s) is followed in the same column.
- `pick_line` (S path, `approximate`): the chosen candidate cannot be found either verbatim or by search — the line
  the model chose from serves as an approximate box (so a field to be reviewed still has a location).
- `search`: the value is searched for in the whole layer, compared by the field's kind (money, date, tax number,
  IBAN, text). One location → a box; several different locations → `ambiguous` (no box, the locations become
  `alternatives`); nothing → `not_found`.
- `manual`: a person selected the words on the image (saved by the correction, `jav/corrections.py`).

Status (`status`): located | approximate | ambiguous | context_rejected | not_found | no_value | no_layer. The
alternatives (S path) are the other JEV candidates with their probabilities, also with boxes: the UI shows them as
clickable boxes.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from functools import lru_cache
from decimal import Decimal
from typing import Any

from jav import cfg
from jav.models import normalize_date, normalize_iban, normalize_money, normalize_tax_id
from jav.source_layer import SourceLayer, Word
from jav.typepack import CANDIDATE_KIND_OF

MAX_WINDOW = 12  # at most this many consecutive words for one value (name, address)
# a shorter window per kind: numbers, dates and identifiers wrap onto a few words at most (search cost)
KIND_WINDOW = {"money": 4, "date": 4, "tax_id": 4, "iban": 8, "invoice_number": 3, "currency": 2}
MAX_ALTERNATIVES = 3
MIN_ALTERNATIVE_P = 0.02
_DIGIT_GROUP = re.compile(r"^\d{1,3}$")
_EDGE_PUNCT = ".,;:()[]\"'„”"


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold().strip(_EDGE_PUNCT)


def _canon_fn(kind: str) -> Callable[[str], Any]:
    """The comparable form of a value by the field's kind (None = cannot be interpreted)."""
    if kind == "money":
        return lambda s: normalize_money(s)
    if kind == "date":
        return lambda s: normalize_date(s)
    if kind == "tax_id":
        return lambda s: normalize_tax_id(s) or _squash(s) or None
    if kind == "iban":
        return lambda s: normalize_iban(s) or _squash(s) or None
    if kind == "currency":  # 053: the document says "Ft" / "forint" / "€", the extracted value is an ISO code
        return lambda s: CURRENCY_SIGNS.get(_squash(s), _squash(s).upper()) or None
    return lambda s: _squash(s) or None


CURRENCY_SIGNS = {"ft": "HUF", "ft.": "HUF", "forint": "HUF", "huf": "HUF", "€": "EUR", "eur": "EUR", "euro": "EUR",
                  "$": "USD", "usd": "USD"}


def _canon(kind: str, value: Any) -> Any:
    if value is None or str(value).strip() == "":
        return None
    if kind == "money" and isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    try:
        return _canon_fn(kind)(str(value))
    except (ValueError, ArithmeticError):
        return None


def _lines(layer: SourceLayer) -> list[list[Word]]:
    """Lines in reading order; a word without a line number (old layer) stands on its own."""
    groups: dict[tuple[int, int], list[Word]] = {}
    for w in layer.words:
        groups.setdefault((w.page, w.line_no if w.line_no is not None else -w.id - 1), []).append(w)
    return [sorted(ws, key=lambda w: w.x0) for _, ws in sorted(groups.items(), key=lambda kv: (kv[0][0], min(w.id for w in kv[1])))]


def region(words: list[Word]) -> dict[str, Any]:
    """A box from words: the page (of the first word), per-line boxes, an overall box, the quote, the word ids."""
    page = words[0].page
    on_page = [w for w in words if w.page == page]
    by_line: dict[Any, list[Word]] = {}
    for w in on_page:
        by_line.setdefault(w.line_no if w.line_no is not None else round(w.y0, 3), []).append(w)
    boxes = [[round(min(w.x0 for w in ws), 5), round(min(w.y0 for w in ws), 5), round(max(w.x1 for w in ws), 5),
              round(max(w.y1 for w in ws), 5)] for ws in by_line.values()]
    boxes.sort(key=lambda b: (b[1], b[0]))
    bbox = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    return {"page": page, "bbox": bbox, "boxes": boxes, "word_ids": [w.id for w in words],
            "quote": " ".join(w.text for w in words)}


def _minimal(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Drops the (wider) windows that contain another match."""
    return [s for s in spans if not any(o != s and s[0] <= o[0] and o[1] <= s[1] for o in spans)]


def _windows(line: list[Word], match: Callable[[list[Word]], bool], *, kind: str, max_chars: int | None = None) -> list[tuple[int, int]]:
    spans = []
    width = KIND_WINDOW.get(kind, MAX_WINDOW)
    for i in range(len(line)):
        chars = 0
        for j in range(i + 1, min(len(line), i + width) + 1):
            chars += len(line[j - 1].text)
            if max_chars is not None and chars > max_chars:
                break  # the window is already longer than what we are looking for
            if match(line[i:j]):
                # part of a larger number ("700" in "12 700") - but a wide horizontal gap is a column boundary
                # (053: table columns)
                if kind == "money" and i > 0 and _DIGIT_GROUP.match(line[i - 1].text) and line[i].x0 - line[i - 1].x1 <= COLUMN_GAP:
                    continue
                if (kind == "money" and j < len(line) and _DIGIT_GROUP.match(line[j].text) and len(line[j].text) == 3
                        and line[j].x0 - line[j - 1].x1 <= COLUMN_GAP):
                    continue
                spans.append((i, j))
    return _minimal(spans)


def locate_raw(layer: SourceLayer, line_no: int, raw: str) -> list[Word] | None:
    """The printed text span (`raw`) in the given line: the shortest matching word run, or None."""
    target = _squash(raw)
    if not target:
        return None
    line = layer.words_on_line(line_no)
    exact = _windows(line, lambda ws: _squash("".join(w.text for w in ws)) == target, kind="text", max_chars=len(target) + 4)
    if exact:
        i, j = exact[0]
        return line[i:j]
    loose = _windows(line, lambda ws: target in _squash("".join(w.text for w in ws)), kind="text", max_chars=len(target) + 40)
    if loose:  # the word written together with the label or punctuation ("Adószám:13570008-1-13", tax number)
        i, j = min(loose, key=lambda s: s[1] - s[0])
        return line[i:j]
    return _wrapped(layer, line_no, target)


WRAP_MAX_LINES = 2  # a printed text span may wrap onto this many following lines


def _prefix_run(line: list[Word], start: int, target: str) -> list[Word]:
    """The longest word run from `start` whose joined text is a prefix of `target`."""
    run: list[Word] = []
    for w in line[start:]:
        if not target.startswith(_squash("".join(x.text for x in [*run, w]))):
            break
        run.append(w)
    return run


def _wrapped(layer: SourceLayer, line_no: int, target: str) -> list[Word] | None:
    """A text span wrapped onto several lines (e.g. the IBAN of the NAV template: "HU69 … 0000" + "0000" below it): the
    start is in the chosen line, the continuation in the following lines, in the same column (the first word of the
    continuation falls under the part already found, so a label at the start of the line is left out)."""
    line = layer.words_on_line(line_no)
    for start in range(len(line)):
        words = _prefix_run(line, start, target)
        if not words:
            continue
        x0, x1 = words[0].x0, max(w.x1 for w in words)
        for nxt in range(line_no + 1, line_no + 1 + WRAP_MAX_LINES):
            rest = target[len(_squash("".join(w.text for w in words))):]
            if not rest:
                break
            below = layer.words_on_line(nxt)
            k = next((i for i, w in enumerate(below) if w.x0 < x1 and w.x1 > x0), None)
            part = _prefix_run(below, k, rest) if k is not None else []
            if not part:
                break
            words += part
        if _squash("".join(w.text for w in words)) == target and words[-1].line_no != line_no:
            return words
    return None


def search(layer: SourceLayer, kind: str, value: Any) -> list[list[Word]]:
    """Every distinct occurrence of the value (word runs), compared by kind."""
    target = _canon(kind, value)
    if target is None:
        return []
    canon = _canon_fn(kind)

    def match(ws: list[Word]) -> bool:
        text = " ".join(w.text for w in ws)
        try:
            return canon(text) == target
        except (ValueError, ArithmeticError):
            return False

    limit = None if kind in ("money", "date", "tax_id", "iban") else len(str(target)) + 12
    found: list[list[Word]] = []
    lines = _lines(layer)
    for line in lines:
        for i, j in _windows(line, match, kind=kind, max_chars=limit):
            found.append(line[i:j])
    if not found and kind in cfg.load("grounding")["multi_line_kinds"]:
        # a name or address wrapped onto two lines: in the same column of lines one below the other (in a two-column
        # header the supplier's and the customer's names stand side by side, so whole lines must not be joined)
        for a, b in zip(lines, lines[1:]):
            if a[0].page != b[0].page:
                continue
            height = max(w.y1 - w.y0 for w in a)
            if min(w.y0 for w in b) - max(w.y1 for w in a) > 1.5 * height:
                continue
            for sa in _segments(a):
                for sb in _segments(b):
                    if min(sa[-1].x1, sb[-1].x1) - max(sa[0].x0, sb[0].x0) <= 0:
                        continue  # not one below the other
                    pair = sa + sb
                    for i, j in _windows(pair, match, kind=kind, max_chars=limit):
                        if i < len(sa) < j:
                            found.append(pair[i:j])
    return found


COLUMN_GAP = 0.03  # a horizontal gap wider than this fraction of the page width is a column boundary


def _segments(line: list[Word]) -> list[list[Word]]:
    """One line split into columns at the wide horizontal gaps."""
    out: list[list[Word]] = [[line[0]]]
    for prev, w in zip(line, line[1:]):
        if w.x0 - prev.x1 > COLUMN_GAP:
            out.append([w])
        else:
            out[-1].append(w)
    return out


def _entry(status: str, method: str | None, words: list[Word] | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"status": status, "method": method}
    if words:
        out.update(region(words))
    out.update(extra)
    return out


# --- label context (a simplified port of the V4 context.py; vocabulary: configs/grounding.json) ---------------------


@lru_cache(maxsize=65536)  # 061: words repeat often across layers
def _fold(text: str) -> str:
    """An unaccented, lower-case form without punctuation (for comparing labels)."""
    t = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w%]+", " ", t).split())


class Labels:
    """The field labels found in the layer (e.g. "Bruttó összeg:", gross amount) and the nearest label to a word run."""

    def __init__(self, layer: SourceLayer, conf: dict[str, Any] | None = None) -> None:
        conf = conf or cfg.load("grounding")
        self.groups: dict[str, list[str]] = dict(conf.get("label_groups", {}))
        self.same_gap = float(conf["label_same_line_max_gap"])
        self.above_gap = float(conf["label_above_max_gap"])
        phrases = sorted(((role, p.split()) for role, ps in conf["labels"].items() for p in ps), key=lambda rp: -len(rp[1]))
        # 061: labels are indexed by their first word, and in a line only those are tried whose first word occurs in
        # the line, at the places where it occurs. The order (longer label first), hence the result, is the same as with
        # the full location × label traversal; the result of a 49-document run takes a fraction of a second, not 34 s.
        by_first: dict[str, list[int]] = {}
        for n, (_role, toks) in enumerate(phrases):
            if toks:
                by_first.setdefault(toks[0], []).append(n)
        self.found: list[tuple[str, list[Word]]] = []
        for line in _lines(layer):
            folded = [_fold(w.text) for w in line]
            starts: dict[str, list[int]] = {}
            for i, tok in enumerate(folded):
                starts.setdefault(tok, []).append(i)
            candidates = sorted(n for tok in starts for n in by_first.get(tok, ()))
            used: set[int] = set()
            for n in candidates:
                role, toks = phrases[n]
                for i in starts[toks[0]]:
                    if i + len(toks) > len(line) or any(k in used for k in range(i, i + len(toks))):
                        continue
                    if all(folded[i + k] == toks[k] for k in range(len(toks))):
                        self.found.append((role, line[i:i + len(toks)]))
                        used.update(range(i, i + len(toks)))

    def nearest(self, hit: list[Word]) -> str | None:
        """The role of the label for a word run: to the left on the same line, or directly above; None on a tie."""
        first, last = hit[0], hit[-1]
        hit_ids = {w.id for w in hit}
        options: list[tuple[int, float, str]] = []
        for role, words in self.found:
            if words[0].page != first.page or hit_ids & {w.id for w in words}:
                continue
            lab_last = words[-1]
            if lab_last.line_no is not None and lab_last.line_no == first.line_no and lab_last.x1 <= first.x0 + 1e-6:
                gap = first.x0 - lab_last.x1
                if gap <= self.same_gap:
                    options.append((0, gap, role))
            else:
                bottom = max(w.y1 for w in words)
                centre = (first.x0 + last.x1) / 2
                if 0 <= first.y0 - bottom <= self.above_gap and words[0].x0 - 0.02 <= centre <= lab_last.x1 + 0.035:
                    options.append((1, first.y0 - bottom, role))
        if not options:
            return None
        options.sort()
        best = options[0]
        if any(o[0] == best[0] and abs(o[1] - best[1]) < 0.005 and o[2] != best[2] for o in options[1:]):
            return None
        return best[2]

    def supports(self, role: str | None, field: str) -> bool:
        """The label belongs to the field: its own role, or a general group the field belongs to."""
        return role is not None and (role == field or field in self.groups.get(role, []))


def locate_value(layer: SourceLayer | None, kind: str, value: Any, *, method: str = "search", field: str | None = None,
                 labels: Labels | None = None) -> dict[str, Any]:
    """The source location of a value by search (G path, corrected value). With several hits the field's label decides
    (it needs `field`): a location next to another field's label drops out; one location with its own label → a box;
    otherwise `ambiguous`."""
    if layer is None:
        return _entry("no_layer", None)
    if value is None or str(value).strip() == "":
        return _entry("no_value", None)
    hits = search(layer, kind, value)
    if not hits:
        return _entry("not_found", method)
    alts = lambda hs: [{"value": str(value), "p": None, **region(h)} for h in hs[:8]]  # noqa: E731
    order = lambda hs: sorted(hs, key=lambda h: (h[0].page, h[0].y0, h[0].x0))  # noqa: E731 - reading order
    if field is None or kind == "currency":  # the currency sign sits by the amount; no other field's label excludes it
        hits = order(hits)
        return _entry("located", method, hits[0], alternatives=alts(hits[1:]), multiple=len(hits))
    labels = labels or Labels(layer)
    roles = [labels.nearest(h) for h in hits]
    own = order([h for h, r in zip(hits, roles) if labels.supports(r, field)])
    free = order([h for h, r in zip(hits, roles) if r is None])
    if not own and not free:  # every hit stands next to another field's label
        return _entry("context_rejected", method, alternatives=alts(hits))
    # 053 (decision of 2026-09-28): with several locations, the box goes on the most likely one (next to its own label,
    # otherwise the first occurrence without a label); the other locations are clickable alternatives, `multiple` is the
    # number of locations
    best, rest = (own[0], own[1:] + free) if own else (free[0], free[1:])
    return _entry("located", method, best, label=bool(own), alternatives=alts(rest), multiple=len(own) + len(free))


# --- rows of itemised lists (053, T1-lista-keret) ---------------------------------------------------------------

ROW_ANCHOR_KINDS = ("money", "date")


def locate_rows(layer: SourceLayer | None, rows: list[Any], kinds: dict[str, str]) -> list[dict[str, Any]]:
    """The location of an itemised list's rows: the row's amounts and dates (anchors) on the same word-layer line. The
    line with the most anchors wins; on a tie, the first one after the previous row's line (the list is in document
    order, so items with repeated amounts land on consecutive lines). Without anchors, the description text is searched.
    Box: every word of the word-layer line; `approximate` when a row with several anchors matches only one of them on
    the line."""
    if layer is None:
        return [_entry("no_layer", None) for _ in rows]
    cache: dict[tuple[str, str], list[list[Word]]] = {}

    def hits_of(kind: str, value: Any) -> list[list[Word]]:
        key = (kind, str(value))
        if key not in cache:
            cache[key] = search(layer, kind, value)
        return cache[key]

    out: list[dict[str, Any]] = []
    last: tuple[int, float] | None = None
    for row in rows:
        row = row if isinstance(row, dict) else {"*": row}
        anchors = [(k, v) for c, v in row.items() if (k := kinds.get(c, "text")) in ROW_ANCHOR_KINDS and v not in (None, "")]
        if not any(v not in (None, "") for v in row.values()):
            out.append(_entry("no_value", None))
            continue
        per_line: dict[int, set[int]] = {}
        first_word: dict[int, Word] = {}
        for i, (kind, value) in enumerate(anchors):
            for h in hits_of(kind, value):
                if h[0].line_no is None:
                    continue
                per_line.setdefault(h[0].line_no, set()).add(i)
                first_word.setdefault(h[0].line_no, h[0])
        if not per_line:
            text = next((v for c, v in row.items() if kinds.get(c, "text") == "text" and v), None)
            for h in hits_of("text", text) if text else []:
                if h[0].line_no is not None:
                    per_line.setdefault(h[0].line_no, {0})
                    first_word.setdefault(h[0].line_no, h[0])
        if not per_line:
            out.append(_entry("not_found", "rows"))
            continue
        best = max(len(v) for v in per_line.values())
        cands = sorted((ln for ln, v in per_line.items() if len(v) == best), key=lambda ln: (first_word[ln].page, first_word[ln].y0))
        after = [ln for ln in cands if last is None or (first_word[ln].page, first_word[ln].y0) > last]
        line_no = (after or cands)[0]
        w = first_word[line_no]
        last = (w.page, w.y0)
        words = [x for x in layer.words_on_line(line_no) if x.page == w.page]
        status = "located" if best >= min(2, max(1, len(anchors))) else "approximate"
        out.append(_entry(status, "rows", words, multiple=len(cands) if len(cands) > 1 else None))
    return out


def ground_lists(layer: SourceLayer | None, *, lists: dict[str, list[Any]], kinds: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    """The per-row source location of the pack's itemised lists (`status: list`, `rows`: one entry per row)."""
    return {f: {"status": "list", "method": "rows", "alternatives": [], "rows": locate_rows(layer, rows or [], kinds.get(f, {}))}
            for f, rows in lists.items()}


def ground_picks(layer: SourceLayer | None, *, fields: dict[str, str], values: dict[str, Any], picks: dict[str, Any],
                 candidates: dict[str, Iterable[Any]], confidence: dict[str, float | None]) -> dict[str, dict[str, Any]]:
    """S path: the location of the selected candidate in its own line (fallback: search), and the other candidates with
    their probabilities."""
    out: dict[str, dict[str, Any]] = {}
    labels = Labels(layer) if layer is not None else None
    for field, kind in fields.items():
        pick = picks.get(field)
        # the candidates grouped by kind (jav/jev_select.py `field_kind`); field kind → candidate kind
        cands = {c.label: c for c in candidates.get(CANDIDATE_KIND_OF.get(kind, kind), [])}
        conf = confidence.get(field)
        if layer is None:
            out[field] = _entry("no_layer", None, confidence=conf)
            continue
        # the printed text span and line recorded at selection time (FieldPick.raw, .line_no)
        line_no = getattr(pick, "line_no", None) if pick is not None and pick.label is not None else None
        raw = getattr(pick, "raw", None) if line_no is not None else None
        words = locate_raw(layer, line_no, raw) if line_no is not None and raw else None
        if words:
            entry = _entry("located", "pick", words)
        elif values.get(field) is not None:
            entry = locate_value(layer, kind, values.get(field), field=field, labels=labels)
            line_words = layer.words_on_line(line_no) if line_no is not None else []
            if entry["status"] == "not_found" and line_words:
                # the model chose from this line: an approximate (line-level) box, so the field has a location
                entry = _entry("approximate", "pick_line", line_words)
        else:
            entry = _entry("no_value", None, present_p=getattr(pick, "present_p", None))
        alts = []
        probs = dict(getattr(pick, "probabilities", {}) or {})
        for label, p in sorted(probs.items(), key=lambda kv: -kv[1]):
            if len(alts) >= MAX_ALTERNATIVES or p < MIN_ALTERNATIVE_P:
                break
            if pick is not None and label == pick.label or label not in cands:
                continue
            c = cands[label]
            w = locate_raw(layer, c.line_no, c.raw)
            if w:
                alts.append({"value": c.label, "raw": c.raw, "p": round(float(p), 4), **region(w)})
        entry["alternatives"] = entry.get("alternatives", []) if entry["status"] in ("ambiguous", "context_rejected") else alts
        entry["confidence"] = conf
        out[field] = entry
    return out


def ground_values(layer: SourceLayer | None, *, fields: dict[str, str], values: dict[str, Any],
                  confidence: dict[str, float | None]) -> dict[str, dict[str, Any]]:
    """G path (or a field without candidates): searches for every value."""
    labels = Labels(layer) if layer is not None else None
    out = {}
    for f, kind in fields.items():
        entry = locate_value(layer, kind, values.get(f), field=f, labels=labels)
        out[f] = {"alternatives": [], **entry, "confidence": confidence.get(f)}
    return out


def manual(layer: SourceLayer | None, word_ids: list[int]) -> dict[str, Any]:
    """The box of the words a person selected. Unknown id → ValueError (the correction is rejected)."""
    if layer is None:
        raise ValueError("no source layer for this item; selection on the image is not possible")
    by_id = layer.by_id()
    missing = [i for i in word_ids if i not in by_id]
    if not word_ids or missing:
        raise ValueError(f"unknown word ids: {missing[:5]}")
    words = [by_id[i] for i in sorted(set(word_ids))]
    return _entry("located", "manual", words, alternatives=[])
