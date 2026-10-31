"""264 (plan E, F5; the owner's decision of 2026-10-31): a run's item list names an item as the batch's list does. An
item that did not finish in this run (a trial, a stopped or a failed item) has no unified name of this run; it shows
the name of the run whose result counts, so the same document is not called by two names on two pages. Synthetic
names."""
from __future__ import annotations

from jav.app import datasets, naming, work


def test_an_item_unfinished_in_this_run_takes_the_counted_run_s_name(monkeypatch):
    own = {"i1": naming.ItemName("Synthetic_2026-03_invoice.pdf", "ready", run_id="run-2"), "i2": naming.PENDING,
           "i3": naming.NO_NAME}
    counted = {"i1": naming.ItemName("Synthetic_2026-03_invoice_old.pdf", "ready", run_id="run-1"),
               "i2": naming.ItemName("Synthetic_2026-04_invoice.pdf", "review", "uncertain", "run-1"),
               "i3": naming.NO_NAME}
    monkeypatch.setattr(naming, "run_item_names", lambda run_id: dict(own))
    monkeypatch.setattr(naming, "package_item_names", lambda wp: dict(counted))
    monkeypatch.setattr(work, "get", lambda wp_id: {"id": wp_id, "items": []})
    names = datasets.run_item_names({"run_id": "run-2", "workpackage_id": "wp-1"})
    assert names["i1"].unified == "Synthetic_2026-03_invoice.pdf"  # this run's own name stays
    assert (names["i2"].unified, names["i2"].state, names["i2"].run_id) == ("Synthetic_2026-04_invoice.pdf", "review", "run-1")
    assert names["i3"] is naming.NO_NAME  # an email has no file name of its own


def test_the_counted_names_are_read_only_when_an_item_needs_them(monkeypatch):
    monkeypatch.setattr(naming, "run_item_names", lambda run_id: {"i1": naming.ItemName("A.pdf", "ready", run_id="run-2")})

    def never(wp):
        raise AssertionError("the counted run's names were read although every item has its own")

    monkeypatch.setattr(naming, "package_item_names", never)
    assert datasets.run_item_names({"run_id": "run-2", "workpackage_id": "wp-1"})["i1"].unified == "A.pdf"
