"""152: the package's processing section offers its older live runs for superseding.

151 put the "Supersede" offer on the older run's own page only, which a person reaches from the package's run table;
in a trial on 2026-10-12 the owner did not find it. The package view now lists every older live run a person can
supersede (`work.supersedable_runs`, the same offer as on the run's page), oldest first, and the list empties as they
are superseded. Synthetic data, no paid calls.
"""

from fastapi.testclient import TestClient

from jav import api, work, work_views
from tests.test_supersede_runs_151 import runs  # noqa: F401 - the shared fixture: one package, an older and a newer live run


def test_the_package_lists_the_older_run_with_its_offer(runs):  # noqa: F811
    (row,) = work.supersedable_runs(runs["wp"])
    assert row == {"run_id": runs["older"], "created_at": work.get_run(runs["older"])["created_at"], "by": runs["newer"],
                   "open_reasons": 2, "resolved_reasons": 0, "corrected_items": 0}
    assert work_views.workpackage_view(runs["wp"])["supersedable"] == [row]


def test_a_superseded_run_leaves_the_list(runs):  # noqa: F811
    work.supersede_run(runs["older"], actor="teszt.elek")
    assert work.supersedable_runs(runs["wp"]) == []


def test_the_service_returns_the_list_with_the_package(runs):  # noqa: F811
    client = TestClient(api.create_app(store_path=runs["db"]), base_url="http://127.0.0.1:8930")
    r = client.get(f"/api/workpackages/{runs['wp']}")
    assert r.status_code == 200, r.text
    assert [x["run_id"] for x in r.json()["supersedable"]] == [runs["older"]]
