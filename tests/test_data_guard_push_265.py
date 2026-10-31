"""265 (code review SEC-03, SEC-04, TOOL-10): the data guard's push rules and four gaps.

- SEC-03: the push hook refused only a forbidden history; CLAUDE.md said it refused `--all`, `--tags` and `--mirror`.
  The hook does not see the command line, so it now refuses the refs they bring: more than one stage branch, a tag
  that is not a release, an archive branch, a deletion. An entry of `forbidden_history` this clone cannot resolve is
  said, not skipped.
- SEC-04: `.playwright-mcp/` (the screenshots) was kept out only by `.gitignore`.
- TOOL-10: a denied term with a space or a point never matched (refused now); an added line starting with "++ " was
  read as the next file's header, switching the check off; the `.jsonl` and `.log` files were not blocked.
No git push is made; the rules are checked on the hook's input lines.
"""

from __future__ import annotations

import pytest

from jav.devtools import data_guard as dg

GUARD = dg.Guard(dg.load_config(), env_secrets={}, env_sources=())
SHA = "1" * 40


def _refs(*remote_refs: str, delete: bool = False) -> list[list[str]]:
    return [["refs/heads/x", dg.ZERO_SHA if delete else SHA, ref, dg.ZERO_SHA] for ref in remote_refs]


def _kinds(lines: list[list[str]]) -> list[str]:
    return [f.path for f in dg._push_refs(GUARD, lines)]


def test_main_a_release_tag_and_one_stage_branch_may_go() -> None:
    assert _kinds(_refs("refs/heads/main", "refs/tags/v1.72.0", "refs/heads/review-fixes-265")) == []


@pytest.mark.parametrize("refs", [("refs/heads/a", "refs/heads/b"), ("refs/tags/k0-kesz",), ("refs/heads/archive/old",),
                                  ("refs/tags/archive/kiserletek-204",)])
def test_what_all_tags_or_an_archive_would_bring_is_refused(refs) -> None:
    assert _kinds(_refs(*refs))


def test_main_or_a_tag_is_never_deleted_and_nothing_but_branches_and_tags_goes() -> None:
    assert _kinds(_refs("refs/heads/main", "refs/tags/v1.71.0", delete=True)) == ["refs/heads/main", "refs/tags/v1.71.0"]
    assert _kinds(_refs("refs/heads/review-fixes-265", delete=True)) == []  # a merged stage branch may go
    assert _kinds(_refs("refs/remotes/origin/main")) == ["refs/remotes/origin/main"]  # what --mirror brings


def test_the_screenshots_and_the_run_logs_are_blocked() -> None:
    for path in (".playwright-mcp/266/r1/after.png", "notes/run.jsonl", "service.log"):
        assert GUARD.check_path(path) is not None, path


def test_a_denied_term_is_one_word() -> None:
    with pytest.raises(dg.DataGuardError):
        dg.deny_entry("Example Kft.")
    assert dg.deny_entry("example")["len"] == 7


def test_an_added_line_starting_with_two_pluses_is_content() -> None:
    diff = "\n".join([
        "diff --git a/notes.md b/notes.md", "--- a/notes.md", "+++ b/notes.md", "@@ -0,0 +1,3 @@",
        "+first", "+++ /dev/null", "+the line after it",
    ])
    assert [(p, n, t) for p, n, t in dg.added_lines(diff)] == [
        ("notes.md", 1, "first"), ("notes.md", 2, "++ /dev/null"), ("notes.md", 3, "the line after it")]
