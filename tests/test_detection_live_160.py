"""160 (review AI-4): with "ask every question again" (`jev_cache=live`), the type detection asks again too.

The setting reached the extraction stage only; the detection stage of a document run still read the JEV cache, so a
live trial showed no detection cost and hid a model change (the decision of 090 said every path). Synthetic document,
fake JEV client."""

from pathlib import Path

from jav import work, work_readiness, work_recipes, work_runs
from jav.core import store
from jav.adapters import jev as jev_mod
from jav.runtime import worker
from tests.pdfgen import write_text_pdf
from tests.test_no_type_pack_069 import REMINDER_LINES, ReminderClient


class CountingClient(ReminderClient):
    def __init__(self):
        self.detections = 0

    def system_one(self, *, state, questions, model):
        self.detections += "doc_type" in questions
        return super().system_one(state=state, questions=questions, model=model)


def _run(folder: Path, name: str, jev_cache: str) -> None:
    wp = work.create_from_folder(folder, name=name)
    work_recipes.assign_recipe(wp["id"], "processing", params={"arm": "S", "unknown_documents": "review", "jev_cache": jev_cache},
                       expected_revision=0, actor="t")
    r = work_readiness.readiness(wp["id"])
    work_runs.start_run(wp["id"], mode="apply", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")
    assert worker.run_worker(once=True)["results"] == {"done": 1}


def test_a_live_run_asks_the_type_detection_again(tmp_path):
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
        write_text_pdf(tmp_path / name / "felszolitas.pdf", REMINDER_LINES)  # read from its text layer, without OCR
    client = CountingClient()
    adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        _run(tmp_path / "first", "First", "reuse")
        assert client.detections == 1
        _run(tmp_path / "second", "Second", "live")
    assert client.detections == 2
