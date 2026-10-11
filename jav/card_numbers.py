"""144 (DECISIONS 144): a payment card number in a statement's text, recognised and masked.

A CIB statement prints a card charge's full card number in its detail row (`1234 5678 9012 3456 20260105 101500; …`)
and a credit card statement heads each card's purchases with it; 23 lines of the store held a full card number in
their memo. The owner's decision: the readers keep only the first six and the last four digits, as the banks' own XML
statements print it (`123456xxxxxx3456`). A number counts as a card number only in a card number's shape — sixteen
digits on their own, in one run or in four groups of four — whose check digit is right (the Luhn algorithm) and whose
first digit is that of a card scheme (2-6); a run of digits that merely contains such a window (a date, a time and an
amount side by side), or four groups inside a longer grouped number (an IBAN in a memo), is left alone.

Layer: a business helper without dependencies; `jav.statement_table` (the readers) and `jav.reconcile` (the pairing
views of a statement extracted by AI) use it.
"""

from __future__ import annotations

import re

# sixteen digits in one run, or four groups of four that are not part of a longer grouped number (an IBAN printed in
# groups of four): no digit and a space before the first group
_CARD = re.compile(r"(?<!\d)(?:(\d{16})|(?<!\d )(\d{4}) (\d{4}) (\d{4}) (\d{4}))(?!\d)")
_MASKED = re.compile(r"^(?=.{16}$)(?P<lead>\d{4,6})[xX*]{6,8}\d{4}$")  # a number the bank already masked


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
    return len(digits) == 16 and digits.isdigit() and digits[0] in "23456" and check_digit_ok(digits)


def masked(card: str | None) -> str | None:
    """A card number as `123456xxxxxx3456`: a full number masked, an already masked one in one form, else None."""
    if not card:
        return None
    compact = re.sub(r"[ -]", "", card)
    if is_card_number(compact):
        return f"{compact[:6]}xxxxxx{compact[-4:]}"
    if (m := _MASKED.match(compact)) is None:
        return None
    lead = min(6, len(m["lead"]))  # a statement printing fewer leading digits keeps only those
    return f"{compact[:lead]}{'x' * (12 - lead)}{compact[-4:]}"


def mask_text(text: str | None) -> str | None:
    """The text with every full card number in it masked (anything else unchanged)."""
    if not text:
        return text

    def one(m: re.Match[str]) -> str:
        digits = m.group(1) or "".join(m.group(i) for i in range(2, 6))
        return f"{digits[:6]}xxxxxx{digits[-4:]}" if is_card_number(digits) else m.group(0)

    return _CARD.sub(one, text)
