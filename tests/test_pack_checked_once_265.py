"""265 (code review APPW-05): with the configs frozen, a process pack is read and checked once.

A case page loaded its process pack seven to ten times, each a full check of the pack and its steps. The service and
the worker freeze their configs at start-up, so a pack cannot change in them: it is now checked once and kept until the
configs are read again. Without the freeze (a command, a test) every load checks the pack as before. No AI.
"""

from __future__ import annotations

from jav.app import process_packs, registrations
from jav.core import cfg


def test_a_frozen_pack_is_checked_once(monkeypatch) -> None:
    registrations.load_all()
    calls = []
    real = process_packs._problems
    monkeypatch.setattr(process_packs, "_problems", lambda pack: calls.append(pack.id) or real(pack))
    pack_id = process_packs.packs()[0].id
    calls.clear()
    process_packs.load(pack_id)
    process_packs.load(pack_id)
    assert calls == [pack_id, pack_id]  # not frozen: checked every time
    cfg.freeze()
    try:
        calls.clear()
        first = process_packs.load(pack_id)
        assert process_packs.load(pack_id) is first and calls == [pack_id]
    finally:
        cfg.unfreeze()
    calls.clear()
    process_packs.load(pack_id)
    assert calls == [pack_id]  # read again after the freeze ends
