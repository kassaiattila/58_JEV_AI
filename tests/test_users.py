"""061 döntés: aktív felhasználó + kiosztás. Jelszó nélkül; a névlista nem üres → emberi művelet csak a listán szereplő
névvel; a futás indítása és a recept mentése is emberi döntés; a munkacsomagnak felelőse lehet („Saját csomagjaim”);
felhasználónként napi tevékenységnapló („Mai munkám”). Mesterséges adat, AI-hívás nélkül."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import unquote

from jav import app_settings, store
from tests import test_api
from tests.test_api import HUMAN, _ready_wp

env = test_api.env
ANNA = {"X-Actor": "Minta%20Anna"}


def _users(c, *names):
    r = c.put("/api/settings/users", json={"users": list(names)})
    assert r.status_code == 200, r.text


def _start(c, wp_id, headers):
    ready = c.get(f"/api/workpackages/{wp_id}/workflow/readiness").json()
    return c.post(f"/api/workpackages/{wp_id}/workflow/start", headers=headers,
                  json={"mode": "shadow", "expected_revision": ready["assignment_revision"], "input_hash": ready["input_hash"]})


def test_canonical_user_is_case_insensitive_and_open_while_list_is_empty(env):
    with store.use_store(env["db"]):
        assert app_settings.canonical_user("Bárki Béla") == "Bárki Béla"  # üres lista: bármely név (első beállítás)
        app_settings.save_users(["Minta Anna", "Teszt Elek"])
        assert app_settings.canonical_user("minta anna") == "Minta Anna"
        assert app_settings.canonical_user("Idegen Ödön") is None


def test_unknown_user_cannot_act_once_users_are_listed(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    _users(c, "Minta Anna")
    r = c.post(f"/api/workpackages/{wp['id']}/rename", headers={"X-Actor": "Idegen"}, json={"name": "x"})
    assert r.status_code == 403 and r.json()["error"] == "unknown_user"
    ok = c.post(f"/api/workpackages/{wp['id']}/rename", headers={"X-Actor": "minta%20anna"}, json={"name": "Átnevezve"})
    assert ok.status_code == 200, ok.text


def test_run_start_and_recipe_save_need_a_person_and_record_the_name(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    _users(c, "Minta Anna")
    assert _start(c, wp["id"], {}).status_code == 422  # szerző nélkül nem indítható
    assert _start(c, wp["id"], {"X-Actor": "Idegen"}).status_code == 403
    r = _start(c, wp["id"], ANNA)
    assert r.status_code == 201, r.text
    assert c.get(f"/api/runs/{r.json()['run_id']}").json()["run"]["actor"] == "Minta Anna"
    bad = c.post(f"/api/workpackages/{wp['id']}/workflow", json={"recipe_id": "invoice-extraction", "params": {"arm": "G"},
                                                                 "expected_revision": 1})
    assert bad.status_code == 422


def test_owner_is_set_listed_filtered_and_logged(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    other = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(env["folder"]), "name": "Másik"}).json()["workpackage"]
    assert other["owner"] == unquote(HUMAN["X-Actor"])  # 065 döntés: az új csomag felelőse a létrehozó
    _users(c, "Minta Anna", "Teszt Elek")
    assert c.post(f"/api/workpackages/{wp['id']}/owner", headers=ANNA, json={"owner": "Senki"}).status_code == 422
    r = c.post(f"/api/workpackages/{wp['id']}/owner", headers=ANNA, json={"owner": "minta anna"})
    assert r.status_code == 200, r.text
    assert c.get(f"/api/workpackages/{wp['id']}").json()["workpackage"]["owner"] == "Minta Anna"
    rows = c.post("/api/datasets/workpackages/query", json={}).json()["rows"]
    assert {x["id"]: x["owner"] for x in rows} == {wp["id"]: "Minta Anna", other["id"]: other["owner"]}
    mine = c.post("/api/datasets/workpackages/query", json={"scope": {"owner": "Minta Anna"}}).json()["rows"]
    assert [x["id"] for x in mine] == [wp["id"]]
    cleared = c.post(f"/api/workpackages/{wp['id']}/owner", headers=ANNA, json={"owner": None})
    assert cleared.status_code == 200 and cleared.json()["workpackage"]["owner"] is None
    with store.use_store(env["db"]), store.connect() as db:
        events = [r["action"] for r in db.execute("SELECT action FROM workpackage_events WHERE workpackage_id=? ORDER BY rowid", (wp["id"],))]
    assert events == ["owner", "owner"]


def test_today_activity_lists_only_the_persons_own_actions(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])  # a recept hozzárendelése: Teszt Elek (HUMAN)
    _users(c, "Minta Anna", "teszt.elek")
    c.post(f"/api/workpackages/{wp['id']}/owner", headers=ANNA, json={"owner": "Minta Anna"})
    run_id = _start(c, wp["id"], ANNA).json()["run_id"]
    day = datetime.now(timezone.utc).astimezone().date().isoformat()
    res = c.post("/api/datasets/activity/query", json={"scope": {"actor": "Minta Anna", "day": day}}).json()
    actions = sorted(r["action"] for r in res["rows"])
    assert actions == ["owner", "run_start"]
    start = next(r for r in res["rows"] if r["action"] == "run_start")
    assert start["_run"] == run_id and start["_wp"] == wp["id"] and start["workpackage_name"] == "Mesterséges számlák"
    elek = c.post("/api/datasets/activity/query", json={"scope": {"actor": "teszt.elek", "day": day}}).json()["rows"]
    assert [r["action"] for r in elek] == ["recipe"]
    assert elek[0]["detail"] == "Számlák adatainak kinyerése"  # 062: a recept címe, nem a kódneve
    assert c.post("/api/datasets/activity/query", json={"scope": {}}).status_code == 422  # a személy kötelező


def test_changing_a_filled_user_list_needs_a_listed_author(env):
    """066 Á35: a névlista írása eddig szerző nélkül is ment; az első kitöltés (üres lista) szerző nélkül is lehet, utána
    csak a listán szereplő szerző módosíthatja."""
    c = env["client"]
    _users(c, "Minta Anna")
    assert c.put("/api/settings/users", json={"users": ["Minta Anna", "Új Név"]}).status_code == 422
    assert c.put("/api/settings/users", json={"users": ["Minta Anna", "Új Név"]}, headers=HUMAN).status_code == 403
    r = c.put("/api/settings/users", json={"users": ["Minta Anna", "Új Név"]}, headers=ANNA)
    assert r.status_code == 200 and r.json()["users"] == ["Minta Anna", "Új Név"]


def test_user_list_accepts_only_names_the_actor_header_can_carry(env):
    """066 Á25: a névlista eddig bármilyen nevet elfogadott, a szerző-fejléc szabálya (betű, szám, szóköz, pont, @, kötőjel)
    viszont nem: a felvett „O'Brien” nevével utána semmit nem lehetett tenni. Most a mentés is ugyanazt a szabályt nézi."""
    c = env["client"]
    bad = c.put("/api/settings/users", json={"users": ["Minta Anna", "O'Brien", "<b>x</b>"]})
    assert bad.status_code == 422 and "O'Brien" in bad.json()["message"]
    assert c.get("/api/settings/users").json()["users"] == []
    ok = c.put("/api/settings/users", json={"users": ["Kővári Ödön", "teszt.elek@minta.hu"]})
    assert ok.status_code == 200
