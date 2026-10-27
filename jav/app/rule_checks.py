"""The code's checks of a proposed rule, before any model judges it (231, stage D, D-c7b).

Plain-language summary: a model will propose rules from a condition document, each with the page, clause and words it
was read from. Before any model judges a proposal, code checks what code can check. The rule fits its fact catalogue
(`product_rules.rule_problems`). It cites the document it was read from, a page that document has and that was read
(not one its marking left out), and, for a document already in the registry, a clause that document has on that page.
Its quoted words are on the page it cites. Each number of its decision table is found where the document says it: in
the quote, elsewhere on the cited page, on another page, written as a word (four as a word), derived from a stated number
(a 10 % discount as a factor of 0.9, a boundary one away from a stated count, a factor of 1), read by text recognition,
or not found. A number not found or read by recognition is never accepted silently: a person confirms it. Every
finding is a sentence in the interface's language; a blocking one keeps the proposal from being accepted as it is.

- `check(rule, pages, document_ref=, document=None)`: the `RuleCheck` (its findings, and where each number stands).

Layer: application, code only (`configs/rule_proposals.json`); it names no process and no business.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from jav.app import facts, product_rules
from jav.app.product_rules import ConditionDocument, Rule
from jav.core import cfg, numbers
from jav.core.measures import Money, PerMille, Percentage, Quantity
from jav.core.user_messages import Said, said
from jav.documents.page_text import DocumentPages

__all__ = ["Finding", "NumberSeen", "RuleCheck", "check"]

Severity = Literal["blocking", "attention"]
Where = Literal["quote", "page", "elsewhere", "word", "derived", "neutral", "ocr", "not_found"]
_COMPARED = ("gt", "gte", "lt", "lte", "between")


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    text: Said


@dataclass(frozen=True)
class NumberSeen:
    value: str  # as a person reads it: "10000000 HUF", "30 %", "1610"
    where: Where
    page: int | None = None
    kind: str = "decimal"  # D-c7g: amount, percent, permille, count, decimal or code (a code is shown as written)


@dataclass(frozen=True)
class RuleCheck:
    findings: tuple[Finding, ...]
    numbers: tuple[NumberSeen, ...]

    @property
    def blocking(self) -> bool:
        return any(f.severity == "blocking" for f in self.findings)


@dataclass(frozen=True)
class _Number:
    value: Decimal
    shown: str
    kind: Literal["amount", "percent", "permille", "count", "decimal", "code"]
    compared: bool = False  # at the edge of a comparison (a count one away from a stated one may stand)
    outcome: bool = False


def _plain(text: str) -> str:
    """Words as a reader joins them: one space between them, a word broken at its hyphen joined again."""
    return re.sub(r"-\s+", "-", re.sub(r"\s+", " ", text)).strip()


_TOKEN = re.compile(r"(?<![\d.,])(\d{1,3}(?:[ \u00a0.]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?![\d])(\s?%)?")
_FOOTER = re.compile(r"^\s*[–-]\s*\d+\s*[–-]\s*$")  # "– 2 –"
_BROKEN_GROUP = re.compile(r"(?<!\d)(\d{1,3})[ \t]*\n[ \t]*(\d{3})(?!\d)")  # "100" at a line's end, "000 Ft" on the next


def _tokens(text: str, convention: numbers.Convention | None) -> list[tuple[Decimal, bool]]:
    """The numbers a text prints, each with whether a percent sign follows it; not a clause's own number at the start
    of its heading ("4. Valuation"), a page's number at its foot ("– 2 –"), or either side of a slash ("3/19",
    "AHE-11936/6"), which state no rule's value. A thousands group the line broke is joined first."""
    out = []
    for line in _BROKEN_GROUP.sub(r"\1 \2", text).splitlines():
        if _FOOTER.match(line):
            continue
        for m in _TOKEN.finditer(line):
            start, end = m.span(1)
            if not line[:start].strip() and line[end:end + 1] == ".":
                continue  # a heading's number
            if line[start - 1:start] == "/" or line[end:end + 1] == "/":
                continue
            read = numbers.read_number(m.group(1), kind="number", convention=convention)
            if read.value is not None:
                out.append((read.value, bool(m.group(2))))
    return out


