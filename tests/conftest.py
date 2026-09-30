"""Közös tesztbeállítás (065): a tesztek nem írhatnak az üzemi naplóba.

A `worker` parancs (`jav/work_cli.py`) az üzemi naplót (`runs/logs/worker.log`) kapcsolja a gyökér-naplózóra; a
tesztsorban ez minden futáskor hamis „worker started / processed=1” sorokat hagyott a valódi naplóban, és a kapcsolás
után a többi teszt naplója is oda került. A tesztek ideje alatt a naplómappa ideiglenes.
"""

import pytest

from jav.runtime import applog


@pytest.fixture(autouse=True, scope="session")
def _no_ops_log(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(applog, "LOG_DIR", tmp_path_factory.mktemp("logs"))
        yield
