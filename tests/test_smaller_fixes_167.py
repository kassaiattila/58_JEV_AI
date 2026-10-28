"""167 (review 153 E): smaller fixes. A party name read with a control character (a broken glyph read as NUL)
reaches the reconciliation without it; the result table showed it as it was."""

from __future__ import annotations

from jav.domains.finance.reconcile_store import printable


def test_control_characters_become_one_space() -> None:
    assert printable("Example\x00Kft.") == "Example Kft."
    assert printable("Example \x00\x07 Kft.\x7f") == "Example Kft."


def test_other_values_stay() -> None:
    assert printable(None) is None
    assert printable("Example Kft.") == "Example Kft."
    assert printable(12) == 12


def test_a_document_that_is_not_a_pdf_has_no_page_image(tmp_path) -> None:
    """167 (review 153 E): a Word, Excel, text or statement file is refused with its own message, not PDFium's error."""
    import pytest

    from jav.documents import page_image

    path = tmp_path / "statement.xml"
    path.write_text("<Document/>", encoding="utf-8")
    with pytest.raises(page_image.BadPage) as caught:
        page_image.render(path, 1, data=path.read_bytes())
    assert caught.value.params == {"kind": ".xml"}
    assert "no page image" in str(caught.value)


def test_a_correction_in_the_activity_log_names_its_fields_not_their_values() -> None:
    """167 (review 153 E): the corrected fields' keys (the values never go into the log); before, an item hash."""
    from jav.app.activity import _detail

    assert _detail("correction", '{"net_total": "1000", "invoice_number": "INV-1"}') == "invoice_number,net_total"
    assert _detail("correction", "{}") is None
    assert _detail("correction", "not json") is None


def test_a_reconciliation_package_shows_no_item_count(monkeypatch) -> None:
    """167 (review 153 E): its lines are not items, so the list left the count empty instead of 0. 231 (U2a; the
    owner's decision of 2026-10-28: one work list, the cases): a reconciliation is a case, which the list of every
    document batch asks to be left out, so no row of the list counts lines as items."""
    from jav.app import datasets, work_views

    asked: list[dict] = []
    row = {"id": "wp-2", "name": "x", "source_kind": "folder", "items": 3, "last_run_id": None,
           "next": {"stage": "process", "label": "", "code": "start", "params": {}}}

    def listed(**kw):
        asked.append(kw)
        return [dict(row)]

    monkeypatch.setattr(work_views, "workpackage_list", listed)
    _cols, rows = datasets._workpackages({})
    assert [r["items"] for r in rows] == [3] and asked == [{"include_archived": False, "batches_only": True}]
