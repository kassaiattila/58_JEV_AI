"""199 (plan 197 K2d): a type pack's detection switch, turned only by the person's command.

A taught candidate is turned on only with a clean, complete measurement of its evaluation half on the files it has
now; with `--replace`, its family's old pack is turned off and keeps its files. Withdrawal turns detection off and
keeps the files for the earlier results; `--restore` turns the replaced pack back on. Detection follows the switch:
the family's question offers the packs that are on. Every switch is a new version with a changelog line, in the
pack's own layout; a refusal writes nothing. The packs are copies in a temporary folder; no AI call."""

import json
import shutil
from datetime import date

import pytest

from jav import cfg, cli, detect_detail, goldens, type_teaching, typepack

KEY, OLD = "belepo_jegy_taught", "belepo_jegy"
MEASURED = {f"taught:{KEY}:evaluation": {
    "key": f"taught:{KEY}:evaluation", "cases": 5, "answered": 5, "without_result": 0, "right": 40, "scored": 40,
    "unit": "fields", "receipt": "20261022_081601_measure.jsonl", "commit": "d5adfe8", "clean": True, "engine": "jev"}}
DAY = date(2026, 10, 22)


@pytest.fixture
def packs(tmp_path, monkeypatch):
    folder = tmp_path / "types"
    shutil.copytree(cfg.TYPES_DIR, folder)
    monkeypatch.setattr(cfg, "TYPES_DIR", folder)
    cfg.reload()
    typepack.reload()
    yield folder
    monkeypatch.undo()
    cfg.reload()
    typepack.reload()


def _unchanged(commit, key):
    """The candidate's files at the measured commit: as they are now."""
    return type_teaching.files_now(key)


def _pack(folder, key):
    return json.loads((folder / f"{key}.json").read_text(encoding="utf-8"))


def _texts(folder):
    return {p.name: p.read_text(encoding="utf-8") for p in folder.glob("*.json")}


def test_a_measured_candidate_replaces_the_old_pack_and_detection_follows(packs):
    before = type_teaching.content_digest(type_teaching.files_now(KEY))
    assert detect_detail.candidates("ticket") == [OLD]
    switched = type_teaching.activate(KEY, replace=OLD, latest=MEASURED, files_then=_unchanged, today=DAY)
    assert switched == [type_teaching.Switch(KEY, "0.2.0", True), type_teaching.Switch(OLD, "1.1.0", False)]
    assert detect_detail.candidates("ticket") == [KEY]
    new, old = _pack(packs, KEY), _pack(packs, OLD)
    assert new["auto_detect"] is True and old["auto_detect"] is False
    assert new["meta"]["taught"]["state"] == "active" and new["meta"]["taught"]["replaces"] == OLD
    assert new["meta"]["taught"]["measured"] == {"receipt": "20261022_081601_measure.jsonl", "commit": "d5adfe8",
                                                 "right": 40, "scored": 40, "unit": "fields"}
    note = new["meta"]["changelog"][-1]
    assert (note["version"], note["date"]) == ("0.2.0", "2026-10-22") and "40/40 fields" in note["note"]
    assert f"replaced by {KEY}" in old["meta"]["changelog"][-1]["note"] and old["fields"] == new["fields"]
    for key, data in ((KEY, new), (OLD, old)):  # each pack keeps its own layout
        assert (packs / f"{key}.json").read_text(encoding="utf-8") == json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    # the switch changes neither what was measured nor the requests: the same files apart from the version records
    assert type_teaching.content_digest(type_teaching.files_now(KEY)) == before


