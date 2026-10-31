"""265 (code review X-03, X-04): the injection check cannot be switched off by a default, and a case's picked files
have a bound.

- X-03: the warning signs that always wait for a person (`email.json` `signal_review`) could be set to none by an
  installation default (at least 0), which switched off the injected-instruction check; the default now keeps it.
- X-04: a case's source took 10 000 picked paths (a 10 MB request); now at most 2000 (a folder takes any number).
Real rule files, an empty store; no AI call.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jav.app import registrations, rule_defaults
from jav.core import cfg, store

registrations.load_all()


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "limits.sqlite"):
        rule_defaults.use()
        rule_defaults._forget()
        try:
            yield tmp_path
        finally:
            cfg.use_defaults(None)
            rule_defaults._forget()


def test_a_default_keeps_the_injected_instruction_waiting_for_a_person(db) -> None:
    with pytest.raises(rule_defaults.DefaultError, match="keeps prompt_injection"):
        rule_defaults.propose("email", "signal_review", [], "anna")
    rule_defaults.propose("email", "signal_review", ["prompt_injection"], "anna")


def test_a_case_s_picked_files_have_a_bound() -> None:
    from jav.service.api_cases import Source

    assert Source(kind="files", files=[f"C:/docs/{n}.pdf" for n in range(2000)])
    with pytest.raises(ValidationError):
        Source(kind="files", files=[f"C:/docs/{n}.pdf" for n in range(2001)])
