"""195 (plan G-tidy R4): the local service's addresses live in modules by theme, and `create_app` adds each once.

The shared addresses used to be written inside `create_app`; they moved, as they were, into `jav/service/api_*.py` modules by
theme. These checks keep the split whole: every such module is added, none twice, the shared themes stay around the
logic packs' and domains' own modules in their old order, and no address is registered twice.
"""

from __future__ import annotations

import importlib
from collections import Counter

from fastapi.routing import APIRoute

from jav.service import api
from jav.core.config import PROJECT_ROOT


def test_every_service_module_is_added_exactly_once():
    root = PROJECT_ROOT / "jav"  # 208: a domain's addresses are in its folder
    on_disk = {".".join(p.relative_to(PROJECT_ROOT).with_suffix("").parts) for p in root.rglob("api_*.py")}
    added = api.route_modules()
    assert [name for name, n in Counter(added).items() if n > 1] == []
    assert set(added) == on_disk
    assert all(callable(importlib.import_module(name).routes) for name in added)


def test_the_shared_themes_stay_around_the_packs_and_domains_in_their_old_order():
    added = api.route_modules()
    assert tuple(added[:4]) == api.SHARED_BEFORE == ("jav.service.api_workpackages", "jav.service.api_runs", "jav.service.api_results",
                                                     "jav.service.api_items")
    # 231 (A6): the process packs' cases come after the workflows; (B1) the partner register after them; (B2) the process
    # packs' own settings after the partners
    assert tuple(added[-7:]) == api.SHARED_AFTER == ("jav.service.api_outputs", "jav.service.api_workflows", "jav.service.api_cases",
                                                     "jav.service.api_partners", "jav.service.api_processes",
                                                     "jav.service.api_system", "jav.service.api_settings")
    assert added[4:-7] == api.service_modules()


def test_no_address_is_registered_twice_and_the_unknown_address_answers_last(tmp_path):
    app = api.create_app(store_path=tmp_path / "jav.sqlite")
    routes = [r for r in app.routes if isinstance(r, APIRoute)]
    keys = Counter((r.path, method) for r in routes for method in r.methods)
    assert [key for key, n in keys.items() if n > 1] == []
    assert routes[-1].name == "unknown_api"
    assert [r.path for r in routes[:3]] == ["/api/settings", "/api/normalize", "/api/health"]
