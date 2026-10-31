"""265 (code review X-28): a test never reads or writes the real JEV cache.

The JEV cache (`runs/cache/`) holds JEV's answers about real documents. The OCR cache was redirected for every test
(160), the JEV cache was not: an adapter made without a folder took the real one, fixed when the module was loaded,
and the tests left hundreds of files in it. The adapter now reads the folder when it is made, and every test gets an
empty temporary one (`tests/conftest.py`). No AI.
"""

from __future__ import annotations

from jav.ai.jev import JevAdapter
from jav.core.config import RUNS_DIR


def test_an_adapter_made_in_a_test_uses_a_temporary_cache() -> None:
    adapter = JevAdapter(client=object())  # type: ignore[arg-type] (never called)
    assert adapter.cache_dir != RUNS_DIR / "cache" and "jev-cache" in adapter.cache_dir.name
