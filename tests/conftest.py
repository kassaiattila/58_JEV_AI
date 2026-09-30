"""Shared test setup (065): the tests must not write to the operational log.

The `worker` command (`jav/work_cli.py`) attaches the operational log (`runs/logs/worker.log`) to the root logger; in
the test suite this left false "worker started / processed=1" lines in the real log on every run, and after attaching,
the other tests' logs went there too. While the tests run, the log folder is temporary.
"""

import pytest

from jav.runtime import applog


@pytest.fixture(autouse=True, scope="session")
def _no_ops_log(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(applog, "LOG_DIR", tmp_path_factory.mktemp("logs"))
        yield