def _numbers_of(typed: Any, *, compared: bool = False, outcome: bool = False) -> list[_Number]:
    if isinstance(typed, Money):
        return [_Number(typed.amount, f"{typed.amount} {typed.currency}", "amount", compared, outcome)]
    if isinstance(typed, Quantity):
        return [_Number(typed.value, f"{typed.value} {typed.unit}", "amount", compared, outcome)]
    if isinstance(typed, Percentage):
        return [_Number(typed.value, f"{typed.value} %", "percent", compared, outcome)]
    if isinstance(typed, PerMille):
        return [_Number(typed.value, f"{typed.value} ‰", "permille", compared, outcome)]
    if isinstance(typed, bool):
        return []
    if isinstance(typed, int):
        return [_Number(Decimal(typed), str(typed), "count", compared, outcome)]
    if isinstance(typed, Decimal):
        return [_Number(typed, str(typed), "decimal", compared, outcome)]
    if isinstance(typed, str):
        return [_Number(Decimal(typed), typed, "code", compared, outcome)] if typed.isdigit() else []
    if isinstance(typed, tuple):
        return [n for item in typed for n in _numbers_of(item, compared=compared, outcome=outcome)]
    return []


def _rule_numbers(rule: Rule, cat: facts.Catalogue) -> list[_Number]:
    found: list[_Number] = []
    for row in rule.table.rows:
        for name, condition in row.when.items():
            d = cat.facts.get(name)
            for op, value in condition.items():
                if d is None or op in ("present", "absent"):
                    continue
                for v in value if op in ("in", "not_in", "between") and isinstance(value, list) else [value]:
                    try:
                        found += _numbers_of(facts.typed_value(name, d, v), compared=op in _COMPARED)
                    except facts.FactError:
                        continue  # the catalogue's check names it
        for name, value in row.then.items():
            o = cat.outcomes.get(name)
            if o is not None:
                try:
                    found += _numbers_of(facts.typed_value(name, o, value), outcome=True)
                except facts.FactError:
                    continue
    unique: dict[tuple[str, str], _Number] = {}
    for n in found:
        unique.setdefault((n.shown, n.kind), n)
    return list(unique.values())


class _Text:
    """The document's text as the number search reads it."""

    def __init__(self, pages: DocumentPages, quote: str | None, settings: dict[str, Any]) -> None:
        convention = numbers.document_convention(pages.pages.values())
        self.pages = pages
        self.tokens = {n: _tokens(text, convention) for n, text in pages.pages.items()}
        self.quote_tokens = _tokens(quote or "", convention)
        self.quote = quote or ""
        words = "|".join(sorted((re.escape(w) for w in settings["number_words"]), key=len, reverse=True))
        endings = "|".join(sorted((re.escape(e) for e in settings["number_word_endings"] if e), key=len, reverse=True))
        self.word = re.compile(rf"(?i)(?<!\w)({words})(?:{endings})?(?!\w)") if words else None
        self.word_values = {w.lower(): Decimal(v) for w, v in settings["number_words"].items()}

    def printed(self, value: Decimal, kind: str, cited: int | None) -> tuple[Where, int | None] | None:
        """Where a number is printed: in the quote, on the cited page, on another page (None: nowhere)."""
        def has(tokens: list[tuple[Decimal, bool]]) -> bool:
            return any(v == value for v, _ in tokens)

        if kind == "code":
            code = re.compile(rf"(?<!\d){re.escape(str(value))}(?!\d)")
            if code.search(self.quote):
                return "quote", cited
            for n, text in self.pages.pages.items():
                if code.search(text):
                    return ("page" if n == cited else "elsewhere"), n
            return None
        if has(self.quote_tokens):
            return "quote", cited
        order = sorted(self.tokens, key=lambda n: (n != cited, n))
        for n in order:
            if has(self.tokens[n]):
                return ("page" if n == cited else "elsewhere"), n
        return None

    def as_word(self, value: Decimal, cited: int | None) -> int | None:
        if self.word is None:
            return None
        for n in sorted(self.pages.pages, key=lambda n: (n != cited, n)):
            for m in self.word.finditer(self.pages.pages[n]):
                if self.word_values.get(m.group(1).lower()) == value:
                    return n
        return None

    def percents(self) -> set[Decimal]:
        return {v for tokens in self.tokens.values() for v, percent in tokens if percent}


