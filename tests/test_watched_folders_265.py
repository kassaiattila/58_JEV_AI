"""265 (code review APPR-16, X-17): a watched folder never takes in a document another one takes, or the
application's own data.

Two enabled watched folders could name the same folder, or one could lie inside another that is read with its
subfolders: a document then went into two batches. A watched folder could also lie in the store, the downloaded emails
or the runs folder. Now saving the list refuses both (a disabled folder, or one read without its subfolders above
another, takes nothing twice). Synthetic data, no AI calls.
"""

from pathlib import Path

import pytest

from jav.app import app_settings
from jav.core import store
from jav.core.config import DATA_ROOT
from tests import test_api

env = test_api.env
W = app_settings.WatchedFolder


def _resolve(raw: str) -> Path:
    return Path(raw).resolve()


def test_two_enabled_watched_folders_never_read_one_document(env):
    inner = env["folder"] / "inner"
    inner.mkdir()
    with store.use_store(env["db"]):
        with pytest.raises(app_settings.FolderOverlap):
            app_settings.save_folders([W(path=str(env["folder"])), W(path=str(env["folder"]), name="again")],
                                      check_dir=_resolve)
        with pytest.raises(app_settings.FolderOverlap):
            app_settings.save_folders([W(path=str(env["folder"]), recursive=True), W(path=str(inner), name="inner")],
                                      check_dir=_resolve)
        saved = app_settings.save_folders([W(path=str(env["folder"])), W(path=str(inner), name="inner"),
                                           W(path=str(env["folder"]), name="off", enabled=False)], check_dir=_resolve)
        assert len(saved) == 3


@pytest.mark.parametrize("part", ["store", "inbox", "runs"])
def test_a_watched_folder_is_never_in_the_application_s_own_data(env, part):
    with store.use_store(env["db"]), pytest.raises(app_settings.FolderOverlap):
        app_settings.save_folders([W(path=str(DATA_ROOT / part))], check_dir=_resolve)


def _stored_twice(env) -> tuple[str, str]:
    """272 (K2, the rest of APPR-16): two enabled folders reading one document, stored before the save refused them
    (the rule came in 265; a list saved earlier keeps them until it is saved again)."""
    import os
    from datetime import datetime, timedelta, timezone

    doc = env["folder"] / "a.pdf"
    doc.write_bytes(b"%PDF-1.4 invented")
    os.utime(doc, (doc.stat().st_atime - 3600, doc.stat().st_mtime - 3600))  # settled long ago
    with store.use_store(env["db"]):
        app_settings.save_folders([W(path=str(env["folder"]), name="first")], check_dir=_resolve)
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        with store.connect() as c:
            row = dict(c.execute("SELECT * FROM watched_folders").fetchone())
            c.execute("INSERT INTO watched_folders(id, name, path, enabled, recursive, batch_mode, recipe_id, params,"
                      " interval_min, next_at, last_at, last_status, last_result, updated_at)"
                      " VALUES ('wf-second','second',?,1,0,'folder',NULL,'{}',5,?,NULL,NULL,NULL,?)",
                      (row["path"], past, past))
            c.execute("UPDATE watched_folders SET next_at=?", (past,))
    return row["id"], "wf-second"


def test_two_stored_folders_reading_one_document_take_it_in_once(env):
    first, second = _stored_twice(env)
    with store.use_store(env["db"]):
        scanned = app_settings.tick()
        rows = {f["id"]: f for f in app_settings.folders()}
    assert set(scanned) == {first, second}
    assert rows[first]["last_status"] == "ok" and rows[first]["last_result"]["new"] == 1
    assert rows[second]["last_status"] == "error" and "the same documents" in rows[second]["last_result"]["error"]
    assert "new" not in rows[second]["last_result"]
