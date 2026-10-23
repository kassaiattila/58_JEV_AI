"""Any number of domains (191, plan F-quote-package B1).

Guarantees tested: `registrations.load_all` registers every domain in `DOMAINS`, not exactly two: the first domain,
then the shared registrations (the workflows, the package scopes), then each further domain in its order, which is
the order the finance and email domains have had since 180; every domain module names its service modules and its own
modules; the quotes domain is the third.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from jav import package_scope, registrations, workflows
from jav.domains import DOMAINS
from tests.test_dependency_direction import domain_modules


def _domain(name: str, calls: list[str]) -> SimpleNamespace:
    return SimpleNamespace(register=lambda: calls.append(name))


def test_the_first_domain_then_the_shared_registrations_then_the_others_in_order() -> None:
    calls: list[str] = []
    domains = [_domain(name, calls) for name in ("first", "second", "third")]
    order = registrations.order(domains)
    assert order[1:3] == [workflows.register, package_scope.register]
    for register in (order[0], *order[3:]):
        register()
    assert calls == ["first", "second", "third"]


def test_every_domain_module_names_its_service_and_has_its_modules() -> None:
    for name in DOMAINS:
        module = importlib.import_module(name)
        assert callable(module.register), name
        assert isinstance(module.SERVICE, tuple), name
        assert len(domain_modules(name)) > 1, name  # 208: the ones in its folder


def test_the_quotes_domain_is_the_third() -> None:
    assert DOMAINS[2] == "jav.domains.quotes"
    quotes = importlib.import_module("jav.domains.quotes")
    assert {"domains.quotes", "quote_golden"} <= domain_modules(quotes.__name__)
