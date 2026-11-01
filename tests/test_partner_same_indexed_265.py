"""265 (code review APPR-13): the same-partner check is an indexed query that finds what the loop found.

Recording or changing a partner looked for another active one with the same tax number (or the same name, when not
both have a tax number) by reading every active partner in Python. It is now one indexed query that keeps the loop's
answer: the first match in the table's order. Invented partners; no AI.
"""

from __future__ import annotations

from jav.app import partners, registrations
from jav.core import store


def _loop(c, out, partner_id):
    """The check as it was, for the comparison."""
    from jav.app import parties
    from jav.core import versions

    tax, name = parties.tax_key(out["tax_number"]), parties.name_key(out["name"])
    for row in c.execute("SELECT partner_id, tax_key, name_key FROM partner_versions WHERE state=?", (versions.ACTIVE,)):
        if row["partner_id"] == partner_id:
            continue
        if tax and row["tax_key"] == tax:
            return str(row["partner_id"])
        if name and row["name_key"] == name and not (tax and row["tax_key"]):
            return str(row["partner_id"])
    return None


def test_the_query_finds_what_the_loop_found(tmp_path) -> None:
    registrations.load_all()
    with store.use_store(tmp_path / "p.sqlite"):
        made = [partners.create(partners.PartnerIn(name=n, tax_number=t, roles=["supplier"]), "Invented Person")["partner_id"]
                for n, t in (("Alfa Kft.", "12345676-2-41"), ("Beta Bt.", None), ("Gamma Zrt.", "11111119-2-41"))]
        cases = [({"name": "Alfa Kft.", "tax_number": "12345676-2-41"}, None), ({"name": "Other", "tax_number": "12345676-2-41"}, None),
                 ({"name": "Beta Bt.", "tax_number": None}, None), ({"name": "Beta Bt.", "tax_number": "99999990-2-41"}, None),
                 ({"name": "Gamma Zrt.", "tax_number": None}, None), ({"name": "Alfa Kft.", "tax_number": "12345676-2-41"}, made[0]),
                 ({"name": "Nobody", "tax_number": None}, None)]
        with store.connect() as c:
            for out, own in cases:
                assert partners._same(c, out, own) == _loop(c, out, own), out
