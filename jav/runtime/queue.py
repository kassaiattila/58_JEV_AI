"""Tartós munkasor SQLite-ban (040 K1). Minta: a régi AIFLOW V4 `orchestrator/framework/jobq.py` (viselkedési port).

Megtartott invariánsok a V4-ből:
- A feladatsor maga a tartós befogadási bizonylat: a `dedup_key` UNIQUE az atomi duplikátumvédelem; ismételt
  felvétel a MEGLÉVŐ feladatot adja vissza (`deduped=True`), a payload nem cserélődik ki.
- Foglalás egy rövid `BEGIN IMMEDIATE` tranzakcióban, utána a munka zár nélkül fut.
- A próbálkozásszám túléli az újraindítást; a határ után `dead`. A visszaengedés (`release`) nem éget próbálkozást.
- Az árva foglalások visszaállítása CSAK induláskor (`recover_orphans`): egy feldolgozó van, ezért induláskor minden
  `claimed` sor bizonyítottan halott. Több feldolgozóhoz előbb bérlet/életjel kellene (a V4-ben sincs).
- 063: az árva feladat próbálkozásszáma is korlátos (`ORPHAN_MAX_ATTEMPTS`; a V4 `sweep_orphans(max_attempts)` és az
  induláskori leállítás-befejezés viselkedése, amelyet a K1-es átvétel kihagyott), különben egy feldolgozót „megölő” feladat
  minden újraindításkor újra az első lenne; a leállás közben kért leállítás induláskor lezárul; a foglalás a kevesebbszer
  próbált feladatot veszi előre (a gyanús feladat a friss munka mögé kerül).
- Végállapot (done / dead / cancelled) nem változik vissza.
Nem jött át: PostgreSQL-zárak, OCR-előd-lánc, intake-batch szünet, forrás-epilógus (a V4 infrastruktúrájához kötöttek).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from jav import store

TERMINAL = ("done", "dead", "cancelled")
ORPHAN_MAX_ATTEMPTS = 3  # 063: ennyi félbemaradt próbálkozás után a feladat halott (nem ismétlődik végtelenül)

store.register_schema("runtime.queue", """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL,
    dedup_key     TEXT UNIQUE,
    run_id        TEXT,
    payload       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',   -- queued | claimed | done | dead | cancelled
    attempts      INTEGER NOT NULL DEFAULT 0,
    available_at  TEXT NOT NULL,
    claimed_by    TEXT,
    claimed_at    TEXT,
    cancel_requested_at TEXT,
    finished_at   TEXT,
    error         TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_jobs_claim ON jobs(status, available_at, id);