def _where(n: _Number, text: _Text, cited: int | None, derive: dict[str, bool]) -> NumberSeen:
    if n.kind == "decimal" and n.outcome and derive.get("neutral_factor") and n.value == 1:
        return NumberSeen(kind=n.kind, value=n.shown, where="neutral")  # a factor of 1 changes nothing; a stray "1" does not stand for it
    printed = text.printed(n.value, n.kind, cited)
    if printed is not None:
        where, page = printed
        if page in text.pages.ocr_pages:
            return NumberSeen(kind=n.kind, value=n.shown, where="ocr", page=page)
        return NumberSeen(kind=n.kind, value=n.shown, where=where, page=page)
    if n.kind in ("count", "decimal") and n.value == n.value.to_integral_value():
        page = text.as_word(n.value, cited)
        if page is not None:
            return NumberSeen(kind=n.kind, value=n.shown, where="ocr" if page in text.pages.ocr_pages else "word", page=page)
    if n.kind == "decimal" and n.outcome and derive.get("percent_factor"):
        if any(n.value in (1 - p / 100, 1 + p / 100) for p in text.percents()):
            return NumberSeen(kind=n.kind, value=n.shown, where="derived")
    if n.kind == "count" and n.compared and derive.get("count_boundary"):
        for near in (n.value - 1, n.value + 1):
            if near >= 0 and (text.printed(near, "count", cited) is not None or text.as_word(near, cited) is not None):
                return NumberSeen(kind=n.kind, value=n.shown, where="derived")
    return NumberSeen(kind=n.kind, value=n.shown, where="not_found")


def _citation(rule: Rule, pages: DocumentPages, document_ref: str, document: ConditionDocument | None) -> list[Finding]:
    source = rule.source
    out: list[Finding] = []
    if source.document != document_ref:
        out.append(Finding("citation_document", "blocking", said(
            "it cites {{cited}}, not the document it was read from ({{document}})", cited=source.document, document=document_ref)))
    if source.page is None:
        out.append(Finding("citation_page", "attention", said("it names no page")))
    elif not 1 <= source.page <= pages.page_count:
        out.append(Finding("citation_page", "blocking", said("it cites page {{page}}, which the document does not have", page=source.page)))
    elif source.page in pages.skipped:
        out.append(Finding("citation_page", "blocking", said(
            "it cites page {{page}}, which was not read: its marking ({{marking}}) keeps it out", page=source.page,
            marking=pages.skipped[source.page])))
    if source.clause is None:
        out.append(Finding("citation_clause", "attention", said("it names no clause")))
    elif document is not None:
        section = next((s for s in document.sections if s.clause == source.clause), None)
        if section is None:
            out.append(Finding("citation_clause", "blocking", said(
                "it cites clause {{clause}}, which the document does not have", clause=source.clause)))
        elif section.page is not None and source.page is not None and abs(section.page - source.page) == 1                 and _quoted_on(rule, pages):
            # U-A3: a clause that starts at a page's foot and goes on over the next; the quote's page is checked apart
            out.append(Finding("citation_clause", "attention", said(
                "clause {{clause}} starts on page {{actual}}, the rule cites page {{page}}", clause=source.clause,
                actual=section.page, page=source.page)))
        elif section.page is not None and source.page is not None and section.page != source.page:
            out.append(Finding("citation_clause", "blocking", said(
                "clause {{clause}} is on page {{actual}}, not on page {{page}}", clause=source.clause, actual=section.page,
                page=source.page)))
    elif source.page in pages.pages and not re.search(rf"(?m)^\s*{re.escape(source.clause)}\.?(?:\s|$)", pages.pages[source.page]):
        out.append(Finding("citation_clause", "attention", said(
            "clause {{clause}} is not found on page {{page}}", clause=source.clause, page=source.page)))
    return out


def _letters(text: str) -> str:
    """231 (U-A3): only the letters and digits, lowercase: a word broken at a line's end ("vagyon-\\nvédelmi") and its
    whole form ("vagyonvédelmi") read the same."""
    return re.sub(r"[\W_]+", "", text.casefold())


ROUGH = 0.85  # U-A3: the share of a quote's letters a recognised page holds in order, near together


