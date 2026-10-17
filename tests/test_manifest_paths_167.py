"""167 (review S-4): the named copies' manifest never names a user's folders, even when the originals share only a drive.

The manifest (`jegyzek.csv`, shipped in a ZIP someone may pass on) names each original below the folder the originals
share (153, review C8). When they shared only the drive root, the path below it was the full local path without the
drive (`Users\\<name>\\...`). Now a shared folder that is only a root, or the folder that holds the users' home folders,
gives the file names alone. Synthetic paths only.
"""

from pathlib import Path

import pytest

from jav import naming


@pytest.mark.parametrize("paths", [
    ["C:\\Users\\someone\\Documents\\a.pdf", "C:\\Data\\b.pdf"],  # only the drive root in common
    ["C:\\a.pdf", "C:\\Users\\someone\\b.pdf"],
    ["\\\\nas\\share\\someone\\a.pdf", "\\\\nas\\share\\other\\b.pdf"],  # only the network share in common
    ["/home/someone/a.pdf", "/data/b.pdf"],  # only the root folder in common
])
def test_originals_sharing_only_a_root_are_named_by_their_file_names(paths):
    where = naming._shared_folder_paths(paths)
    assert where == {p: p.replace("\\", "/").rsplit("/", 1)[-1] for p in paths}
    assert not any("someone" in v or "Users" in v for v in where.values())


def test_originals_in_different_users_folders_are_named_by_their_file_names(monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("C:\\Users\\someone")))
    paths = ["C:\\Users\\someone\\Documents\\a.pdf", "C:\\Users\\other\\Downloads\\b.pdf"]
    assert naming._shared_folder_paths(paths) == {paths[0]: "a.pdf", paths[1]: "b.pdf"}


def test_a_real_shared_folder_still_keeps_the_subfolders_below_it():
    paths = ["C:\\Users\\someone\\invoices\\2026\\a.pdf", "C:\\Users\\someone\\invoices\\2026\\may\\b.pdf"]
    assert naming._shared_folder_paths(paths) == {paths[0]: "a.pdf", paths[1]: "may\\b.pdf"}
    single = ["C:\\Users\\someone\\invoices\\a.pdf"]
    assert naming._shared_folder_paths(single) == {single[0]: "a.pdf"}
