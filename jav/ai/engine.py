"""The AI engine setting (160, plan F-csak-gpt): JEV and GPT (the default) or GPT only.

Processing without JEV ("GPT only") is a run setting since 086 (the recipes' `jev: off`); each flow takes it as
`jev=False` and routes its questions to GPT and to the code's own checks. This module makes that a guarantee rather
than a convention: a flow application built without JEV runs every step inside `jav.ai.jev.disabled()`, so a JEV
question asked anyway (a regression, a new call site that forgot the switch, the native reader's own adapter) is
refused before anything leaves the machine and becomes the `jev_unavailable:disabled` to-do through the flows' usual
handling. It covers every way a flow runs: the worker, the measurements and the tests.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

from burr.lifecycle import PostRunStepHook, PreRunStepHook

from jav.ai import jev


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
