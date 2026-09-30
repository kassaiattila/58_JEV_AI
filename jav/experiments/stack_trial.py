"""Shared, isolated comparison runner for the existing Burr flows."""
from __future__ import annotations

import json
import hashlib
import sqlite3
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

from jav import store
from jav.adapters.jev import JevAdapter, use_adapter
from jav.experiments.pydantic_jev import run_typed
from jav.config import PROJECT_ROOT


def canonical_state(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


@contextmanager
def trial_services(adapter, store_path: Path):
    with use_adapter(adapter), store.use_store(store_path):
        yield


class DirectAdapter:
    """The same canonical state text on both experimental paths."""
    def __init__(self, base: JevAdapter, *, force_live: bool = False):
        self.base = base
        self.audit = []
        self.force_live = force_live

    @property
    def model(self):
        return self.base.model

    def ask(self, request_id, state, questions, **kwargs):
        text = canonical_state(state)
        if self.force_live:
            kwargs["use_cache"] = False
        result = self.base.ask(request_id, text, questions, **kwargs)
        self.audit.append({"request_id": request_id, "state": text,
                           "questions": {k: q.model_dump(mode="json") for k, q in questions.items()},
                           "response": result.response.model_dump(mode="json"), "cache_key": result.cache_key})
        return result


class TypedAdapter(DirectAdapter):
    """Hands the native Pydantic AI translator's original JEV response to the unchanged flow."""
    def ask(self, request_id, state, questions, *, run_id=None, config_hash=None, use_cache=True, model=None):
        if model is not None and model != self.base.model:
            raise ValueError("A próbában csak a rögzített modell használható")
        result = run_typed(canonical_state(state), questions, adapter=self.base,
                           run_id=run_id or "adhoc", config_hash=config_hash,
                           use_cache=use_cache and not self.force_live, request_id=request_id)
        request = result.requests[0]
        self.audit.append({"request_id": request_id, "state": request["state"],
                           "questions": {k: q.model_dump(mode="json") for k, q in request["questions"].items()},
                           "response": result.calls[0].response.model_dump(mode="json"),
                           "cache_key": result.calls[0].cache_key})
        return result.calls[0]


def run_trial(flow: str, source_path: str, directory: Path, run_id: str, adapter,
              *, doc_type: str = "invoice_hu", halt_after=None, fault=None,
              arm: str = "S", agent_factory=None, generator_identity: str | None = None):
    """Existing graph, SQLite state bound to the run identifier, isolated business store.

    A single-worker experiment, not a distributed work queue. In tests `fault` can interrupt
    the process before a step / after its effect but before the state is saved.
    """
    from burr.core import ApplicationBuilder, State
    from burr.core.persistence import SQLitePersister
    from burr.integrations.pydantic import PydanticTypingSystem
    from burr.lifecycle.base import PreRunStepHook, PostRunStepHook
    from jav import flow as invoice_flow, flow_detect
    from pydantic_core import to_jsonable_python

    if arm not in {'S', 'G'} or (flow != 'invoice' and arm != 'S'):
        raise ValueError('unsupported flow arm')
    if agent_factory is not None and (arm != 'G' or not generator_identity):
        raise ValueError('custom generator requires G arm and explicit identity')
    directory.mkdir(parents=True, exist_ok=True)
    module = {"detect": flow_detect, "invoice": invoice_flow}[flow]
    template = (module.build_app(source_path, tracker=False) if flow == "detect" else
                module.build_app(source_path, case_id=Path(source_path).stem, arm=arm, tracker=False, doc_type=doc_type))
    initial = template.state.data.model_copy(update={"run_id": run_id, "use_cache": True})
    source_hash = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    config_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted((PROJECT_ROOT / "configs").rglob("*.json")))).hexdigest()
    code_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted((PROJECT_ROOT / "jav").rglob("*.py")))).hexdigest()
    identity_data = {"source_hash": source_hash, "source_path": str(Path(source_path).resolve()),
                           "flow": flow, "doc_type": doc_type, "adapter": type(adapter).__name__,
                           "model": adapter.model, "config_hash": config_hash, "code_hash": code_hash}
    if arm == 'G':
        identity_data.update(arm=arm, generator_identity=generator_identity or 'configured-default')
    identity = json.dumps(identity_data, sort_keys=True)
    with sqlite3.connect(directory / "identities.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS identities (run_id TEXT PRIMARY KEY, identity TEXT NOT NULL)")
        db.execute("INSERT OR IGNORE INTO identities VALUES (?,?)", (run_id, identity))
        if db.execute("SELECT identity FROM identities WHERE run_id=?", (run_id,)).fetchone()[0] != identity:
            raise ValueError("run identity changed; use a new run_id")

    class Timing(PreRunStepHook, PostRunStepHook):
        def pre_run_step(self, *, action, **kwargs):
            if fault:
                fault("before_action:" + action.name)
            self.started = time.perf_counter()

        def post_run_step(self, *, action, exception, **kwargs):
            with (directory / "timings.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps({"run_id": run_id, "action": action.name,
                                      "seconds": time.perf_counter()-self.started,
                                      "error": type(exception).__name__ if exception else None}) + "\n")

    class Persister(SQLitePersister):
        def save(self, partition_key, app_id, sequence_id, position, state, status, **kwargs):
            if status == "completed" and fault:
                fault("after_action:" + position)
            # Burr's default Pydantic serialiser dumps in Python mode: date/Decimal are
            # not JSON. Our own, known state schema restores the types on load.
            json_state = State(to_jsonable_python(state.get_all()))
            return super().save(partition_key, app_id, sequence_id, position, json_state, status, **kwargs)

    persister = Persister(str(directory / "burr.sqlite"), serde_kwargs={"allowlist": ["jav.models", "jav.detect"]})
    persister.initialize()
    try:
        saved = persister.load("trial", run_id)
        if saved and saved["status"] == "completed" and saved["position"] in module.TERMINALS:
            return type(initial).model_validate(saved["state"].get_all())
        app = (ApplicationBuilder().with_graph(template.graph)
               .with_typing(PydanticTypingSystem(type(initial)))
               .with_identifiers(app_id=run_id, partition_key="trial")
               .with_hooks(Timing())
               .initialize_from(persister, resume_at_next_action=True,
                                default_state=initial.model_dump(), default_entrypoint="load_pdf")
               .with_state_persister(persister).build())
        from jav.extract_llm import use_agent_factory
        generator_context = use_agent_factory(agent_factory) if agent_factory is not None else nullcontext()
        with trial_services(adapter, directory / "business.sqlite"), generator_context:
            _, _, state = app.run(halt_after=halt_after or module.TERMINALS)
        return state.data
    finally:
        persister.cleanup()