CREATE INDEX IF NOT EXISTS ix_jobs_run ON jobs(run_id, status);
CREATE TABLE IF NOT EXISTS queue_control (id INTEGER PRIMARY KEY CHECK (id = 1), paused INTEGER NOT NULL DEFAULT 0);
""")


class JobCancelled(Exception):
    """A kezelő leállítást kért; biztonságos lépéshatáron dobjuk, nem feldolgozási hiba."""


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    dedup_key: str | None
    run_id: str | None
    payload: dict[str, Any]
    status: str
    attempts: int
    claimed_by: str | None
    error: str | None
    deduped: bool = False


def _ts(delay_s: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delay_s)).isoformat(timespec="microseconds")


def _job(row, deduped: bool = False) -> Job:
    return Job(id=row["id"], kind=row["kind"], dedup_key=row["dedup_key"], run_id=row["run_id"],
               payload=json.loads(row["payload"]), status=row["status"], attempts=row["attempts"],
               claimed_by=row["claimed_by"], error=row["error"], deduped=deduped)


def _begin(c) -> None:
    c.commit()  # a connect séma-inicializálását lezárjuk a saját írási tranzakció előtt
    c.execute("BEGIN IMMEDIATE")


def enqueue(kind: str, *, run_id: str | None, payload: dict[str, Any], dedup_key: str | None = None,
            delay_s: float = 0) -> Job:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
    with store.connect() as c:
        _begin(c)
        if dedup_key is not None:
            row = c.execute("SELECT * FROM jobs WHERE dedup_key=?", (dedup_key,)).fetchone()
            if row is not None:
                return _job(row, deduped=True)
        cur = c.execute("INSERT INTO jobs(kind, dedup_key, run_id, payload, available_at, created_at) VALUES (?,?,?,?,?,?)",
                        (kind, dedup_key, run_id, body, _ts(delay_s), _ts()))
        return _job(c.execute("SELECT * FROM jobs WHERE id=?", (cur.lastrowid,)).fetchone())


def get(job_id: int) -> Job | None:
    with store.connect() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _job(row) if row else None


def claim(worker: str, kinds: tuple[str, ...] | None = None) -> Job | None:
    """A legrégebbi elérhető feladat lefoglalása; szüneteltetett sornál None."""
    with store.connect() as c:
        _begin(c)
        paused = c.execute("SELECT paused FROM queue_control WHERE id=1").fetchone()
        if paused and paused["paused"]:
            return None
        kind_sql = f" AND kind IN ({','.join('?' * len(kinds))})" if kinds else ""
        row = c.execute(
            "SELECT * FROM jobs WHERE status='queued' AND available_at<=? AND cancel_requested_at IS NULL" + kind_sql
            + " ORDER BY attempts, id LIMIT 1", (_ts(), *(kinds or ()))).fetchone()
        if row is None:
            return None
        c.execute("UPDATE jobs SET status='claimed', claimed_by=?, claimed_at=? WHERE id=?", (worker, _ts(), row["id"]))
        return _job(c.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())


def _transition(job_id: int, sql: str, params: tuple, result: str) -> str:
    """Közös átmenet: végállapotú feladat nem változik, a meglévő végállapotot adja vissza."""
    with store.connect() as c:
        _begin(c)
        row = c.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        if row["status"] in TERMINAL:
            return row["status"]
        c.execute(sql, params)
        return result


def complete(job_id: int) -> str:
    return _transition(job_id, "UPDATE jobs SET status='done', finished_at=?, error=NULL, claimed_by=NULL WHERE id=?",
                       (_ts(), job_id), "done")


def fail(job_id: int, error: str, *, max_attempts: int, backoff_s: float) -> str:
    """Hiba: próbálkozás +1; a határ alatt lineáris várakozással vissza a sorba, a határon `dead`."""
    with store.connect() as c:
        _begin(c)  # olvasás és írás egy tranzakcióban
        row = c.execute("SELECT status, attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        if row["status"] in TERMINAL:
            return row["status"]
        attempts = row["attempts"] + 1
        status = "dead" if attempts >= max_attempts else "queued"
        c.execute("UPDATE jobs SET attempts=?, error=?, status=?, finished_at=?, available_at=?, claimed_by=NULL, claimed_at=NULL"
                  " WHERE id=?", (attempts, error[:300], status, _ts() if status == "dead" else None,
                                  _ts(backoff_s * attempts), job_id))
        return status


def release(job_id: int, *, delay_s: float) -> str:
    """Vissza a sorba próbálkozás elhasználása nélkül (pl. elfogyott keret, átmeneti korlát)."""
    return _transition(job_id, "UPDATE jobs SET status='queued', claimed_by=NULL, claimed_at=NULL, available_at=? WHERE id=?",
                       (_ts(delay_s), job_id), "queued")


def cancel(job_id: int) -> str:
    """Sorban álló feladat azonnal leáll; futónál leállítási kérés (a feldolgozó a következő lépéshatáron áll meg)."""
    with store.connect() as c:
        row = c.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row["status"] == "queued":
        return _transition(job_id, "UPDATE jobs SET status='cancelled', finished_at=? WHERE id=?", (_ts(), job_id), "cancelled")
    if row["status"] == "claimed":
        _transition(job_id, "UPDATE jobs SET cancel_requested_at=? WHERE id=?", (_ts(), job_id), "claimed")
        return "cancel_requested"
    return row["status"]


def check_cancellation(job_id: int) -> None:
    """A futó lépések hívják biztonságos határon; kért leállításnál `JobCancelled`."""
    with store.connect() as c:
        row = c.execute("SELECT status, cancel_requested_at FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row and (row["cancel_requested_at"] or row["status"] == "cancelled"):
        raise JobCancelled(f"job {job_id} cancellation requested")


def finish_cancelled(job_id: int) -> str:
    return _transition(job_id, "UPDATE jobs SET status='cancelled', finished_at=?, claimed_by=NULL WHERE id=?",
                       (_ts(), job_id), "cancelled")


@dataclass(frozen=True)
class OrphanRecovery:
    """Az induláskori árva-kezelés eredménye: a visszaengedettek száma, a halottá és a leállítottá vált feladatok."""
    requeued: int
    dead: list[Job]
    cancelled: list[Job]


def recover_orphans(*, max_attempts: int = ORPHAN_MAX_ATTEMPTS) -> OrphanRecovery:
    """CSAK a feldolgozó indulásakor: minden `claimed` sor halott futás. Vissza a sorba, próbálkozás +1; a korlátnál
    `dead` (063); ha közben leállítást kértek, `cancelled` (063: különben a foglalás kihagyná, és örökre sorban állna)."""
    now = _ts()
    requeued, dead_ids, cancelled_ids = 0, [], []
    with store.connect() as c:
        _begin(c)
        for r in c.execute("SELECT id, attempts, cancel_requested_at FROM jobs WHERE status='claimed'").fetchall():
            if r["cancel_requested_at"]:
                c.execute("UPDATE jobs SET status='cancelled', finished_at=?, claimed_by=NULL, claimed_at=NULL,"
                          " error='orphaned: cancelled while the worker was down' WHERE id=?", (now, r["id"]))
                cancelled_ids.append(r["id"])
            elif r["attempts"] + 1 >= max_attempts:
                c.execute("UPDATE jobs SET status='dead', attempts=attempts+1, finished_at=?, claimed_by=NULL, claimed_at=NULL,"
                          " error=? WHERE id=?", (now, f"orphaned: the worker stopped {r['attempts'] + 1} times on this job", r["id"]))
                dead_ids.append(r["id"])
            else:
                c.execute("UPDATE jobs SET status='queued', attempts=attempts+1, claimed_by=NULL, claimed_at=NULL,"
                          " error='orphaned: worker restarted' WHERE id=?", (r["id"],))
                requeued += 1
        dead = [_job(c.execute("SELECT * FROM jobs WHERE id=?", (i,)).fetchone()) for i in dead_ids]
        cancelled = [_job(c.execute("SELECT * FROM jobs WHERE id=?", (i,)).fetchone()) for i in cancelled_ids]
    return OrphanRecovery(requeued=requeued, dead=dead, cancelled=cancelled)


def active_run_ids() -> list[str]:
    """064: azok a futások, amelyeknek van még sorban álló vagy foglalt feladata (a tár ritkítása ezeket kihagyja)."""
    with store.connect() as c:
        return [r["run_id"] for r in c.execute(
            "SELECT DISTINCT run_id FROM jobs WHERE status IN ('queued', 'claimed') AND run_id IS NOT NULL ORDER BY run_id")]


def set_paused(paused: bool) -> None:
    with store.connect() as c:
        c.execute("INSERT INTO queue_control(id, paused) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET paused=excluded.paused",
                  (int(paused),))


def counts(*, run_id: str | None = None) -> dict[str, int]:
    with store.connect() as c:
        rows = c.execute("SELECT status, COUNT(*) n FROM jobs" + (" WHERE run_id=?" if run_id else "") + " GROUP BY status",
                         (run_id,) if run_id else ()).fetchall()
    return {r["status"]: r["n"] for r in rows}
