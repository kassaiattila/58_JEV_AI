"""A state saved before a module moved is read back with the class at its new place (208, plan G-process-core R2).

Plain-language summary: the worker saves an item's state after every step, so that an interrupted item resumes where
it stopped. A saved state names each typed value's class by the module it lived in. When the code goes into folders,
those modules move; the state persister reads an old name at its new place (`MOVED_MODULES`), so an item interrupted
before the move resumes as it was. Synthetic data, no AI call.
"""

from __future__ import annotations

import importlib
import json

from burr.core import State

from jav.domains.email.emails import Attachment, EmailMessage
from jav.flows.persistence import MOVED_MODULES, ClosingSQLitePersister
from jav.core.config import PROJECT_ROOT


def _saved_under_old_names(tmp_path, state: State) -> ClosingSQLitePersister:
    """A persister whose one saved state names its classes by their modules before the move."""
    persister = ClosingSQLitePersister(str(tmp_path / "burr.sqlite"))
    persister.initialize()
    persister.save("email", "run-1:item", 0, "intent", state, "completed")
    text = persister.connection.execute("SELECT state FROM burr_state").fetchone()[0]
    for old, new in MOVED_MODULES.items():
        text = text.replace(f'"jav.{new}.', f'"jav.{old}.')
    persister.connection.execute("UPDATE burr_state SET state = ?", (text,))
    persister.connection.commit()
    return persister


def test_a_state_saved_before_the_move_is_read_with_the_new_classes(tmp_path):
    message = EmailMessage(message_id="m-1", subject="Invented subject",
                           attachments=[Attachment(filename="invented.pdf", path="invented.pdf")])
    persister = _saved_under_old_names(tmp_path, State({"message": message, "messages": [message], "count": 1}))
    saved = persister.connection.execute("SELECT state FROM burr_state").fetchone()[0]
    assert '"__pydantic_class": "jav.emails.EmailMessage"' in saved  # as a state saved before 208 names it
    loaded = persister.load("email", "run-1:item")["state"]
    persister.cleanup()
    assert loaded["message"] == message and isinstance(loaded["message"], EmailMessage)
    assert loaded["messages"] == [message] and loaded["count"] == 1


def test_a_state_saved_after_the_move_reads_as_before(tmp_path):
    persister = ClosingSQLitePersister(str(tmp_path / "burr.sqlite"))
    persister.initialize()
    message = EmailMessage(message_id="m-2")
    persister.save("email", "run-2:item", 0, "intent", State({"message": message}), "completed")
    assert json.loads(persister.connection.execute("SELECT state FROM burr_state").fetchone()[0])["message"][
        "__pydantic_class"] == "jav.domains.email.emails.EmailMessage"
    assert persister.load("email", "run-2:item")["state"]["message"] == message
    persister.cleanup()


def test_every_moved_module_is_gone_from_its_old_place_and_imports_at_its_new_one():
    for old, new in MOVED_MODULES.items():
        assert not (PROJECT_ROOT / "jav" / (old.replace(".", "/") + ".py")).exists(), old
        importlib.import_module(f"jav.{new}")


def test_a_stored_format_name_does_not_follow_its_module():
    """A statement file names its format in the file itself (133 statement files and 200 source copies in the store,
    208); the name looks like the reader's old module path but is a stored name, so it never follows a move."""
    from jav.domains.finance import statement_original, statement_table

    assert statement_table.FORMAT == statement_original.FORMAT == "jav.statement_table"


def test_a_moved_class_is_read_at_its_new_place(tmp_path):
    """209 (plan G-process-core R2d): the page layout's classes left the data model for the documents layer. A state
    saved naming one at either earlier place (`jav.models` before 208, `jav.ai.models` on the branch since) is read
    with the class at its new one (`MOVED_CLASSES`); the store held about 332,000 saved lines of layout in 208."""
    from jav.documents.layout import CellLayout, LineLayout

    line = LineLayout(no=1, page=1, text="Invented line", cells=[CellLayout(text="Invented line", x0=1.0, x1=2.0)])
    persister = ClosingSQLitePersister(str(tmp_path / "burr.sqlite"))
    persister.initialize()
    for n, old in enumerate(("jav.models", "jav.ai.models", "jav.documents.layout")):
        persister.save("doc_detect", f"run-{n}:item", 0, "detect", State({"layout": [line]}), "completed")
        text = persister.connection.execute("SELECT state FROM burr_state WHERE app_id = ?", (f"run-{n}:item",)).fetchone()[0]
        assert '"__pydantic_class": "jav.documents.layout.LineLayout"' in text
        persister.connection.execute("UPDATE burr_state SET state = ? WHERE app_id = ?",
                                     (text.replace('"jav.documents.layout.', f'"{old}.'), f"run-{n}:item"))
        persister.connection.commit()
        loaded = persister.load("doc_detect", f"run-{n}:item")["state"]
        assert loaded["layout"] == [line] and isinstance(loaded["layout"][0], LineLayout), old
    persister.cleanup()


def test_every_moved_class_is_gone_from_its_old_module_and_lives_at_its_new_one():
    from jav.flows.persistence import MOVED_CLASSES

    for (old, name), new in MOVED_CLASSES.items():
        moved = getattr(importlib.import_module(f"jav.{new}"), name)
        assert moved.__module__ == f"jav.{new}", (new, name)
        # the old module may still use it (the flow state holds its lines), but defines none of its own
        assert getattr(importlib.import_module(f"jav.{MOVED_MODULES.get(old, old)}"), name, moved) is moved, (old, name)


def test_a_renamed_class_is_read_under_its_new_name(tmp_path):
    """227 (backlog Q-old-state-InvoiceHU, plan R3a): the record of a document's data points was named `InvoiceHU`
    until 188, in `jav.models`; a state saved naming it so is read as the `DocumentRecord` of the AI layer
    (`RENAMED_CLASSES`; the fields are the same). 2 774 saved states of the store named it so in 208."""
    from jav.ai.models import DocumentRecord, LineItem

    record = DocumentRecord(supplier_name="Invented Kft.", currency="HUF", extra={"note": "invented"},
                            line_items=[LineItem(description="Invented line", unit="db")])
    persister = ClosingSQLitePersister(str(tmp_path / "burr.sqlite"))
    persister.initialize()
    persister.save("invoice", "run-1:item", 0, "extract", State({"record": record}), "completed")
    text = persister.connection.execute("SELECT state FROM burr_state").fetchone()[0]
    assert '"__pydantic_class": "jav.ai.models.DocumentRecord"' in text
    old = text.replace('"jav.ai.models.DocumentRecord"', '"jav.models.InvoiceHU"').replace('"jav.ai.models.', '"jav.models.')
    persister.connection.execute("UPDATE burr_state SET state = ?", (old,))
    persister.connection.commit()
    loaded = persister.load("invoice", "run-1:item")["state"]
    persister.cleanup()
    assert isinstance(loaded["record"], DocumentRecord) and loaded["record"] == record


def test_every_renamed_class_lives_under_its_new_name_and_not_its_old_one():
    from jav.flows.persistence import RENAMED_CLASSES

    for (old, name), (new, new_name) in RENAMED_CLASSES.items():
        moved = getattr(importlib.import_module(f"jav.{new}"), new_name)
        assert moved.__module__ == f"jav.{new}", (new, new_name)
        assert not hasattr(importlib.import_module(f"jav.{MOVED_MODULES.get(old, old)}"), name), (old, name)
