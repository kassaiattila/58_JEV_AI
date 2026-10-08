"""129 (backlog Q-vendor-name-tagline): a party name ends at its legal form.

The release trial of 128 found a shop's tagline glued to the supplier name on a pro forma invoice ("... KFT." followed
by what the shop sells), with no to-do. The rule is general and runs in code on both paths, after the choice: the
text after the name's last legal form is cut when it is clearly not part of a registered name (an address, a tax or
registration number, a remark after a separator, a lower-case phrase), and kept when it continues the name (another
legal form, a branch, a winding-up state, a trading name, a partner). The candidates sent to JEV do not change, so the
saved JEV answers stay valid. Invented names only; no AI call.
"""

from __future__ import annotations

import pytest

from jav import typepack
from jav.candidates import trim_after_legal_form
from jav.jev_select import picks_to_invoice
from jav.models import FieldPick, normalize_value


@pytest.mark.parametrize("name,expected", [
    ("Minta Tanacsado KFT. Mobil es szamitastechnikai szakuzlet", "Minta Tanacsado KFT."),  # a shop's tagline
    ("Minta Tavkozlesi Nyrt. 1097 Budapest, Minta utca 36", "Minta Tavkozlesi Nyrt."),  # an address
    ("Example Pty. Ltd.ABN 80 158 929 938, VAT EU372042198", "Example Pty. Ltd."),  # registration numbers
    ("Example Pty. Ltd. ABN 80 158 929 938", "Example Pty. Ltd."),
    ("Minta Kft - Paciens: Minta Peter", "Minta Kft"),  # a remark after a separator
    ("Minta Kft. 01-09-123456 HU12345678", "Minta Kft."),
    ("Minta Kft., 1141 Budapest", "Minta Kft."),
])
def test_what_is_not_part_of_the_name_is_cut(name, expected):
    assert trim_after_legal_form(name) == expected


@pytest.mark.parametrize("name", [
    "Example Pty. Ltd",  # two legal forms
    "MINTA KORLÁTOLT FELELŐSSÉGŰ TÁRSASÁG",
    "Minta Hanna E.V. KISADOZO",
    "Exampleboard BV dba Example",  # a trading name
    "Minta sp. z o.o. spółka komandytowa",
    "Minta GmbH & Co. KG",
    "Minta Zrt. Magyarországi Fióktelepe",  # a branch
    "Minta Kft. f.a.",  # under liquidation
    "Minta Alapitvany Ovodaja",  # one capitalised word: may be a name
    "Kovács és Társa Bt.",
    "Kft. Minta",  # nothing before the legal form
    "Example Ireland Operations Ltd",
    "Minta Peter",  # a private person: no legal form
    "",
])
def test_what_continues_the_name_is_kept(name):
    assert trim_after_legal_form(name) == name


def test_the_generative_path_trims_a_name_but_no_other_kind():
    reasons: list[str] = []
    assert normalize_value("name", "Minta Kft. Mobil es szamitastechnikai szakuzlet", "supplier_name", reasons) == "Minta Kft."
    assert normalize_value("address", "Minta Kft. 1141 Budapest, Minta utca 1", "supplier_address", reasons) == "Minta Kft. 1141 Budapest, Minta utca 1"
    assert reasons == []


def test_the_selection_path_trims_the_chosen_name():
    pack = typepack.get("invoice_hu")
    label = "Minta Kft. Mobil es szamitastechnikai szakuzlet"
    picks = {"supplier_name": FieldPick(field="supplier_name", label=label, confidence=0.8, n_options=2, request_id="r")}
    invoice, _reasons = picks_to_invoice(picks, {}, pack)
    assert invoice.supplier_name == "Minta Kft."
