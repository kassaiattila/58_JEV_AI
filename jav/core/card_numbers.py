"""144 (DECISIONS 144): a payment card number in a statement's text, recognised and masked.

A CIB statement prints a card charge's full card number in its detail row (`1234 5678 9012 3456 20260105 101500; …`)
and a credit card statement heads each card's purchases with it; 23 lines of the store held a full card number in
their memo. The owner's decision: the readers keep only the first six and the last four digits, as the banks' own XML
statements print it (`123456xxxxxx3456`). A number counts as a card number only in a card number's shape — sixteen
digits on their own, in one run or in four groups of four — whose check digit is right (the Luhn algorithm) and whose
first digit is that of a card scheme (2-6); a run of digits that merely contains such a window (a date, a time and an
amount side by side), or four groups inside a longer grouped number (an IBAN in a memo), is left alone.

167 (review S-3): the groups may be separated by spaces, hyphens or dots (one kind per number: GPT often returns
them hyphenated, `1234-5678-9012-3456`), and a 15-digit American Express number (first digits 34 or 37, printed in one run or as
4-6-5 groups) counts too. A 19-digit number does not. The data guard uses the same pattern (`CARD`), so what the
masking recognises and what the guard stops cannot drift apart.

Layer: a business helper without dependencies; `jav.domains.finance.statement_table` (the readers), `jav.domains.finance.reconcile` (the pairing
views of a statement extracted by AI), the saving and the downloads of extracted data, and `jav.data_guard` use it.
"""

from __future__ import annotations

import re
from typing import Any

_SEPARATORS = (" ", "-", ".")


def _grouped(sizes: tuple[int, ...]) -> str:
    """Digit groups of the given sizes, one kind of separator per number, not inside a longer number grouped the same
    way (no digit and that separator before the first group)."""
    return "|".join(f"(?<!\\d{re.escape(sep)})" + re.escape(sep).join(f"\\d{{{n}}}" for n in sizes)
                    for sep in _SEPARATORS)


# A card number's shape: sixteen or fifteen digits in one run, four groups of four, or American Express's 4-6-5 groups;
# no digit right before or after it. Whether it is a card number decides `is_card_number`.
CARD = re.compile(f"(?<!\\d)(?:\\d{{16}}|\\d{{15}}|{_grouped((4, 4, 4, 4))}|{_grouped((4, 6, 5))})(?!\\d)")
_MASKED = re.compile(r"^(?=.{15,16}$)(?P<lead>\d{4,6})[xX*]{5,8}\d{4}$")  # a number the bank already masked


def check_digit_ok(digits: str) -> bool:
    """The Luhn check of a card number's digits."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return bool(digits) and total % 10 == 0


def is_card_number(digits: str) -> bool:
    """Sixteen digits with a scheme's first digit (2-6), or fifteen with American Express's first two (34, 37); either
    with a right Luhn check digit."""
    if not digits.isdigit() or not check_digit_ok(digits):
        return False
    return (len(digits) == 16 and digits[0] in "23456") or (len(digits) == 15 and digits[:2] in ("34", "37"))


def _mask_digits(digits: str) -> str:
    return f"{digits[:6]}{'x' * (len(digits) - 10)}{digits[-4:]}"


def masked(card: str | None) -> str | None:
    """A card number as `123456xxxxxx3456` (fifteen digits: `123456xxxxx3456`): a full number masked, an already
    masked one in one form, else None."""
    if not card:
        return None
    compact = re.sub(r"[ .-]", "", card)
    if is_card_number(compact):
        return _mask_digits(compact)
    if (m := _MASKED.match(compact)) is None:
        return None
    lead = min(6, len(m["lead"]))  # a statement printing fewer leading digits keeps only those
    return f"{compact[:lead]}{'x' * (len(compact) - 4 - lead)}{compact[-4:]}"


_DIGEST = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{32,}(?![0-9A-Za-z])")  # 160: a document's id, a source's sha256


def mask_text(text: str | None) -> str | None:
    """The text with every full card number in it masked (anything else unchanged). 160 (review S-2): a digest (32 or
    more lowercase hexadecimal digits in one run) is left as it is, so masking never changes an identity."""
    if not text:
        return text

    def one(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        return _mask_digits(digits) if is_card_number(digits) else m.group(0)

    out, end = [], 0
    for d in _DIGEST.finditer(text):
        out += [CARD.sub(one, text[end:d.start()]), d.group(0)]
        end = d.end()
    return "".join(out) + CARD.sub(one, text[end:])


def mask_values(value: Any) -> Any:
    """153 (review C4): every text in a value (a dict's values, a list's items, nested) with its full card numbers
    masked; anything else unchanged. Extracted data is saved and exported this way, so a card statement processed as a
    document keeps only the first six and the last four digits too (the decision of 144)."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: mask_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_values(v) for v in value]
    return value
