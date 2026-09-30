"""A régi projekt helye környezeti változóból jön (040, K0)."""

import importlib
from pathlib import Path


def _reload_config(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("JAV_LEGACY_ROOT", raising=False)
    else:
        monkeypatch.setenv("JAV_LEGACY_ROOT", value)
    import jav.config as cfg_mod
    return importlib.reload(cfg_mod)


def test_legacy_root_from_env(monkeypatch, tmp_path):
    cfg = _reload_config(monkeypatch, str(tmp_path))
    try:
        assert cfg.OLD_PROJECT_ROOT == tmp_path
        assert cfg.GOLDEN_MANIFEST == tmp_path / "flows" / "doc-extract-bare" / "golden" / "manifest.json"
    finally:
        _reload_config(monkeypatch, None)


def test_legacy_root_default(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    cfg = _reload_config(monkeypatch, None)
    assert cfg.OLD_PROJECT_ROOT == Path(r"C:\00_DEV_LOCAL\10_AIFLOW_V4")
