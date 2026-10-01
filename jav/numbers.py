"""One number reader for every path (081, number reading: the owner's report of 2026-10-01, "28.000" read as 28).

A Billzone invoice printed in English notation ("28,000.00") was read as net 28, VAT 7.56 and gross 35.56: the
Hungarian candidate pattern cut "28,000" to "28,00". The three wrong values still added up, so no to-do was raised.
Every path now reads a number through this module: the S path's candidates, GPT's values, the JEV check's value
search, a selection on the page image and a manual correction.

A printed number is read whole (it is never cut apart) and resolved by these rules:

- a dot and a comma together: the last one is the decimal separator ("12.345,67", "12,345.67");
- several of the same separator: thousands groups ("1.234.567", "1,234,567");
- one separator followed by exactly three digits after one to three digits ("28.000", "28,000"): a thousands group
  for money, because money never has three decimals; for a quantity the document's own notation decides
  (`document_convention`), and without one it is read the Hungarian way and flagged;
- one separator followed by one or two digits, or by four or more: a decimal separator; a dot with one or two digits
  keeps the earlier flag (an English decimal and a malformed group cannot be told apart in code);
- money with three or more decimals that is no thousands group ("1234.567", "0,500") is flagged.

A flagged reading (`ambiguous`) becomes a to-do where it is used; it is never resolved silently. Manual input follows
the Hungarian habit (`read_input`) and refuses an ambiguous form instead of guessing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel

Convention = Literal["comma", "dot"]  # comma: "1 234,56" (Hungarian, continental); dot: "1,234.56" (English)
Kind = Literal["money", "number"]


class NumberRead(BaseModel):
    """A number read from text. `ambiguous`: the separators allow another reading, so a person has to check it."""

    value: Decimal | None
    ambiguous: bool = False


class AmbiguousNumber(ValueError):
    """A typed number whose separators can be read two ways ("28.5" for money: 28.5 or a mistyped 28 500)."""


_CURRENCY_TOKENS = re.compile(r"(?i)\b(?:ft|huf|eur|usd|forint)\b\.?|[€$]")
_TRAILING_DASH = re.compile(r"[,.]\s*-\s*$")  # "12 000,-"
_NON_NUMERIC = re.compile(r"[^\d.,\-]")
# "$42.50" / "42.50 USD": the dot is a decimal point (international profile)
_DECIMAL_DOT_HINT = re.compile(r"[$€£]\s*-?\d|\d\s*(?:USD|EUR|GBP|AUD|CAD|CHF)\b", re.IGNORECASE)
_GROUPED = {sep: re.compile(rf"^-?[1-9]\d{{0,2}}(?:{re.escape(sep)}\d{{3}})+$") for sep in ".,"}


def _label(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


def has_decimal_dot_hint(text: str) -> bool:
    """A currency sign or code next to the number ("$42.50", "42.50 USD"): a two-decimal dot is a decimal point."""
    return bool(_DECIMAL_DOT_HINT.search(text))


def read_number(raw: object, *, kind: Kind = "money", convention: Convention | None = None, intl: bool = False,
                dot_hint: bool | None = None) -> NumberRead:
    """Reads a printed number whole. `kind`: money or a quantity (`number`); `convention`: the document's notation
    (`document_convention`); `intl`: the international candidate profile (a currency sign makes a two-decimal dot a
    decimal point); `dot_hint`: that sign found around the number by the caller (only the number itself is read, never
    its neighbours). Never raises: unreadable text gives `value=None`."""
    if raw is None:
        return NumberRead(value=None)
    s = str(raw).replace(" ", " ").strip()
    dot_is_decimal = intl and (has_decimal_dot_hint(s) if dot_hint is None else dot_hint)
    s = _CURRENCY_TOKENS.sub("", s)
    s = _TRAILING_DASH.sub("", s).strip()
    s = _NON_NUMERIC.sub("", s.replace(" ", ""))
    if not s or s in {"-", ".", ","} or s.count("-") > 1 or "-" in s[1:]:
        return NumberRead(value=None)

    ambiguous = False
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        decimal_sep = "," if s.rfind(",") > s.rfind(".") else "."
        group_sep = "." if decimal_sep == "," else ","
        if s.count(decimal_sep) > 1:
            return NumberRead(value=None)
        s = s.replace(group_sep, "").replace(decimal_sep, ".")
    elif has_dot or has_comma:
        sep = "," if has_comma else "."
        grouped = bool(_GROUPED[sep].match(s))
        frac = s.rsplit(sep, 1)[1]
        if s.count(sep) > 1:
            if not grouped:
                return NumberRead(value=None)
            s = s.replace(sep, "")
        elif len(frac) == 3 and grouped:
            if kind == "money":
                s = s.replace(sep, "")  # money never has three decimals: "28.000" / "28,000" = 28 000
            else:
                group_sep = {"comma": ".", "dot": ","}.get(convention or "", ".")  # unknown: the Hungarian reading
                s = s.replace(sep, "") if sep == group_sep else s.replace(sep, ".")
                ambiguous = convention is None
        else:
            s = s.replace(sep, ".")
            if kind == "money" and len(frac) >= 3:
                ambiguous = True  # "1234.567" / "0,500": three or more decimals and no thousands group
            elif sep == "." and len(frac) <= 2:
                ambiguous = not dot_is_decimal and not (kind == "number" and convention == "dot")
    try:
        return NumberRead(value=Decimal(s), ambiguous=ambiguous)
    except InvalidOperation:
        return NumberRead(value=None)


# --- the document's notation -------------------------------------------------------------------------------------------

_MASK = re.compile(
    r"\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}\.?"  # 2024.01.09. / 2024-01-09
    r"|\d{1,2}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{4}"  # 09.01.2024
    r"|\d{1,2}:\d{2}(?::\d{2})?"  # 12:30
)
_COMMA_VOTES = (
    re.compile(r"\d[.  ]\d{3},\d{1,2}(?!\d)"),  # 1.234,56 / 1 234,56
    re.compile(r"(?<![\d.,])\d+,\d{2}(?![\d.,]?\d)"),  # 143,00 / 34,92
    re.compile(r"(?<![\d.,])\d+,\d{4,}(?!\d)"),  # 3,3900: four decimals cannot be a thousands group
)
_DOT_VOTES = (
    re.compile(r"\d,\d{3}\.\d{1,2}(?!\d)"),  # 28,000.00
    re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3}){2,}(?![\d.,]?\d)"),  # 1,234,567
    re.compile(r"(?<![\d.,])\d+\.\d{2}(?![\d.,]?\d)"),  # 12.50
    re.compile(r"(?<![\d.,])\d+\.\d{4,}(?!\d)"),  # 1.0000
)


def document_convention(texts: Iterable[str]) -> Convention | None:
    """The document's decimal notation from its decisive numbers: "comma" (1 234,56) or "dot" (1,234.56); None when
    there is no decisive number or the two are equally frequent. Dates and times are left out; a lone thousands group
    ("12.345", "28,000") decides nothing."""
    comma = dot = 0
    for text in texts:
        t = _MASK.sub(" ", text)
        comma += sum(len(rx.findall(t)) for rx in _COMMA_VOTES)
        dot += sum(len(rx.findall(t)) for rx in _DOT_VOTES)
    if comma == dot:
        return None
    return "comma" if comma > dot else "dot"


# --- manual input --------------------------------------------------------------------------------------------------------

_INPUT = re.compile(r"-?[\d.,]+")


def read_input(raw: object, *, kind: Kind = "money") -> str:
    """A typed number by the Hungarian habit, as the stored canonical text ("28000", "28000.5"): a space or a dot groups
    thousands ("28 000", "28.000"), a comma is the decimal separator ("28,5"); "28 000,50" and "28,000.00" are read by
    their last separator. Raises `AmbiguousNumber` for a form that can be read two ways ("28.5" or "28,000" for money,
    "1.5" for a quantity) and `ValueError` for text that is not a number."""
    s = str(raw).replace(" ", "").replace(" ", "").strip()
    if not _INPUT.fullmatch(s) or not any(ch.isdigit() for ch in s):
        raise ValueError(f"not a number: {raw!r}")
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        got = read_number(s, kind=kind)
    elif has_comma:
        frac = s.rsplit(",", 1)[1]
        if s.count(",") > 1 or (kind == "money" and len(frac) == 3):
            raise AmbiguousNumber(f"ambiguous separators: {raw!r}")
        got = NumberRead(value=_decimal(s.replace(",", ".")))
    elif has_dot:
        frac = s.rsplit(".", 1)[1]
        if s.count(".") > 1 or (len(frac) == 3 and _GROUPED["."].match(s)):
            if not _GROUPED["."].match(s):
                raise ValueError(f"not a number: {raw!r}")
            got = NumberRead(value=_decimal(s.replace(".", "")))
        elif len(frac) >= 4 and kind == "number":
            got = NumberRead(value=_decimal(s))
        else:
            raise AmbiguousNumber(f"ambiguous separators: {raw!r}")
    else:
        got = NumberRead(value=_decimal(s))
    if got.value is None:
        raise ValueError(f"not a number: {raw!r}")
    if got.ambiguous:
        raise AmbiguousNumber(f"ambiguous separators: {raw!r}")
    return _label(got.value)


def _decimal(s: str) -> Decimal | None:
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


# --- whole tokens --------------------------------------------------------------------------------------------------------

_SPACE = (" ", " ")


def _continues_right(line: str, j: int) -> bool:
    if j >= len(line):
        return False
    ch = line[j]
    if ch.isdigit():
        return True
    if ch in ".," and j + 1 < len(line) and line[j + 1].isdigit():
        return True
    # a space-grouped number goes on: "1 234" + " 567"
    return ch in _SPACE and line[j + 1:j + 4].isdigit() and len(line[j + 1:j + 4]) == 3 and not line[j + 4:j + 5].isdigit()


def _continues_left(line: str, i: int) -> bool:
    if i <= 0:
        return False
    ch = line[i - 1]
    if ch.isdigit():
        return True
    return ch in ".," and i >= 2 and line[i - 2].isdigit()


def is_whole_token(raw: str, line: str) -> bool:
    """Whether `raw` stands in `line` as a whole number at least once, not as a piece of a longer one ("28,00" in
    "28,000.00" is a piece). A value not found in the line cannot be judged here and counts as whole."""
    if not raw or raw not in line:
        return True
    start = line.find(raw)
    while start >= 0:
        end = start + len(raw)
        if not _continues_left(line, start) and not _continues_right(line, end):
            return True
        start = line.find(raw, start + 1)
    return False


__all__ = ["AmbiguousNumber", "Convention", "Kind", "NumberRead", "document_convention", "has_decimal_dot_hint",
           "is_whole_token", "read_input", "read_number"]
