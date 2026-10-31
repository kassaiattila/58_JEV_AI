"""265 (code review TOOL-18): a worktree's preflight reads and writes the main checkout's internal documents.

The internal documents (handoffs, plans, the state snapshot) are not in git, so a linked worktree has none: its
preflight looked at its own empty handoff folder and wrote a state snapshot of its own nobody reads. The hooks already
used the main checkout's; preflight and the snapshot now follow the same rule (`devstate.docs_root`). Temporary folders.
"""

from __future__ import annotations

from jav.core import devstate


def test_a_worktree_uses_the_main_checkouts_documents(tmp_path) -> None:
    main, worktree = tmp_path / "main", tmp_path / "wt"
    (main / ".git").mkdir(parents=True)
    (main / "docs" / "handoffs").mkdir(parents=True)
    worktree.mkdir()
    assert devstate.docs_root(worktree, str(main / ".git")) == main.resolve()


def test_the_main_checkout_and_a_main_without_handoffs_use_their_own(tmp_path) -> None:
    main, worktree = tmp_path / "main", tmp_path / "wt"
    (main / ".git").mkdir(parents=True)
    worktree.mkdir()
    assert devstate.docs_root(worktree, str(main / ".git")) == worktree  # the main one has no handoffs
    (main / "docs" / "handoffs").mkdir(parents=True)
    assert devstate.docs_root(main, ".git") == main
    assert devstate.docs_root(worktree, "") == worktree  # no git answer


def test_a_path_elsewhere_is_shown_whole(tmp_path) -> None:
    assert devstate.shown_path(devstate.PROJECT_ROOT / "docs" / "STATE.md") == "docs/STATE.md"
    assert devstate.shown_path(tmp_path / "STATE.md") == str(tmp_path / "STATE.md")
