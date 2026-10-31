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
