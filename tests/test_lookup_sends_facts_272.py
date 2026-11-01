"""272 (K2, the check of X-19): a lookup sends only the facts its connector names, not just as many of them.

265 (X-19) refused a lookup that sends more kinds of data than its connector's `sends` list has lines: it compared
counts, so a lookup could send a person's name where the connector declares a tax number. A lookup connector now
names the facts it may send (`sends_facts` in configs/connectors.json, beside the readable `sends`), and a lookup
whose question carries any other fact is refused when its process pack is read. Real config files; no call.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jav.app.lookups import Lookup
from jav.core import cfg, connectors


def test_a_lookup_may_not_send_a_fact_its_connector_does_not_name():
    with pytest.raises(ValidationError, match="company_name"):
        Lookup(connector="invented_company_register", from_step="facts", asks={"tax_number": "company_name"},
               answers={"company.status": "company_status"})


def test_a_lookup_within_its_connector_s_facts_is_read():
    lookup = Lookup(connector="invented_sanctions_list", from_step="facts", asks={"name": "company_name"},
                    asks_if_known={"tax_number": "tax_number"}, answers={"listed": "sanctions_listed"})
    assert lookup.connector == "invented_sanctions_list"


def test_the_invented_lookups_name_their_facts():
    assert connectors.of("invented_company_register").sends_facts == ("tax_number",)
    assert connectors.of("invented_sanctions_list").sends_facts == ("company_name", "tax_number")


def test_a_lookup_through_a_connector_that_names_no_facts_is_refused():
    assert connectors.of("mnb_rates").sends_facts == ()  # asked by the exchange rate module, not by a lookup step
    with pytest.raises(ValidationError, match="names no facts"):
        Lookup(connector="mnb_rates", from_step="facts", asks={"date": "invoice_date"}, answers={"rate": "rate"})


def test_a_connector_s_facts_must_be_names():
    raw = {**cfg.load("connectors")["connectors"]["invented_company_register"], "sends_facts": [""]}
    with pytest.raises(connectors.ConnectorError, match="sends_facts"):
        connectors._read("x", raw)
