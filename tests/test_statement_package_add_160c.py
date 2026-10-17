"""160-C S2 (plan F-flexible work package): a statement package grows only through its own survey.

A plain document add is refused (the survey decides which file is which account's which month); the package's own
survey uses the package's party and period and marks what the package already holds, and the add logs what it took.
Synthetic exports and PDF lines only (the 137 Erste shapes), no AI call.
"""

from __future__ import annotations

import json

import pytest

from jav import statement_package as sp
from jav import work
from tests import test_api
from tests import test_statement_package_140 as sp140
from tests.test_statement_package_140 import _folder, _party, _row, _survey

db = sp140.db  # the 140 fixtures: a store of its own, the synthetic PDFs' text layer
pdf_text = sp140.pdf_text


def _package_with_may(root, party: str) -> tuple[str, object]:
    folder = _folder(root)
    may = _row(_survey(folder, party), "2026-05")
    sc = sp.create(name="Example statements", party_id=party, period_start="2026-05-01", period_end="2026-06-30",
                   paths=[folder], statements=[may["id"]], pdfs=[], actor="tester")
    return sc["workpackage_id"], folder


def test_a_plain_add_is_refused_for_a_statement_package(db):
    wp_id, folder = _package_with_may(db, _party())
    with pytest.raises(ValueError, match="survey"):
        work.add_to_package(wp_id, [folder / "other-bank-2026-05.pdf"], expected_revision=work.get(wp_id)["revision"], actor="tester")


def test_the_packages_survey_marks_what_it_holds_and_the_add_takes_the_rest(db):
    party = _party()
    wp_id, folder = _package_with_may(db, party)
    survey = sp.survey_for(wp_id, [folder])
    may, june = _row(survey, "2026-05"), _row(survey, "2026-06")
    assert (survey["period_start"], survey["period_end"], survey["party"]["id"]) == ("2026-05-01", "2026-06-30", party)
    assert (may["in_package"], may["chosen"]) == (True, False)  # already in the package: not proposed again
    assert (june["in_package"], june["chosen"]) == (False, True)
    before = work.get(wp_id)
    wp = sp.add(wp_id, paths=[folder], statements=[june["id"]], pdfs=[], expected_revision=before["revision"], actor="tester")
    assert len(wp["items"]) == len(before["items"]) + 1 and june["id"] in {i["item_id"] for i in wp["items"]}
    event = work.workpackage_events(wp_id)[-1]
    assert (event["action"], event["actor"], json.loads(event["detail"])) == ("statement_add", "tester", {"statements": 1, "pdfs": 0})
    with pytest.raises(sp.PackageError, match="already"):
        sp.add(wp_id, paths=[folder], statements=[june["id"]], pdfs=[], expected_revision=wp["revision"], actor="tester")


# --- the service ---------------------------------------------------------------------------------------------------------


env = test_api.env


def test_the_service_grows_a_statement_package_through_its_survey_only(env):
    c, human = env["client"], test_api.HUMAN
    party = _party()
    wp_id, folder = _package_with_may(env["root"], party)
    rev = work.get(wp_id)["revision"]
    refused = c.post(f"/api/workpackages/{wp_id}/items", headers=human, json={"paths": [str(folder / "other-bank-2026-05.pdf")],
                                                                              "expected_revision": rev})
    assert refused.status_code == 422 and "survey" in refused.json()["message"]
    r = c.post(f"/api/workpackages/{wp_id}/statements/survey", headers=human, json={"paths": [str(folder)]})
    assert r.status_code == 200, r.text
    june = _row(r.json(), "2026-06")
    added = c.post(f"/api/workpackages/{wp_id}/statements/add", headers=human,
                   json={"paths": [str(folder)], "statements": [june["id"]], "pdfs": [], "expected_revision": rev})
    assert added.status_code == 200, added.text
    assert june["id"] in {i["item_id"] for i in added.json()["workpackage"]["items"]}
