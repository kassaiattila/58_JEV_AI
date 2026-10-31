"""265 (code review SEC-06): a config name never leaves the config folder, and the value normaliser takes a type's name.

`type:../service` read `configs/service.json` (in a process that had not frozen its configs, the service's own
settings), and the service's 422 named the machine's absolute path. Now a name with `..` or an absolute path is
refused, a missing config is named by its name, and the normaliser's `doc_type` is a type's name only.
"""

from __future__ import annotations

import pytest

from jav.core import cfg
from tests import test_api

env = test_api.env


@pytest.mark.parametrize("name", ["type:../service", "../service", "process:../../x", "callsite:..\detect", "C:/x/y"])
def test_a_name_that_leaves_the_folder_is_refused(name) -> None:
    with pytest.raises(ValueError, match="not a config name"):
        cfg.path_of(name)


def test_a_type_pack_in_a_subfolder_is_still_a_name() -> None:
    assert cfg.path_of("type:_base/utility_bill_hu").name == "utility_bill_hu.json"


def test_a_missing_config_is_named_by_its_name() -> None:
    with pytest.raises(FileNotFoundError) as err:
        cfg._disk("no_such_config_265")
    assert str(err.value) == "a config is missing: no_such_config_265"


def test_the_normaliser_takes_a_type_s_name_only(env) -> None:
    r = env["client"].post("/api/normalize", headers=test_api.HUMAN,
                           json={"doc_type": "../service", "field": "x", "text": "1"})
    assert r.status_code == 422 and "service.json" not in r.text and ":\\\\" not in r.text
