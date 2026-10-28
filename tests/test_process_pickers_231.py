"""231 (stage U, U3b; the owner's decisions of 2026-10-28: what a process uses is chosen from the shared library): every
resource of every process is chosen from a list, and a step's list holds only what fits it.

Every resource a process pack names offers its values; the insurance processes' letter frame, offer document, send mode
and offer template are resources too (until U3b fixed in their steps). A priced document's output offers only the
outputs that print the version of the step it names (the IT quote's the quote, an insurance offer's the rated offer),
a pack naming an output that does not print its step's version is refused, and a process cannot make such an output its
own value. Real process packs, an empty store; nothing runs.
"""

from __future__ import annotations

import copy
import json
import shutil

import pytest

from jav.app import process_packs, process_settings, registrations
from jav.core import cfg, store
from jav.core.config import PROJECT_ROOT

registrations.load_all()


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "pickers.sqlite"):
        yield tmp_path


def _options(pack_id: str, key: str) -> list[str] | None:
    _label, options = process_settings.resource_info(process_packs.load(pack_id), key)
    return None if options is None else [value for value, _ in options]


def test_every_resource_of_every_process_is_chosen_from_a_list(db) -> None:
    for pack in process_packs.packs():
        for key in pack.resources:
            assert _options(pack.id, key) is not None, f"{pack.id}: {key} has no list to choose from"


@pytest.mark.parametrize("pack_id", ["insurance_offer", "insurance_renewal", "allianz_property_offer"])
def test_an_insurance_process_chooses_its_letter_frame_document_send_mode_and_template(db, pack_id) -> None:
    pack = process_packs.load(pack_id)
    assert {"letter_frame", "offer_output", "send_mode", "template:rated_offer"} <= set(pack.resources)
    assert _options(pack_id, "offer_output") == ["rated_offer"]
    assert "output_folder" in _options(pack_id, "send_mode")
    assert pack.resources["letter_frame"] in _options(pack_id, "letter_frame")


def test_a_priced_document_offers_only_the_outputs_that_print_its_step(db) -> None:
    assert _options("it_quote", "quote_output") == ["quote"]  # Q-kimenet-választék: no rated offer for a quote


def test_a_pack_whose_document_prints_another_step_s_version_is_refused(tmp_path, monkeypatch) -> None:
    configs = tmp_path / "configs"
    shutil.copytree(PROJECT_ROOT / "configs", configs)
    data = copy.deepcopy(json.loads((configs / "processes" / "it_quote.json").read_text(encoding="utf-8")))
    data["resources"]["quote_output"] = "rated_offer"
    (configs / "processes" / "it_quote.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(cfg, "CONFIG_DIR", configs)
    monkeypatch.setattr(cfg, "CALLSITE_DIR", configs / "callsites")
    monkeypatch.setattr(cfg, "TYPES_DIR", configs / "types")
    monkeypatch.setattr(cfg, "PROCESSES_DIR", configs / "processes")
    cfg.reload()
    try:
        with pytest.raises(process_packs.PackError, match="does not print"):
            process_packs.load("it_quote")
    finally:
        cfg.reload()


def test_a_process_cannot_make_an_unfitting_output_its_own(db) -> None:
    with pytest.raises(process_settings.SettingError):
        process_settings.propose("it_quote", "quote_output", "rated_offer", "anna")