def test_withdrawal_keeps_the_files_and_restore_turns_the_replaced_pack_back_on(packs):
    type_teaching.activate(KEY, replace=OLD, latest=MEASURED, files_then=_unchanged, today=DAY)
    assert type_teaching.withdraw(KEY, today=DAY) == [type_teaching.Switch(KEY, "0.3.0", False)]
    assert detect_detail.candidates("ticket") == []  # no pack on in the family: the general data proposal
    assert _pack(packs, KEY)["meta"]["taught"]["state"] == "withdrawn" and (packs / f"{KEY}.json").exists()
    # turned on again: the measured files have not changed, only the version records
    type_teaching.activate(KEY, latest=MEASURED, files_then=_unchanged, today=DAY)
    assert detect_detail.candidates("ticket") == [KEY] and "replaces" not in _pack(packs, KEY)["meta"]["taught"]
    with pytest.raises(type_teaching.TeachingError, match="replaced no pack"):
        type_teaching.withdraw(KEY, restore=True)
    type_teaching.withdraw(KEY, today=DAY)
    type_teaching.activate(KEY, replace=None, latest=MEASURED, files_then=_unchanged, today=DAY)
    type_teaching.withdraw(KEY, today=DAY)
    # the usual way back: the old pack on again by its own command, without a measurement gate (it was never taught)
    assert type_teaching.activate(OLD, today=DAY) == [type_teaching.Switch(OLD, "1.2.0", True)]
    assert detect_detail.candidates("ticket") == [OLD]


def test_restore_turns_the_replaced_pack_on_in_the_same_step(packs):
    type_teaching.activate(KEY, replace=OLD, latest=MEASURED, files_then=_unchanged, today=DAY)
    switched = type_teaching.withdraw(KEY, restore=True, today=DAY)
    assert switched == [type_teaching.Switch(KEY, "0.3.0", False), type_teaching.Switch(OLD, "1.2.0", True)]
    assert detect_detail.candidates("ticket") == [OLD] and "replaces" not in _pack(packs, KEY)["meta"]["taught"]


@pytest.mark.parametrize(("latest", "files_then", "reason"), [
    ({}, _unchanged, "never measured"),
    ({k: {**v, "clean": False} for k, v in MEASURED.items()}, _unchanged, "uncommitted"),
    ({k: {**v, "answered": 4} for k, v in MEASURED.items()}, _unchanged, "every case"),
    ({k: {**v, "without_result": 1} for k, v in MEASURED.items()}, _unchanged, "every case"),
    (MEASURED, lambda commit, key: {**type_teaching.files_now(key), "prompt": "another prompt"}, "changed since"),
    (MEASURED, lambda commit, key: None, "changed since"),
])
def test_a_candidate_without_a_clean_complete_measurement_of_its_files_stays_off(packs, latest, files_then, reason):
    before = _texts(packs)
    with pytest.raises(type_teaching.TeachingError, match=reason):
        type_teaching.activate(KEY, replace=OLD, latest=latest, files_then=files_then)
    assert _texts(packs) == before and detect_detail.candidates("ticket") == [OLD]


@pytest.mark.parametrize(("key", "replace", "reason"), [
    ("no_such_type", None, "no type pack"),
    (OLD, None, "picks it already"),
    ("invoice_hu", None, "category's own pack"),         # its detection is the type registry's
    ("statement_table", None, "read by code only"),
    (KEY, KEY, "itself"),
    (KEY, "statement_cib", "family"),                    # another family's pack
    (KEY, "meghivo", "does not pick it"),                # nothing to replace
    (KEY, None, "no detection anchors"),                 # next to the old pack: the anchor score would pick it blind
])
def test_a_switch_that_cannot_be_made_as_asked_writes_nothing(packs, key, replace, reason):
    before = _texts(packs)
    with pytest.raises(type_teaching.TeachingError, match=reason):
        type_teaching.activate(key, replace=replace, latest=MEASURED, files_then=_unchanged)
    assert _texts(packs) == before


def test_withdrawing_a_pack_detection_does_not_pick_is_refused(packs):
    with pytest.raises(type_teaching.TeachingError, match="does not pick it"):
        type_teaching.withdraw(KEY)


def test_the_commands_switch_and_refuse(packs, monkeypatch, capsys):
    monkeypatch.setattr(goldens, "latest_results", lambda runs_dir=None: MEASURED)
    monkeypatch.setattr(type_teaching, "files_at", _unchanged)
    assert cli.main(["type-withdraw", KEY]) == 2
    assert cli.main(["type-activate", KEY, "--replace", OLD]) == 0
    out = capsys.readouterr().out
    assert f"{KEY} 0.2.0: on" in out and f"{OLD} 1.1.0: off" in out and "40/40 fields" in out
    assert cli.main(["type-withdraw", KEY, "--restore"]) == 0
    assert detect_detail.candidates("ticket") == [OLD]
