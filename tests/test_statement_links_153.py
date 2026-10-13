"""153 (review C8): a statement folder's survey does not follow a link to a file outside the folder.

The other folder readers keep to the folder once links are followed (`work.folder_documents`); the statement readers
listed a linked file from anywhere. Synthetic files only; skipped where the system does not let the test make a link.
"""

import os

import pytest

from jav import statement_package, statement_table


def _link(target, link):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the test make a symbolic link")


def test_a_linked_pdf_from_outside_the_folder_is_passed_over(tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"%PDF-1.4 synthetic")
    folder = tmp_path / "statements"
    folder.mkdir()
    (folder / "own.pdf").write_bytes(b"%PDF-1.4 synthetic")
    _link(outside / "secret.pdf", folder / "linked.pdf")
    assert [p.name for p in statement_package._pdfs_in(folder)] == ["own.pdf"]
    assert statement_table.inside(folder / "own.pdf", folder) and not statement_table.inside(folder / "linked.pdf", folder)
