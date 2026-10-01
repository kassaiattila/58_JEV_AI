"""One date reader for every path (084, date reading: the owner's report of 2026-10-01, "04-DEC-22" unreadable).

A hotel invoice printed its issue date as "Issued : 04-DEC-22 21:52". Neither the S path nor a selection on the page
image could read it: the shared reader knew only four-digit years and a few forms, and manual input took only
YYYY-MM-DD. Every path now reads a date through this module: the candidates of the S path, the value JEV chooses,
GPT's values, the JEV check's value search, a selection on the page image and a manual correction.

A printed date is read whole (never cut out of a longer number) and resolved by these rules:

- year first (2022.12.04, 2022-12-04, "2022. december 4."): unambiguous;
- with a month name or abbreviation (Hungarian, English, German, French, Spanish, Italian; any letter case, with or
  without accents, ordinal endings, "4 de diciembre de 2022", "04-DEC-22"): unambiguous;
- all numbers with a four-digit year, day or month first: a number above 12 decides; otherwise a dot means day first
  (no country writes month.day.year); a hyphen or a slash follows the document's own order (`document_date_order`);
  without one a hyphen stays day first, as before, and a slash is flagged (`ambiguous`; its value is the month-first
  reading used before, `alt` the other one);
- all numbers with a two-digit year ("04.12.22", "1/15/23") can also be the Hungarian short form with the year first
  (22.12.04), so only the document's own order resolves them; without one they are flagged;
- a four-digit year is 1900-2099 ("1500 Dec 4" is an amount, not a date); a two-digit year belongs to this century
  unless that would be later than next year (then to the previous one);
- a time, a weekday or a label next to the date does not disturb it.

Survey of the local documents (2026-10-01): month-first slash dates that nothing on the date itself decides occur on
97 foreign documents, and 129 foreign documents decide the order by their own dates; "04-DEC-22"-like dates occur on
10, all-number two-digit-year dates on 14. "MAG/12/2022" is a document number, so a month name does not take a slash
and the Italian "mag" is left out (the full "maggio" stays).

A flagged reading becomes a to-do where it is used; it is never resolved silently. Manual input (`read_date_input`)
takes every unambiguous form and refuses an ambiguous one.

The two old Hungarian patterns in `jav/models.py` (`DATE_NUMERIC_RE`, `DATE_TEXT_RE`) stay unchanged: the type
recognition request counts their matches, and changing them would make every recognition a new, paid call.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel

DateOrder = Literal["dmy", "mdy"]  # dmy: 04/12/2022 = 4 December (continental, British); mdy: 12/04/2022 (US)
Kind = Literal["ymd", "name", "dot", "dash", "slash"]


class DateRead(BaseModel):
    """A date read from text. `ambiguous`: the day and the month may be the other way round, so a person has to check."""

    value: date | None
    ambiguous: bool = False


class AmbiguousDate(ValueError):
    """A typed date whose day and month can be read two ways ("04/12/2022": 4 December or 12 April)."""


@dataclass(frozen=True)
class DateHit:
    """One date found in a text: its span, the printed form and the reading (`alt`: the other reading of a flagged
    date, so that a value search can accept either)."""

    start: int
    end: int
    raw: str
    value: date
    ambiguous: bool = False
    alt: date | None = None
    kind: Kind = "ymd"
    decisive: DateOrder | None = None  # an all-number date whose day or month is above 12: evidence of the order
    short: bool = False  # an all-number date with a two-digit year


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(ch) != "Mn")


_MONTH_NAMES: dict[int, tuple[str, ...]] = {
    1: ("január", "jan", "january", "januar", "jänner", "janvier", "janv", "enero", "ene", "gennaio", "gen"),
    2: ("február", "febr", "feb", "february", "februar", "février", "févr", "febrero", "febbraio"),
    3: ("március", "márc", "march", "mar", "märz", "maerz", "mrz", "mär", "mars", "marzo"),
    4: ("április", "ápr", "apr", "april", "avril", "avr", "abril", "abr", "aprile"),
    5: ("május", "máj", "may", "mai", "mayo", "maggio"),
    6: ("június", "jún", "jun", "june", "juni", "juin", "junio", "giugno", "giu"),
    7: ("július", "júl", "jul", "july", "juli", "juillet", "juil", "julio", "luglio", "lug"),
    8: ("augusztus", "aug", "august", "août", "agosto", "ago"),
    9: ("szeptember", "szept", "szep", "september", "sept", "sep", "septembre", "septiembre", "setiembre", "settembre",
        "set"),
    10: ("október", "okt", "october", "oct", "oktober", "octobre", "octubre", "ottobre", "ott"),
    11: ("november", "nov", "novembre", "noviembre"),
    12: ("december", "dec", "dezember", "dez", "décembre", "déc", "diciembre", "dic", "dicembre"),
}  # fmt: skip
_MONTHS: dict[str, int] = {_fold(name): month for month, names in _MONTH_NAMES.items() for name in names}
_MONTH_FORMS = {form for month, names in _MONTH_NAMES.items() for name in names for form in (name, _fold(name))}
_MONTH = "(?:" + "|".join(re.escape(f) for f in sorted(_MONTH_FORMS, key=len, reverse=True)) + r")(?![^\W\d_])"

_SEP = r"[\s.\-/]*"
_DAY_END = r"(?:st|nd|rd|th|er)?\.?"
Tag = Literal["dmy", "mdy", "short"] | None  # a name form's order (evidence of the document's order); a short date
_PATTERNS: tuple[tuple[Kind, Tag, re.Pattern[str]], ...] = (
    # 2022.12.04 / 2022-12-04 / 2022. 12. 04. / 2022/12/04 (as the old Hungarian pattern; a time may follow)
    ("ymd", None, re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})\s*[.\-/]\s*(?P<m>\d{1,2})\s*[.\-/]\s*(?P<d>\d{1,2})\.?(?!\d)")),
    # 2022. december 4. / 2022-Dec-04
    ("name", None, re.compile(rf"(?<!\d)(?P<y>(?:19|20)\d{{2}})\.?,?{_SEP}(?P<mn>{_MONTH})\.?{_SEP}(?P<d>\d{{1,2}})\.?(?!\d)",
                              re.I)),
    # 4 December 2022 / 4. Dezember 2022 / 4 de diciembre de 2022 / 4th of December, 2022
    ("name", "dmy", re.compile(rf"(?<!\d)(?P<d>\d{{1,2}}){_DAY_END}(?:\s*(?:de|of)\b)?{_SEP}(?P<mn>{_MONTH})\.?"
                               rf"(?:\s*de\b)?[\s.\-/,]*(?P<y>(?:19|20)\d{{2}})(?!\d)", re.I)),
    # 04-DEC-22 / 04 Dec 22 / 04DEC22: a two-digit year only with the same separator twice and no four-digit year after
    # it ("Mar 28-Mar 31, 2026" is a US range, not 28 March 1931)
    ("name", "dmy", re.compile(rf"(?<!\d)(?P<d>\d{{1,2}})(?P<s>[\s.\-/]?)(?P<mn>{_MONTH})\.?(?P=s)(?P<y>\d{{2}})(?!\d)"
                               rf"(?![.,]\d)(?!,?\s*(?:19|20)\d{{2}}(?!\d))", re.I)),
    # December 4, 2022 / Dec. 4th, 2022 / DEC 04 2022 (a four-digit year only: "Dec 4, 22 items" is no date; no slash:
    # "MAG/12/2022" is a document number)
    ("name", "mdy", re.compile(rf"(?<![^\W\d_])(?P<mn>{_MONTH})\.?[\s\-]*(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?[\s\-]*"
                               rf"(?P<y>(?:19|20)\d{{2}})(?!\d)", re.I)),
    # 04.12.2022 / 04-12-2022 (as the old day-first pattern) / 04/12/2022 (as the old US pattern)
    ("dot", None, re.compile(r"(?<!\d)(?P<a>\d{1,2})\s*(?P<s>[.\-])\s*(?P<b>\d{1,2})\s*[.\-]\s*(?P<y>(?:19|20)\d{2})(?!\d)")),
    ("slash", None, re.compile(r"(?<!\d)(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>(?:19|20)\d{2})(?!\d)")),
    # 04.12.22 / 04-12-22 / 04/12/22: a two-digit year only with the same separator twice and nothing number-like around
    ("dot", "short", re.compile(r"(?<![\d.\-/])(?P<a>\d{1,2})(?P<s>[./-])(?P<b>\d{1,2})(?P=s)(?P<y>\d{2})(?!\d)(?![./-]\d)")),
)
_OCR_YMD = re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})\s*[.\-/,]\s*(?P<m>\d{1,2})\s*[.\-/,]\s*(?P<d>\d{1,2})\.?(?!\d)")
_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")


def _year(text: str, today: date) -> int:
    y = int(text)
    if len(text) > 2:
        return y
    return 2000 + y if 2000 + y <= today.year + 1 else 1900 + y


def _valid(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _numeric(m: re.Match[str], kind: Kind, order: DateOrder | None, today: date) -> DateHit | None:
    a, b, short = int(m.group("a")), int(m.group("b")), len(m.group("y")) == 2
    y = _year(m.group("y"), today)
    sep = "/" if kind == "slash" else m.group("s")
    kind = {"/": "slash", "-": "dash", ".": "dot"}[sep]  # type: ignore[assignment]
    raw, start, end = m.group(0), m.start(), m.end()
    dmy, mdy = _valid(y, b, a), _valid(y, a, b)
    if dmy is None and mdy is None:
        return None
    if short:  # the year may also be the first number (Hungarian short form): only the document's order decides
        if order is not None:
            value = dmy if order == "dmy" else mdy
            return DateHit(start, end, raw, value, kind=kind, short=True) if value else None
        value, alt = (mdy, dmy) if kind == "slash" else (dmy, mdy)
        value, alt = (value, alt) if value is not None else (alt, None)
        return DateHit(start, end, raw, value, ambiguous=True, alt=alt if alt != value else None, kind=kind, short=True)
    if dmy is None or mdy is None:  # a number above 12 decides
        return DateHit(start, end, raw, dmy or mdy, kind=kind, decisive="dmy" if dmy else "mdy")  # type: ignore[arg-type]
    if a == b or kind == "dot":
        return DateHit(start, end, raw, dmy, kind=kind)
    if order is not None:
        return DateHit(start, end, raw, dmy if order == "dmy" else mdy, kind=kind)
    if kind == "dash":
        return DateHit(start, end, raw, dmy, kind=kind)
    return DateHit(start, end, raw, mdy, ambiguous=True, alt=dmy, kind=kind)


def _hit(m: re.Match[str], kind: Kind, tag: Tag, order: DateOrder | None, today: date) -> DateHit | None:
    if kind in ("dot", "slash"):
        return _numeric(m, kind, order, today)
    month = _MONTHS[_fold(m.group("mn"))] if kind == "name" else int(m.group("m"))
    value = _valid(_year(m.group("y"), today), month, int(m.group("d")))
    decisive = tag if tag in ("dmy", "mdy") else None  # a month name after or before the day shows the document's order
    return DateHit(m.start(), m.end(), m.group(0), value, kind=kind, decisive=decisive) if value else None


def find_dates_in(text: str | None, *, order: DateOrder | None = None, ocr: bool = False, short: bool = True,
                  today: date | None = None) -> list[DateHit]:
    """Every date of a text, left to right, without overlaps (at the same start the longer form wins). `order`: the
    document's own order (`document_date_order`); `ocr`: a comma read as a dot in a year-first date; `short=False`
    leaves out the all-number dates with a two-digit year (on Hungarian and utility documents such text is mostly a
    code, and it could only be a to-do anyway)."""
    if not text:
        return []
    today = today or date.today()
    s = str(text).replace(" ", " ")
    patterns = [(k, g, rx) for k, g, rx in _PATTERNS if short or g != "short"]
    if ocr:
        patterns.append(("ymd", None, _OCR_YMD))
    found = [h for kind, tag, rx in patterns for m in rx.finditer(s) if (h := _hit(m, kind, tag, order, today)) is not None]
    found.sort(key=lambda h: (h.start, -(h.end - h.start)))
    out: list[DateHit] = []
    for h in found:
        if not out or h.start >= out[-1].end:
            out.append(h)
    return out


def read_date(raw: object, *, order: DateOrder | None = None, ocr: bool = False, today: date | None = None) -> DateRead:
    """The first date of a text. Never raises: no date gives `value=None`."""
    if raw is None:
        return DateRead(value=None)
    hits = find_dates_in(str(raw), order=order, ocr=ocr, today=today)
    return DateRead(value=hits[0].value, ambiguous=hits[0].ambiguous) if hits else DateRead(value=None)


def document_date_order(texts: Iterable[str], *, today: date | None = None) -> DateOrder | None:
    """The document's own day/month order: from its hyphen and slash dates with a four-digit year whose day or month is
    above 12, and from its dates with a month name ("Dec 25, 2022": month first, "25 December 2022": day first). None
    when nothing decides or the evidence contradicts itself (a dot date is day first anyway and is no evidence; an
    all-number date with a two-digit year is none either, as its year may come first)."""
    seen = {h.decisive for t in texts for h in find_dates_in(t, today=today)
            if h.kind in ("dash", "slash", "name") and h.decisive and not h.short}
    return seen.pop() if len(seen) == 1 else None


def read_date_input(raw: object, *, today: date | None = None) -> str:
    """A typed date as ISO text ("2022-12-04"). Every unambiguous form is taken; an ambiguous one raises
    `AmbiguousDate`, and text that is not exactly one date (a time next to it is fine) raises `ValueError`."""
    text = str(raw or "").strip()
    hits = find_dates_in(text, today=today)
    if not hits:
        raise ValueError(f"not a date: {text!r}")
    hit = hits[0]
    rest = _TIME.sub("", text[: hit.start] + " " + text[hit.end:])
    if len(hits) > 1 or re.search(r"\d", rest):
        raise ValueError(f"not a single date: {text!r}")
    if hit.ambiguous:
        raise AmbiguousDate(f"the day and the month can be read two ways: {text!r}")
    return hit.value.isoformat()
