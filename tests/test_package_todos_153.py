"""153 (review): a package counts the to-dos its own runs raised, not another package's.

A to-do belongs to the document's content, so the same file in two packages carried one package's to-dos into the
other: a watched-folder package never run showed 720 open to-dos while its Review said there was nothing to review.
The package list's "incl. earlier runs" column, the package's to-dos and its items table now count only the package's
own runs' to-dos. Synthetic data, no paid calls.
"""

from jav import datasets, store, work, work_views
from jav.tablequery import Query
from tests.test_supersede_runs_151 import runs  # noqa: F401 - the shared fixture: one package, an older and a newer live run


def test_a_package_with_the_same_files_does_not_show_anothers_to_dos(runs, tmp_path):  # noqa: F811
    with store.use_store(runs["db"]):
        other = work.create_from_folder(tmp_path / "in", name="The same files, never run")["id"]
        assert work_views.workpackage_reviews(other)["open_reasons"] == 0
        assert work_views.workpackage_reviews(runs["wp"])["open_reasons"] == 3  # its own two runs' to-dos
        rows = {r["id"]: r for r in work_views.workpackage_list()}
        assert (rows[other]["open_reasons_all"], rows[runs["wp"]]["open_reasons_all"]) == (0, 3)
        items = datasets.query("workpackage_items", {"workpackage_id": other}, Query())["rows"]
        assert [r["open_reasons"] for r in items] == [0, 0]
