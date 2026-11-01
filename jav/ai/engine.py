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

import importlib
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from burr.lifecycle import PostRunStepHook, PreRunStepHook
from pydantic import AfterValidator

from jav.ai import jev
from jav.core import cfg, providers

CONFIG = "engines"
# The adapter of each judgement service (code: the mechanism; `configs/engines.json` `judges`: what an engine names).
JUDGE_ADAPTERS: dict[str, tuple[str, str]] = {
    "jev": ("jav.ai.jev", "JevAdapter"),
    "decisions": ("jav.ai.decisions", "DecisionsAdapter"),
}


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
    runs: str = ""  # the suffix of its measurements' run files

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

    @property
    def answerer(self) -> str:
        """The provider whose calls answer the typed questions: the judgement service's, or, for an engine without one,
        the provider it requires first (GPT's), so a measurement of the answers knows whose budget it spends."""
        return self.judge_provider if self.judge is not None else self.requires[0]


def _registry() -> dict[str, Any]:
    return cfg.load(CONFIG)


def ids() -> list[str]:
    """Every engine, in the registry's order."""
    return list(_registry()["engines"])


def default_id() -> str:
    return str(_registry()["default"])


def installation_default() -> str:
    """The engine of this installation while nothing is saved (265; the owner's decision of 2026-11-01): the registry's
    default where it can run, else the first of its `fallback` that can (without a JEV key: GPT only), else the default
    itself, whose unavailability then names the reason. Nothing is called to find out."""
    for engine_id in (default_id(), *_registry().get("fallback", [])):
        if availability(engine_id).available:
            return str(engine_id)
    return default_id()


def check_id(engine_id: str) -> str:
    """The name itself when the registry has such an engine (a request field's check, `EngineId`)."""
    if engine_id not in ids():
        raise ValueError(f"unknown engine {engine_id!r}; expected one of {ids()}")
    return engine_id


# A field holding an engine's name: any engine of the registry (until 265 `Literal["jev", "gpt"]`).
EngineId = Annotated[str, AfterValidator(check_id)]


def get(engine_id: str) -> Engine:
    try:
        raw = _registry()["engines"][engine_id]
    except KeyError:
        raise UnknownEngine(f"unknown engine {engine_id!r}; expected one of {ids()}") from None
    return Engine(id=engine_id, label=str(raw["label"]), judge=raw["judge"], requires=tuple(raw["requires"]),
                  bands=str(raw["bands"]), unavailable_status=str(raw["unavailable_status"]), runs=str(raw.get("runs", "")))


def judges() -> list[str]:
    """Every judgement service an engine may name."""
    return list(_registry()["judges"])


def judge_provider(judge: str) -> str:
    return str(_registry()["judges"][judge]["provider"])


def judge_adapter(judge: str) -> type:
    """The adapter class of a judgement service."""
    try:
        module, name = JUDGE_ADAPTERS[judge]
    except KeyError:
        raise UnknownEngine(f"no adapter for the judgement service {judge!r}; expected one of {list(JUDGE_ADAPTERS)}") from None
    return getattr(importlib.import_module(module), name)


def judge_todo(judge: str) -> str:
    """The first part of the to-do a judgement service raises when it cannot answer (`jev_unavailable`)."""
    return str(_registry()["judges"][judge]["todo"])


def unavailable_todo(exc: jev.JevUnavailableError) -> str:
    """The to-do of a typed question the context's judgement service could not answer: `<its todo>:<reason>`
    (`jev_unavailable:budget_exceeded`, `decisions_unavailable:refusal`)."""
    return f"{judge_todo(jev.current_judge())}:{exc.reason}"


def unavailable_prefixes() -> tuple[str, ...]:
    """The first parts of every judgement service's unavailable to-do, with their colon (`jev_unavailable:`, ...)."""
    return tuple(f"{judge_todo(j)}:" for j in judges())


def unavailable_statuses() -> tuple[str, ...]:
    """Every engine's end state of a flow whose answerer could not be asked (`jev_unavailable`, ...)."""
    return tuple(get(e).unavailable_status for e in ids())


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


def legacy_param() -> str:
    """The setting that named the engine before the registry (the recipes' `jev: on | off`)."""
    return str(_registry()["legacy"]["param"])


def of_flag(flag: Any) -> str:
    """The engine a flow state or a recorded decision saved before 265 names with its JEV switch (`jev`: True or
    False), by the registry's legacy reading (`legacy.values`: on, off)."""
    legacy = _registry()["legacy"]["values"]
    return str(legacy["on" if flag else "off"])


def of_record(data: Mapping[str, Any]) -> Engine:
    """The engine a flow state's values or a decision's recorded inputs name: their `engine`, or, recorded before 265,
    their JEV switch (`jev`)."""
    if data.get("engine") is not None:
        return get(str(data["engine"]))
    return get(of_flag(data.get("jev", True)))


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
                    "provider": state.provider, "judge_provider": engine.judge_provider})
    return out


# --- every step asks the engine's judgement service; without one, nothing is asked (160) --------------------------

def resolve(engine: Engine | str) -> Engine:
    return engine if isinstance(engine, Engine) else get(engine)


@contextmanager
def scope(engine: Engine | str) -> Iterator[Engine]:
    """Inside, the typed questions go to the engine's judgement service; for an engine without one they are refused
    before anything leaves the machine (`jav.ai.jev.disabled()`)."""
    e = resolve(engine)
    with (jev.use_judge(e.judge) if e.judge is not None else jev.disabled()):
        yield e


@contextmanager
def no_cache_write(engine: Engine | str) -> Iterator[Engine]:
    """Inside, the engine's judgement service neither reads nor writes its saved answers (a determinism measurement:
    the real run-to-run variation, the reference answers untouched); an engine without one has none to keep."""
    e = resolve(engine)
    if e.judge is None:
        yield e
        return
    with jev.use_judge(e.judge):
        adapter = jev.get_adapter()
    with adapter.no_cache_write():
        yield e


class WithEngine(PreRunStepHook, PostRunStepHook):
    """Burr hook: each step of the application runs in the engine's scope (`scope`)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._open: list[ExitStack] = []

    def pre_run_step(self, **future_kwargs: Any) -> None:
        stack = ExitStack()
        stack.enter_context(scope(self.engine))
        self._open.append(stack)

    def post_run_step(self, **future_kwargs: Any) -> None:  # Burr calls it after a failed step too
        self._open.pop().close()


def with_engine(builder, engine: Engine | str):
    """The flow's application builder, every step in the engine's scope."""
    return builder.with_hooks(WithEngine(resolve(engine)))


__all__ = ["Engine", "EngineId", "JUDGE_ADAPTERS", "UnknownEngine", "WithEngine", "availability", "check_id", "choices",
           "default_id", "get", "ids", "installation_default", "judge_adapter", "legacy_param", "judge_provider", "judge_todo", "judges", "no_cache_write", "of_flag", "of_params",
           "of_record", "resolve", "scope", "unavailable_prefixes", "unavailable_statuses", "unavailable_todo",
           "with_engine"]
