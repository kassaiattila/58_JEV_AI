"""Load all the application's code when a long-running process starts (091, an incident of 2026-10-02).

The worker imported its flows only at the first item (they pull in heavy dependencies), and several steps import
their modules inside the function. A module changed on disk after the process started (development in the same
working tree) was then loaded against the code already in memory: every item of four runs failed at that import. The
worker and the local service call `preload()` at start-up, so a running process is one consistent state of the code
it started from; a module that cannot be imported stops the start instead of failing every item later. The three
stand-alone measurement tools are never loaded: the runtime does not use them (until 208 `jav.experiments`).

218: after the code, the process takes its calculation snapshot (`jav.core.rulebook.current`): every config is loaded
then, so the rules the process uses are the ones its runs, items and cases are linked to.

231 (an incident of 2026-10-25): every config read then was kept, but the list of them was read anew on every request,
and a cleared cache read the folder again, so a process pack that appeared in the folder later (the development
branch's) reached the released code. The configs are frozen at start-up too (`cfg.freeze`): their list and contents.
"""

from __future__ import annotations

import importlib
import pkgutil

import jav

# the stand-alone measurement tools (208: in jav/evals/, until then jav/experiments/); the engine matrix skips them too
EXCLUDED = ("jav.evals.jev_estimate", "jav.evals.extract_cases", "jav.evals.document_injection_probe")


class PreloadError(RuntimeError):
    """A module of the application could not be imported at start-up."""


def preload() -> list[str]:
    """Imports every module of the `jav` package except the excluded ones and freezes the configs (231); returns the
    modules' names."""
    loaded = _import_all()
    from jav.core import cfg, rulebook, store

    cfg.freeze()  # 231: the configs of this moment, whatever the folder holds later
    with store.connect() as c:  # stage D (D-a): every version of the configs a process ran with is kept, so a key added
        store.begin_immediate(c)  # after a case started takes the value it came with (`rulebook.later_in`)
        rulebook.store_in(c, rulebook.current())
    return loaded


def _import_all() -> list[str]:
    loaded: list[str] = []
    for info in pkgutil.walk_packages(jav.__path__, "jav."):
        if info.name.startswith(EXCLUDED):
            continue
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # the start stops with the module's name; the cause is chained
            raise PreloadError(f"{info.name} could not be imported at start-up: {type(exc).__name__}: {exc}") from exc
        loaded.append(info.name)
    return loaded


__all__ = ["EXCLUDED", "PreloadError", "preload"]
