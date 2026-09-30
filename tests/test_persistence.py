"""062 (Q-szál): a lezárt Burr-állapotmentő más szálon is csendben takarítható el (mesterséges adat, AI-hívás nélkül).

A Burr `SQLitePersister.__del__` a `cleanup()` után is újra lezárná a kapcsolatot; ha a szemétgyűjtés egy másik szálon
fut (pl. a helyi szolgáltatás tesztkliensének szálán), az SQLite ezt hibának jelzi. A teljes tesztsorban ez a tanulási
futtatók után a következő teszt figyelmeztetéseként jelent meg."""

import sys
import threading

from burr.core.persistence import SQLitePersister

from jav.runtime.persistence import ClosingSQLitePersister


def _collect_on_other_thread(cls, tmp_path) -> list:
    persister = cls(str(tmp_path / "burr.sqlite"))
    persister.initialize()
    persister.cleanup()
    seen: list = []
    old, sys.unraisablehook = sys.unraisablehook, seen.append
    try:
        box = [persister]
        del persister
        worker = threading.Thread(target=box.clear)
        worker.start()
        worker.join()
    finally:
        sys.unraisablehook = old
    return seen


def test_plain_burr_persister_complains_when_collected_on_another_thread(tmp_path):
    seen = _collect_on_other_thread(SQLitePersister, tmp_path)
    assert seen and "same thread" in str(seen[0].exc_value)  # a hiba forrása (ha a Burr javítja, ez a teszt jelez)


def test_closing_persister_is_collected_silently_on_another_thread(tmp_path):
    assert _collect_on_other_thread(ClosingSQLitePersister, tmp_path) == []


def test_every_runtime_persister_is_the_closing_one():
    from jav import email_learning_runtime, learning_runtime, legacy_runtime, matter_review
    from jav.runtime import worker

    assert issubclass(worker.StatePersister, ClosingSQLitePersister)
    for mod in (email_learning_runtime, learning_runtime, legacy_runtime, matter_review):
        source = open(mod.__file__, encoding="utf-8").read()
        assert "ClosingSQLitePersister" in source and "SQLitePersister" not in source.replace("ClosingSQLitePersister", ""), mod.__name__
