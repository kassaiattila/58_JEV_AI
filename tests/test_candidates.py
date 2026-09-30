"""Candidate finders - offline, on synthetic layouts (independent of the legacy project's PDFs)."""

from jav.candidates import find_all, find_currencies
from jav.models import CellLayout, LineLayout


def _line(no: int, *cells: tuple[str, float]) -> LineLayout:
    return LineLayout(
        no=no,
        page=1,
        text="   ".join(t for t, _ in cells),
        cells=[CellLayout(text=t, x0=x, x1=x + 6 * len(t)) for t, x in cells],
    )


def _two_column_invoice() -> list[LineLayout]:
    # two-column header in the style of NAV Online Számlázó, with an IBAN wrapped over two lines
    return [
        _line(1, ("e-SZÁMLA", 480)),
        _line(2, ("PRBA-2021-37", 70)),
        _line(3, ("Sorszám:", 28)),
        _line(4, ("ELADÓ:", 28), ("VEVŐ:", 305)),
        _line(5, ("PELDADATA KERESKEDELMI ÉS", 28), ("BESTIXCOM INFORMATIKAI ÉS", 305)),
        _line(6, ("SZOLGÁLTATÓ BETÉTI TÁRSASÁG", 28), ("TANÁCSADÓ KORLÁTOLT", 305)),
        _line(7, ("Magyarország 1119 BUDAPEST", 28), ("FELELŐSSÉGŰ TÁRSASÁG", 305)),
        _line(8, ("MINTA UTCA 12", 28)),
        _line(9, ("Magyarország 1117 BUDAPEST", 305)),
        _line(10, ("Magyar adószám:", 28), ("24681353-1-43", 133), ("PRÓBA utca 21,", 305)),
        _line(11, ("Magyar adószám:", 305), ("28642099-2-42", 410)),
        _line(12, ("Számlaszám:", 28), ("10000001-20000002-00000000", 133)),
        _line(13, ("HU50 1000 0001 2000 0002 0000", 133)),
        _line(14, ("IBAN:", 28), ("0000", 133)),
        _line(15, ("Fizetési mód: Átutalás", 31), ("Teljesítés: 2021.03.19.", 135), ("Keltezés: 2021.03.19.", 243), ("Fizetési határidő: 2021.03.25.", 345)),
        _line(16, ("Pénznem: HUF", 31)),
        _line(17, ("Tanácsadás", 30), ("1,00", 108), ("Darab", 182), ("650 000,00", 233), ("AAM", 311), ("0,00", 372), ("650 000,00", 455)),
        _line(18, ("Számla nettó értéke", 30), ("650 000,00 HUF", 300)),
        _line(19, ("ÁFA százaléka és értéke AAM", 30), ("0,00 HUF", 300)),
        _line(20, ("Számla bruttó végösszege", 30), ("650 000,00 HUF", 300)),
        _line(21, ("Fizetendő összeg", 30), ("650 000,00 HUF", 300)),
        _line(22, ("Telefon: 36200001234", 30)),
    ]


def test_two_column_names_are_joined_per_column():
    names = {c.label for c in find_all(_two_column_invoice())["name"]}
    assert "PELDADATA KERESKEDELMI ÉS SZOLGÁLTATÓ BETÉTI TÁRSASÁG" in names
    assert "BESTIXCOM INFORMATIKAI ÉS TANÁCSADÓ KORLÁTOLT FELELŐSSÉGŰ TÁRSASÁG" in names
    # the address is not joined to the name
    assert not any("1119" in n for n in names)


def test_wrapped_iban_is_reassembled_and_same_account_deduped():
    ibans = find_all(_two_column_invoice())["iban"]
    labels = [c.label for c in ibans]
    assert "HU50 1000 0001 2000 0002 0000 0000" in labels
    # the same account in domestic format -> one candidate (the form seen first is the label)
    assert len(ibans) == 1


def test_tax_ids_formatted_and_phone_excluded():
    tax = {c.label for c in find_all(_two_column_invoice())["tax_id"]}
    assert tax == {"24681353-1-43", "28642099-2-42"}  # the 11-digit phone number fails the check digit


def test_dates_deduped_by_value_with_contexts():
    dates = find_all(_two_column_invoice())["date"]
    assert [c.label for c in dates] == ["2021-03-19", "2021-03-25"]
    assert dates[0].occurrences == 2


def test_invoice_number_from_line_above_label():
    inv = {c.label for c in find_all(_two_column_invoice())["invoice_number"]}
    assert "PRBA-2021-37" in inv
    assert "10000001-20000002-00000000" not in inv  # bank account masked


def test_money_normalized_and_percent_excluded():
    money = {c.label for c in find_all(_two_column_invoice())["money"]}
    assert {"650000", "0"} <= money
    assert "24681353" not in money  # tax number masked


def test_currency_detection():
    assert find_currencies(_two_column_invoice()) == ["HUF"]


def test_szamlazz_hu_layout_name_with_trailing_registration_number():
    lines = [
        _line(1, ("Mintás Péter Pál, 11112222", 160), ("Bank neve: Takarékbank", 393)),
        _line(2, ("6799 Mintafalu", 160), ("SWIFT:TAKBHUHB", 393)),
        _line(3, ("Adószám: 53102467-2-26", 160), ("5760012534567898", 393)),
        _line(4, ("Sorszám: PM-2022-418", 459)),
        _line(5, ("VEVŐ:", 35)),
        _line(6, ("BestIxCom Informatikai és Tanácsadó Kft.", 35), ("Teljesítés dátuma:", 345), ("2022.11.15.", 514)),
        _line(7, ("Összesen:", 493)),
        _line(8, ("22 150 Ft", 499)),
    ]
    c = find_all(lines)
    assert "Mintás Péter Pál" in {x.label for x in c["name"]}
    assert "BestIxCom Informatikai és Tanácsadó Kft." in {x.label for x in c["name"]}
    assert "PM-2022-418" in {x.label for x in c["invoice_number"]}
    assert "5760012534567898" in {x.label for x in c["iban"]}
    assert "22150" in {x.label for x in c["money"]}
