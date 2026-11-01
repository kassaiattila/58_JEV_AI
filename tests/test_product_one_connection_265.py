"""265 (code review APPR-12): a product is resolved over one connection; a fact catalogue is built once per read.

Resolving a product opened a connection for the product and for each of its documents and rules (about a hundred on
one page view), and every call built its fact catalogue anew. Now the product, its documents and rules share one
connection, and a catalogue is built again only when its config is read anew. Invented product; no AI.
"""

from __future__ import annotations

import contextlib

from jav.app import facts, product_rules
from jav.core import store
from tests.test_product_rules_231 import ANNA, BELA, _product, _setup, db  # noqa: F401 (the fixture)


def test_a_product_takes_one_connection(db, monkeypatch) -> None:  # noqa: F811
    _setup()
    product_rules.add("product", "invented_property", _product(), actor=ANNA)
    product_rules.activate("product", "invented_property", 1, actor=BELA)
    opened = []
    real = store.connect

    @contextlib.contextmanager
    def counted(*a, **k):
        opened.append(1)
        with real(*a, **k) as c:
            yield c

    monkeypatch.setattr(store, "connect", counted)
    resolved = product_rules.product_at("invented_property@1")
    assert len(resolved.rules) == 1 and len(resolved.documents) == 2 and len(opened) == 1


def test_a_catalogue_is_built_once_per_read() -> None:
    assert facts.catalogue("property") is facts.catalogue("property")
