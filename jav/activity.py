"""Felhasználónkénti napi tevékenységnapló („Mai munkám”, 061 döntés: aktív felhasználó + kiosztás).

Új nyilvántartás nélkül, a meglévő szerzős sorokból: csomag-események (átnevezés, elrejtés, felelős…), recept-
hozzárendelés, futás indítása és jóváhagyása, mezőjavítás (a levél szándékának javítása is), teendő lezárása,
feladatjavaslat-döntés, postafiók-letöltés. A régi V4 „Mai munkám” nézetének mintája (ott egy közös audit-táblából).

A nap a gép helyi naptári napja; az időbélyegek UTC ISO-alakban vannak tárolva, ezért a nap határait UTC-re váltjuk.
A név kis-nagybetűtől függetlenül egyezik (a 061 előtti sorok szerzője más írásmóddal is szerepelhet).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from jav import store

# (művelet-kód, SQL): minden lekérdezés (at, actor, workpackage_id, run_id, detail) oszlopokat ad, a nap határaival
_SOURCES: tuple[tuple[str, str], ...] = (
    ("event", "SELECT created_at at, actor, workpackage_id, NULL run_id, action detail FROM workpackage_events"
              " WHERE created_at >= ? AND created_at < ?"),
    ("recipe", "SELECT created_at at, actor, workpackage_id, NULL run_id, recipe_id detail FROM recipe_assignments"
               " WHERE created_at >= ? AND created_at < ?"),
    ("run_start", "SELECT created_at at, actor, workpackage_id, run_id, mode detail FROM runs"
                  " WHERE created_at >= ? AND created_at < ?"),
    ("run_approve", "SELECT approved_at at, approved_by actor, workpackage_id, run_id, approval detail FROM runs"
                    " WHERE approved_at >= ? AND approved_at < ?"),
    ("correction", "SELECT k.created_at at, k.actor, r.workpackage_id, k.run_id, k.item_id detail"
                   " FROM run_item_corrections k LEFT JOIN runs r ON r.run_id = k.run_id"
                   " WHERE k.created_at >= ? AND k.created_at < ?"),
    ("reason_resolve", "SELECT closed_at at, actor, NULL workpackage_id, run_id, reason detail FROM review_reasons"
                       " WHERE status='resolved' AND closed_at >= ? AND closed_at < ?"),
    ("task_decision", "SELECT d.decided_at at, d.actor, NULL workpackage_id, d.run_id, d.decision detail"
                      " FROM email_task_decisions d WHERE d.decided_at >= ? AND d.decided_at < ?"),
    ("task_done", "SELECT d.done_at at, d.done_by actor, NULL workpackage_id, d.run_id, NULL detail"
                  " FROM email_task_decisions d WHERE d.done_at >= ? AND d.done_at < ?"),  # 062
    ("mailbox_pull", "SELECT created_at at, actor, NULL workpackage_id, NULL run_id, request detail FROM mailbox_pulls"
                     " WHERE created_at >= ? AND created_at < ?"),
)


def day_bounds(day: str | None) -> tuple[str, str]:
    """A helyi naptári nap (ÉÉÉÉ-HH-NN; üresen: ma) határai UTC ISO-alakban."""
    d = date.fromisoformat(day) if day else datetime.now().astimezone().date()
    local = datetime.now().astimezone().tzinfo
    start = datetime.combine(d, time.min, tzinfo=local).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def _flow_run(run_id: str | None) -> str | None:
    """A teendő-ok és a feladatdöntés a tétel folyamat-azonosítóját tárolja (`<futás>:<tétel>`); a futás az eleje."""
    return run_id.split(":", 1)[0] if run_id else None


def entries(actor: str, day: str | None = None) -> list[dict[str, Any]]:
    """A személy műveletei a napon, időrendben (a legutóbbi elöl)."""
    lo, hi = day_bounds(day)
    who = " ".join(actor.split()).casefold()
    out: list[dict[str, Any]] = []
    with store.connect() as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM workpackages")}
        run_wp = {r["run_id"]: r["workpackage_id"] for r in c.execute("SELECT run_id, workpackage_id FROM runs")}
        for code, sql in _SOURCES:
            table = sql.split(" FROM ", 1)[1].split()[0]
            if table not in tables:  # a modul táblája még nem jött létre (pl. nincs postafiók-letöltés)
                continue
            for r in c.execute(sql, (lo, hi)):
                if not r["actor"] or " ".join(str(r["actor"]).split()).casefold() != who:
                    continue
                run_id = r["run_id"] if code in ("run_start", "run_approve", "correction") else _flow_run(r["run_id"])
                wp_id = r["workpackage_id"] or (run_wp.get(run_id) if run_id else None)
                action = r["detail"] if code == "event" else code
                out.append({"at": r["at"], "action": action, "detail": _detail(code, r["detail"]),
                            "workpackage_id": wp_id, "workpackage_name": names.get(wp_id) if wp_id else None, "run_id": run_id})
    out.sort(key=lambda e: e["at"], reverse=True)
    return out


def _detail(code: str, raw: Any) -> str | None:
    """Rövid, személyes adat nélküli részlet a művelethez (a mezőértékek és a levelek tartalma nem kerül ide)."""
    if raw is None or code == "event":
        return None
    if code == "mailbox_pull":
        try:
            req = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return req.get("mailbox") if isinstance(req, dict) else None
    if code == "correction":
        return None  # a tétel azonosítója hash, nem beszédes; a futás hivatkozása elég
    return str(raw)
