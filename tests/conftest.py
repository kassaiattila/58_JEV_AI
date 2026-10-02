"""Shared test setup (065): the tests must not write to the operational log.

The `worker` command (`jav/work_cli.py`) attaches the operational log (`runs/logs/worker.log`) to the root logger; in
the test suite this left false "worker started / processed=1" lines in the real log on every run, and after attaching,
the other tests' logs went there too. While the tests run, the log folder is temporary.
"""

import pytest

from jav import gpt_choice
from jav.runtime import applog, calls


@pytest.fixture(autouse=True, scope="session")
def _no_ops_log(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(applog, "LOG_DIR", tmp_path_factory.mktemp("logs"))
        yield


@pytest.fixture(autouse=True)
def _no_live_gpt_choice():
    """089: a test never sends a GPT choice question (type or email intent without JEV) to OpenAI, which would be a paid
    call; a test that needs an answer installs its own stand-in with `gpt_choice.use_agent_factory`."""

    def refuse(output_model, instructions):
        raise AssertionError("a test tried a live GPT call (jav/gpt_choice.py); install a stand-in with use_agent_factory")

    with gpt_choice.use_agent_factory(refuse):
        yield


@pytest.fixture(autouse=True)
def _release_call_holders():
    """092: the holder locks a test's reservations took are let go after it, so that no lock file stays open in a
    temporary folder and no test inherits another's holder."""
    yield
    calls.release_all_holders()
