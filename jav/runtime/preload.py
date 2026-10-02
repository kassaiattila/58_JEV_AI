"""Load all the application's code when a long-running process starts (091, an incident of 2026-10-02).

The worker imported its flows only at the first item (they pull in heavy dependencies), and several steps import
their modules inside the function. A module changed on disk after the process started (development in the same
working tree) was then loaded against the code already in memory: every item of four runs failed at that import. The
worker and the local service call `preload()` at start-up, so a running process is one consistent state of the code
it started from; a module that cannot be imported stops the start instead of failing every item later. Experimental
code (`jav.experiments`) is never loaded: the runtime does not use it.
"""

from __future__ import annotations

import importlib
import pkgutil

import jav

EXCLUDED = ("jav.experiments",)


class PreloadError(RuntimeError):
    """A module of the application could not be imported at start-up."""


def preload() -> list[str]:
    """Imports every module of the `jav` package except the excluded ones; returns their names."""
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
