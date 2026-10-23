"""The flows the worker runs, in one registry (173, plan 170 E1).

Plain-language summary: a flow is one kind of processing of an item (an invoice's data points, a document's type, an
email's intent, an unknown document's facts, a bank table). Until now the list of flows was written out by hand in four
places: the worker's map and its way of building each flow, the contract lint, and the run's plan and budget. Now each
flow has one entry here, and those places read it. Nothing else changes: every run keeps its flow's name in its
frozen recipe, so the names stay exactly as they are.

An entry (`FlowSpec`) names the module that holds the flow, how the worker builds its graph for one item (`build`; a
flow made of stages has none), how the contract lint builds a graph to compare with the contract
(`lint`), whether the flow takes its budget and path from the native reader's estimate (`native`), where an item's
document type is known before the run (`doc_type`: the recipe's settings or an earlier detection), and, for a recipe
flow made of stages, its stages in order (`stages`).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


class UnknownFlow(KeyError):
    """No flow is registered under the name."""


@dataclass(frozen=True)
class Build:
    """What the worker hands a flow to build its graph for one item. `read_path`: where a document's bytes are read
    from (its source instance); `attachment_reads`: for an email, the source instances of its attachments that are
    items of the package; `jev` and `use_cache`: the run's JEV switch and its earlier-answers setting."""
    params: dict[str, Any]
    source_path: str
    app_id: str
    persister: Any
    jev: bool
    use_cache: bool
    read_path: str | None = None
    attachment_reads: dict[str, str] | None = None
    run_id: str | None = None
    item: dict[str, Any] | None = None
    recipe_hash: str | None = None


@dataclass(frozen=True)
class FlowSpec:
    name: str
    module: str | None = None
    build: Callable[[ModuleType, Build], Any] | None = None
    lint: Callable[[ModuleType], Any] | None = None
    native: bool = False
    doc_type: str | None = None  # "params": the recipe's `doc_type`; "detected": an earlier detection of the document
    stages: tuple[str, ...] = ()

    def load(self) -> ModuleType:
        if self.module is None:
            raise UnknownFlow(f"{self.name} is made of stages, it has no module of its own")
        return importlib.import_module(self.module)


_FLOWS: dict[str, FlowSpec] = {}


def register(spec: FlowSpec) -> None:
    if spec.name in _FLOWS:
        raise ValueError(f"flow {spec.name} is registered twice")
    _FLOWS[spec.name] = spec


def get(name: str) -> FlowSpec:
    try:
        return _FLOWS[name]
    except KeyError:
        raise UnknownFlow(f"no flow is registered as {name!r}") from None


def specs() -> list[FlowSpec]:
    """Every registered flow, in registration order (the order the contract lint reports them in)."""
    return list(_FLOWS.values())


# --- how each flow is built ---------------------------------------------------------------------------------------

def _build_extraction(mod: ModuleType, b: Build) -> Any:
    # `jev_cache=live` (use_cache False): skip reading the JEV cache so every call goes through the log and the budget
    return mod.build_app(b.source_path, b.app_id, b.params["arm"], tracker=False, doc_type=b.params["doc_type"],
                         run_id=b.app_id, persister=b.persister, use_cache=b.use_cache, read_path=b.read_path,
                         jev=b.jev, detail_probabilities=b.params.get("detail_probabilities"),
                         source_text=b.params.get("source_text"))  # 190: a follow-up on an email's own text


def _build_detect(mod: ModuleType, b: Build) -> Any:
    return mod.build_app(b.source_path, tracker=False, run_id=b.app_id, persister=b.persister, use_cache=b.use_cache,
                         read_path=b.read_path, jev=b.jev)


def _build_email(mod: ModuleType, b: Build) -> Any:
    # 048 T2: the item is the email's `message.json`; the flow reads its folder
    return mod.build_app(source_dir=str(Path(b.source_path).parent), tracker=False, run_id=b.app_id,
                         persister=b.persister, use_cache=b.use_cache, propose_tasks=b.params.get("tasks") == "propose",
                         attachment_reads=b.attachment_reads, jev=b.jev,
                         extract_text=b.params.get("email_text") == "extract")  # 190: a run before the setting: off


def _build_native(mod: ModuleType, b: Build) -> Any:
    if b.run_id is None or b.item is None or b.recipe_hash is None:
        raise ValueError("Native processing requires the frozen run and item identities")
    from jav.ai.native_processing import estimate_limits

    return mod.build_app(work_run_id=b.run_id, item_id=b.item["item_id"], graph_id=b.app_id,
                         source_path=b.source_path, read_path=b.read_path or b.source_path,
                         original_name=Path(b.source_path).name, expected_sha256=b.item["sha256"],
                         recipe_hash=b.recipe_hash, jev=b.jev, use_cache=b.use_cache,
                         requested_arm=b.params.get("arm", "auto"), persister=b.persister, tracker=False,
                         limits=estimate_limits(b.params), ocr=bool(b.params.get("native_ocr")),
                         recognition=b.params.get("native_recognition"))


def _build_statement_table(mod: ModuleType, b: Build) -> Any:
    # 136: an account's statement from a tabular export, code only
    if b.item is None:
        raise ValueError("A statement table requires the frozen item identity")
    return mod.build_app(run_id=b.app_id, item_id=b.item["item_id"], source_path=b.source_path,
                         read_path=b.read_path or b.source_path, expected_sha256=b.item["sha256"], persister=b.persister)


# --- the graphs the contract lint compares with each contract ------------------------------------------------------

def _lint_native(mod: ModuleType) -> Any:
    return mod.build_app(work_run_id="lint-native-run", item_id="0" * 64, graph_id="lint-native-graph",
                         source_path="lint.txt", read_path="lint.txt", original_name="lint.txt",
                         expected_sha256="0" * 64, recipe_hash="0" * 16, jev=False)


def _lint_statement_table(mod: ModuleType) -> Any:
    return mod.build_app(run_id="lint-statement-table", item_id="0" * 64, source_path="lint.json",
                         read_path="lint.json", expected_sha256="0" * 64)


register(FlowSpec("invoice", "jav.flow", _build_extraction, lambda m: m.build_app("lint.pdf", "lint", "S", tracker=False, doc_type="invoice_hu"),
                  doc_type="params"))
register(FlowSpec("doc_detect", "jav.flow_detect", _build_detect, lambda m: m.build_app("lint.pdf", tracker=False)))
register(FlowSpec("email", "jav.domains.email.flow_email", _build_email, lambda m: m.build_app(source_dir="lint", tracker=False)))
register(FlowSpec("native", "jav.flow_native", _build_native, _lint_native, native=True))
register(FlowSpec("statement_table", "jav.domains.finance.flow_statement_table", _build_statement_table, _lint_statement_table))
# 047 T1.3: the `document` recipe flow: detection, then extraction of the detected detailed type (worker `_stages`)
register(FlowSpec("document", stages=("doc_detect", "invoice"), doc_type="detected"))
