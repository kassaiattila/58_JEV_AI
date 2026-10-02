"""091 (an incident of 2026-10-02): the worker imported its flows only at the first item, and a flow module changed on
disk since its start (development in the same working tree) was loaded against the data model already in memory;
every item of four runs failed at that import (no paid call). The worker and the local service now load all their
code when they start, so a running process is one consistent state of the code it started from.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from jav import store
from jav.runtime import preload, worker


def test_preload_imports_the_runtime_code_but_not_the_experiments():
    loaded = preload.preload()
    for name in ("jav.flow", "jav.flow_detect", "jav.flow_email", "jav.extract_llm", "jav.token_confidence", "jav.grounding"):
        assert name in loaded and name in sys.modules
    assert not any(m.startswith("jav.experiments") for m in loaded)


def test_a_module_that_fails_to_import_stops_the_start(monkeypatch):
    real = preload.importlib.import_module

    def broken(name: str):
        if name == "jav.grounding":
            raise ValueError("a broken module")
        return real(name)

    monkeypatch.setattr(preload.importlib, "import_module", broken)
    with pytest.raises(preload.PreloadError, match="jav.grounding"):
        preload.preload()


def test_the_worker_preloads_before_its_first_item(tmp_path: Path, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(preload, "preload", lambda: seen.append("preload") or [])
    with store.use_store(tmp_path / "w.sqlite"):
        info = worker.run_worker(once=True)
    assert seen == ["preload"] and info["processed"] == 0


def test_the_service_preloads_before_it_serves(monkeypatch):
    import uvicorn

    from jav import api

    order: list[str] = []
    monkeypatch.setattr(preload, "preload", lambda: order.append("preload") or [])
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: order.append("serve"))
    monkeypatch.setattr(api, "create_app", lambda *a, **k: object())
    api.serve()
    assert order == ["preload", "serve"]
