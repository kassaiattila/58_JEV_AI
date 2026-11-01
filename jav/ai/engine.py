"""The AI engine: which AI a processing asks (160, plan F-csak-gpt; 265, plan L: the engine as data).

Plain-language summary: an engine says who answers a flow's typed questions (its judgement service: JEV, OpenAI
Decisions, or none, when GPT answers and the code checks), which bands its answers are judged by, and what a run says
when that service cannot be asked. Until 265 the engine was a JEV on/off switch everywhere (`jev: on | off`,
`jev: bool`), so a third engine would have been read as JEV. Now every engine is one entry of `configs/engines.json`,
and the code reads an engine only through this module: `of_params` from a processing setting (the old `jev: on | off`
too), `get` by name, `availability` from the providers it needs.

Processing without a judgement service ("GPT only") stays a guarantee rather than a convention (160): a flow
application built for such an engine runs every step inside `jav.ai.jev.disabled()`, so a typed question asked anyway
(a regression, a new call site that forgot the switch, the native reader's own adapter) is refused before anything
leaves the machine and becomes the `jev_unavailable:disabled` to-do through the flows' usual handling. It covers every
way a flow runs: the worker, the measurements and the tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any

from burr.lifecycle import PostRunStepHook, PreRunStepHook

from jav.ai import jev
from jav.core import cfg, providers

CONFIG = "engines"


class UnknownEngine(ValueError):
    """No engine of the name is in `configs/engines.json`."""


@dataclass(frozen=True)
class Engine:
    """One entry of the engine registry. `judge` is None for an engine without a judgement service."""
    id: str
    label: str
    judge: str | None
    requires: tuple[str, ...]
    bands: str
    unavailable_status: str

    @property
    def judged(self) -> bool:
        """Whether a judgement service answers this engine's typed questions."""
        return self.judge is not None

    def band_key(self, base: str) -> str:
        """The `configs/policy.json` band key of a call site's answers under this engine (`detect.doc_type` ->
        `detect.doc_type.gpt` for GPT only)."""
        return base + self.bands

    @property
    def judge_provider(self) -> str | None:
        """The provider whose calls the judgement service books and budgets."""
        return None if self.judge is None else judge_provider(self.judge)


def _registry() -> dict[str, Any]:
    return cfg.load(CONFIG)


def ids() -> list[str]:
    """Every engine, in the registry's order."""
    return list(_registry()["engines"])


def default_id() -> str:
    return str(_registry()["default"])


def get(engine_id: str) -> Engine:
    try:
        raw = _registry()["engines"][engine_id]
    except KeyError:
        raise UnknownEngine(f"unknown engine {engine_id!r}; expected one of {ids()}") from None
    return Engine(id=engine_id, label=str(raw["label"]), judge=raw["judge"], requires=tuple(raw["requires"]),
                  bands=str(raw["bands"]), unavailable_status=str(raw["unavailable_status"]))


def judges() -> list[str]:
    """Every judgement service an engine may name."""
    return list(_registry()["judges"])


def judge_provider(judge: str) -> str:
    return str(_registry()["judges"][judge]["provider"])


def judge_todo(judge: str) -> str:
    """The first part of the to-do a judgement service raises when it cannot answer (`jev_unavailable`)."""
    return str(_registry()["judges"][judge]["todo"])


def of_params(params: Mapping[str, Any] | None) -> Engine:
    """The engine a processing setting names: its `engine`; a setting saved before the registry (a frozen run's, an old
    package's) names it with the legacy parameter (`jev: on | off`); a setting naming neither runs with the default."""
    params = params or {}
    named = params.get("engine")
    if named is not None:
        return get(str(named))
    legacy = _registry()["legacy"]
    old = params.get(legacy["param"])
    if old is not None:
        try:
            return get(str(legacy["values"][str(old)]))
        except KeyError:
            raise UnknownEngine(f"unknown {legacy['param']} setting {old!r}; expected one of "
                                f"{list(legacy['values'])}") from None
    return get(default_id())


def availability(engine_id: str) -> providers.Availability:
    """Whether the engine can run here: every provider it requires is available (the first one that is not names the
    reason). Nothing is called to find out."""
    for provider_id in get(engine_id).requires:
        state = providers.availability(provider_id)
        if not state.available:
            return state
    return providers.Availability(True)


def choices() -> list[dict[str, Any]]:
    """Every engine with its availability here, in the registry's order (the settings' choices)."""
    out = []
    for engine_id in ids():
        engine, state = get(engine_id), availability(engine_id)
        out.append({"engine": engine_id, "label": engine.label, "available": state.available, "reason": state.reason,
                    "provider": state.provider})
    return out


# --- the guarantee of an engine without a judgement service (160) ---------------------------------------------------

class WithoutJev(PreRunStepHook, PostRunStepHook):
    """Burr hook: each step of the application runs with JEV switched off."""

    def __init__(self) -> None:
        self._open: list[ExitStack] = []

    def pre_run_step(self, **future_kwargs: Any) -> None:
        stack = ExitStack()
        stack.enter_context(jev.disabled())
        self._open.append(stack)

    def post_run_step(self, **future_kwargs: Any) -> None:  # Burr calls it after a failed step too
        self._open.pop().close()


def with_engine(builder, *, jev_on: bool):
    """The flow's application builder, with JEV switched off in every step when `jev_on` is false."""
    return builder if jev_on else builder.with_hooks(WithoutJev())


__all__ = ["Engine", "UnknownEngine", "WithoutJev", "availability", "choices", "default_id", "get", "ids",
           "judge_provider", "judge_todo", "judges", "of_params", "with_engine"]