def _roughly(quote: str, page: str) -> bool:
    """U-A3: whether a page read by text recognition holds the quote with a few letters misread: at least `ROUGH` of its
    letters in order, within a stretch not much longer than the quote."""
    if not quote:
        return False
    # around the quote's longest stretch found as it is, a window a little longer than the quote
    anchor = difflib.SequenceMatcher(None, quote, page, autojunk=False).find_longest_match(0, len(quote), 0, len(page))
    if not anchor.size:
        return False
    slack = len(quote) // 4 + 2
    start = max(0, anchor.b - anchor.a - slack)
    window = page[start:anchor.b + (len(quote) - anchor.a) + slack]
    held = sum(b.size for b in difflib.SequenceMatcher(None, quote, window, autojunk=False).get_matching_blocks())
    return held >= ROUGH * len(quote)


_OMISSION = re.compile(r"\.\.\.|…|\[\.\.\.\]")


def _in_order(quote: str, page: str) -> bool:
    """U-A3: a quote with an omission ("A biztosító … nem áll be"): each of its parts on the page as printed, in order."""
    parts = [_letters(part) for part in _OMISSION.split(quote) if _letters(part)]
    if len(parts) < 2:
        return False
    at, text = 0, _letters(page)
    for part in parts:
        found = text.find(part, at)
        if found < 0:
            return False
        at = found + len(part)
    return True


def _quoted_on(rule: Rule, pages: DocumentPages) -> bool:
    """U-A3: whether the rule's quote stands on the page it cites (as printed, a broken word joined, or roughly on a page
    read by text recognition)."""
    source = rule.source
    if not source.quote or source.page not in pages.pages:
        return False
    quote, page = _plain(source.quote), pages.pages[source.page]
    return (quote in _plain(page) or _letters(quote) in _letters(page) or _in_order(quote, page)
            or (source.page in pages.ocr_pages and _roughly(_letters(quote), _letters(page))))


def _quote(rule: Rule, pages: DocumentPages) -> list[Finding]:
    source = rule.source
    if not source.quote or not source.quote.strip():
        return [Finding("quote", "attention", said("it quotes nothing"))]
    quote = _plain(source.quote)
    if source.page in pages.pages and (quote in _plain(pages.pages[source.page])
                                       or _letters(quote) in _letters(pages.pages[source.page])
                                       or _in_order(quote, pages.pages[source.page])):
        return []
    if source.page in pages.ocr_pages and source.page in pages.pages and _roughly(_letters(quote), _letters(pages.pages[source.page])):
        return [Finding("quote", "attention", said("its quote matches page {{page}} only roughly (text recognition): a person "
                                                   "compares it", page=source.page))]
    elsewhere = next((n for n, text in sorted(pages.pages.items()) if quote in _plain(text)), None)
    if elsewhere is not None:
        return [Finding("quote", "attention", said("its quote is on page {{actual}}, not on page {{page}}", actual=elsewhere,
                                                   page=source.page if source.page is not None else "–"))]
    return [Finding("quote", "blocking", said("its quote is not in the document"))]


def check(rule: Rule, pages: DocumentPages, *, document_ref: str, document: ConditionDocument | None = None) -> RuleCheck:
    """What code finds about a proposed rule read from the document `document_ref` (its pages as read)."""
    settings = cfg.load("rule_proposals")
    findings = [Finding("catalogue", "blocking", p) for p in product_rules.rule_problems(rule)]
    findings += _citation(rule, pages, document_ref, document)
    findings += _quote(rule, pages)
    seen: list[NumberSeen] = []
    try:
        cat = facts.catalogue(rule.catalogue)
    except FileNotFoundError:
        cat = None  # the catalogue's check names it
    if cat is not None:
        text = _Text(pages, rule.source.quote, settings)
        seen = [_where(n, text, rule.source.page, settings["derive"]) for n in _rule_numbers(rule, cat)]
    for n in seen:
        if n.where == "not_found":
            findings.append(Finding("number", "attention", said("{{value}} is not in the document: a person confirms it", value=n.value)))
        elif n.where == "ocr":
            findings.append(Finding("number", "attention", said(
                "{{value}} was read by text recognition on page {{page}}: a person confirms it", value=n.value, page=n.page)))
    return RuleCheck(tuple(findings), tuple(seen))
