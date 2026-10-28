"""231 (plan stage A, A7a): a case keeps the version of its process pack it started on.

A pack changes by a new version; a case started on an older one keeps its steps (the process core stores its
definition) and, since A7a, its screens and outputs: the older version comes back from the calculation snapshot the
case was linked to when it started. Synthetic data, the IT quote's pack.
"""

from __future__ import annotations

import copy

from jav.app import case_views, process_packs, process_runtime
from jav.core import cfg
from tests import test_document_result_174 as rows
from tests.test_quote_path_231 import golden  # noqa: F401 - the fixture


def test_a_case_shows_the_pack_version_it_started_on_after_the_pack_changes(golden, monkeypatch) -> None:  # noqa: F811 - the shared fixture
    cases, _seen = golden
    case_id = process_runtime.start_case("it_quote", {"record": {"workpackage_id": rows.WP, "item_id": rows._id(cases[0].id)}},
                                         name="Quote", actor="anna")
    data = copy.deepcopy(cfg.load("process:it_quote"))
    data["meta"]["version"] = "9.0.0"
    data["screens"]["tabs"][0]["label"] = "Changed request"
    changed = process_packs.ProcessPack.model_validate(data)
    monkeypatch.setattr(process_packs, "load", lambda pack_id: changed)
    assert process_runtime.pack_of(case_id) == ("it_quote", "1.6.0")
    started_on = process_runtime.pack_for(case_id)
    assert started_on.version == "1.6.0" and started_on.screens.tabs[0].label == "Request"
    page = case_views.view(case_id)
    assert page["case"]["version"] == "1.6.0" and page["tabs"][0]["label"] == "Request"
    assert process_runtime.outputs_of(case_id) == ("quote",)
