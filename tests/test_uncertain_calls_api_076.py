"""Paid calls with an uncertain outcome are listed and settled on the System page (076, Q-bizonytalan-keret).

Until now only `calls-uncertain` / `calls-resolve` on the command line could settle them, so a run's budget kept the
maximum cost committed and the step stayed blocked. The service lists them and settles one with the actual cost (or
none) and a note naming the person; the same rules as the command line. No paid call; the attempt is made up.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav import api, store
from jav.runtime import calls

BASE = "http://127.0.0.1:8930"
HUMAN = {"X-Actor": "test.user"}


@pytest.fixture()
def client(tmp_path: Path):
    db = tmp_path / "w.sqlite"
    with store.use_store(db):
        calls._reserve(run_id="run-x", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.2"),
                       budget_scope=None, request_hash=None)  # the process "stopped" in the middle of the call
        calls.release_holder()  # 092: the process stops; the operating system lets go of its holder lock
        assert calls.recover_uncertain() == 1
        yield TestClient(api.create_app(store_path=db), base_url=BASE)


def test_uncertain_calls_are_listed(client: TestClient):
    [row] = client.get("/api/system/uncertain-calls").json()["calls"]
    assert (row["run_id"], row["step_id"], row["provider"], row["status"]) == ("run-x", "s1", "openai", "uncertain")
    assert Decimal(row["max_cost_usd"]) == Decimal("0.2")


def test_settling_needs_a_person_and_a_note(client: TestClient):
    [row] = client.get("/api/system/uncertain-calls").json()["calls"]
    url = f"/api/system/uncertain-calls/{row['id']}/resolve"
    assert client.post(url, json={"cost_usd": "0.07", "note": "checked in the console"}).status_code in (401, 403, 422)
    assert client.post(url, json={"cost_usd": "0.07", "note": ""}, headers=HUMAN).status_code == 422
    assert client.post(url, json={"cost_usd": "-1", "note": "checked"}, headers=HUMAN).status_code == 422
    assert client.get("/api/system/uncertain-calls").json()["calls"]  # nothing settled yet


def test_settled_call_leaves_the_list_and_records_cost_and_person(client: TestClient):
    [row] = client.get("/api/system/uncertain-calls").json()["calls"]
    url = f"/api/system/uncertain-calls/{row['id']}/resolve"
    r = client.post(url, json={"cost_usd": "0.07", "note": "checked in the console"}, headers=HUMAN)
    assert r.status_code == 200, r.text
    assert client.get("/api/system/uncertain-calls").json()["calls"] == []
    [done] = calls.journal("run-x")
    assert (done["status"], done["cost_usd"]) == ("failed", "0.07")
    assert done["note"] == "test.user: checked in the console"
    again = client.post(url, json={"cost_usd": None, "note": "second time"}, headers=HUMAN)
    assert again.status_code == 409  # already settled
