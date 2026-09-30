"""Postafiók-olvasás a helyi szolgáltatásból (048 T2): darabszám-előnézet, letöltés, munkacsomag a friss levelekből.

A régi Outlook-szkriptet (`OUTLOOK_BRIDGE_SCRIPT`) változatlanul hívjuk a `scripts/mail_bridge_call.ps1` burkolón át:
- **előnézet** (`count`): a régi `-CountOnly`; ingyenes, fájlt nem ír, semmit nem jelöl olvasottnak;
- **letöltés** (`fetch`): a letöltés idejére egy saját fogadót indítunk szabad porton, egyszer használatos kulccsal
  (`jav.ingest_server.make_server`), a szkript oda küldi a leveleket; a fogadó a meglévő ismétlésvédelemmel írja őket
  a bejövő mappába. A szkript projektgyökere a saját `BRIDGE_ROOT` (csatolmányok, „már beolvasva” lista), nem a régi
  projekt.

Az új vagy megváltozott levelekből új munkacsomag készül (egy levél = egy tétel, a `message.json`), és rákerül a
levél-szándék recept; fizetős feldolgozás nem indul (2026-09-28 döntés: futtatás kézzel). Ha nincs új levél, nincs
munkacsomag. Az Outlooknak futnia kell a gépen (`-ExistingOutlook`).
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import subprocess
import threading
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jav import ingest_server, store, work
from jav.config import BRIDGE_ROOT, OUTLOOK_BRIDGE_SCRIPT, PROJECT_ROOT

log = logging.getLogger("jav.mailbox")

WRAPPER = PROJECT_ROOT / "scripts" / "mail_bridge_call.ps1"
EMAIL_RECIPE = "email-intent"
COUNT_TIMEOUT_S = 180
FETCH_TIMEOUT_S = 1800
_ACCOUNT = re.compile(r"^[^@\s,;'\"`$]+@[^@\s,;'\"`$]+\.[^@\s,;'\"`$]+$")
_FOLDER = re.compile(r"^[^,;'\"`$\\]{1,80}$")

Runner = Callable[[list[str], int], tuple[int, str, str]]


class BridgeError(RuntimeError):
    """A régi szkript nem futott le (pl. nem fut az Outlook, ismeretlen postafiók); a szöveg a szkript üzenete."""


class MailboxRequest(BaseModel):
    """Mit olvassunk: postafiók(ok), mappa(k), időszak (az utolsó N nap vagy dátumtól dátumig), legfeljebb hány levél."""

    model_config = ConfigDict(extra="forbid")

    accounts: list[str] = Field(min_length=1, max_length=5)
    folders: list[str] = Field(default_factory=lambda: ["Inbox"], min_length=1, max_length=10)
    subfolders: bool = False
    since_days: int | None = Field(default=None, ge=1, le=3650)
    received_from: date | None = None
    received_to: date | None = None
    max_items: int = Field(default=0, ge=0, le=10000)

    @field_validator("accounts")
    @classmethod
    def _accounts(cls, v: list[str]) -> list[str]:
        bad = [a for a in v if not _ACCOUNT.match(a.strip())]
        if bad:
            raise ValueError(f"not e-mail addresses: {bad}")
        return [a.strip() for a in v]

    @field_validator("folders")
    @classmethod
    def _folders(cls, v: list[str]) -> list[str]:
        bad = [f for f in v if not _FOLDER.match(f.strip())]
        if bad:
            raise ValueError(f"invalid folder names: {bad}")
        return [f.strip() for f in v]

    @model_validator(mode="after")
    def _period(self) -> MailboxRequest:
        if (self.received_from is None) != (self.received_to is None):
            raise ValueError("received_from and received_to go together")
        if self.received_from and self.received_to and self.received_from > self.received_to:
            raise ValueError("received_from must not be after received_to")
        if self.received_from is None and self.since_days is None:
            self.since_days = 1
        return self

    def label(self) -> str:
        period = (f"{self.received_from}–{self.received_to}" if self.received_from else f"utolsó {self.since_days} nap")
        return f"{', '.join(self.accounts)} · {', '.join(self.folders)} · {period}"


def _argv(req: MailboxRequest, mode: str, **extra: str) -> list[str]:
    argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER),
            "-Script", str(OUTLOOK_BRIDGE_SCRIPT), "-Mode", mode, "-Accounts", ",".join(req.accounts),
            "-Folders", ",".join(req.folders), "-MaxItems", str(req.max_items), "-RepoRoot", str(BRIDGE_ROOT)]
    if req.subfolders:
        argv.append("-Subfolders")
    if req.received_from and req.received_to:
        # a régi szkript `[datetime]::Parse`-szal olvas; a záró nap teljes egészében benne legyen
        argv += ["-ReceivedFrom", f"{req.received_from}T00:00:00", "-ReceivedTo", f"{req.received_to}T23:59:59"]
    else:
        argv += ["-SinceDays", str(req.since_days)]
    for k, v in extra.items():
        argv += [f"-{k}", v]
    return argv


def _subprocess_runner(argv: list[str], timeout: int) -> tuple[int, str, str]:
    p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    dec = lambda b: b.decode("utf-8", errors="replace")  # noqa: E731
    return p.returncode, dec(p.stdout), dec(p.stderr)


def _tail(text: str, n: int = 12) -> list[str]:
    return [line for line in text.strip().splitlines() if line.strip()][-n:]


_PS_ERROR = re.compile(r"FullyQualifiedErrorId\s*:\s*(.+)$", re.MULTILINE)


def _error_text(err: str, out: str, code: int) -> str:
    """A PowerShell-hibából az ember számára érthető rész: a dobott üzenet (`FullyQualifiedErrorId`), különben az utolsó sorok."""
    m = _PS_ERROR.search(err or "")
    if m:
        return m.group(1).strip()
    return "; ".join(_tail(err or out, 4)) or f"bridge exit {code}"


def count(req: MailboxRequest, *, runner: Runner | None = None) -> dict[str, Any]:
    """Ingyenes darabszám-előnézet: hány levél esik az időszakba, ebből hány volt már beolvasva, és hányat töltene le.

    A régi szkript `eligible` értéke a letöltendő (még nem beolvasott) levelek száma, az időszak összes levele a
    `counts.mail` (065: a felület korábban az `eligible`-t írta ki összesként)."""
    code, out, err = (runner or _subprocess_runner)(_argv(req, "count"), COUNT_TIMEOUT_S)
    lines = [line for line in out.strip().splitlines() if line.strip().startswith("{")]
    if code != 0 or not lines:
        raise BridgeError(_error_text(err, out, code))
    raw = json.loads(lines[-1])
    counts = raw.get("counts") or {}
    return {"request": req.model_dump(mode="json"), "label": req.label(), "eligible": int(raw.get("eligible") or 0),
            "in_period": int(counts.get("mail") or 0),
            "already_read": int(counts.get("skippedSeen") or 0), "scanned": int(counts.get("scanned") or 0),
            "window": {"from": raw.get("received_from"), "to": raw.get("received_to")},
            "accounts": [{"account": a.get("account"), "eligible": (a.get("counts") or {}).get("mail")} for a in raw.get("accounts") or []]}


def fetch(req: MailboxRequest, *, actor: str, runner: Runner | None = None, inbox_root: Path | None = None) -> dict[str, Any]:
    """Letöltés a saját, ideiglenes fogadón át; az új / megváltozott levelekből munkacsomag a levél-szándék recepttel."""
    token = secrets.token_urlsafe(24)
    stored: list[dict[str, Any]] = []
    lock = threading.Lock()

    def on_ingest(res: dict[str, Any], payload: dict[str, Any]) -> None:
        with lock:
            stored.append({"folder": Path(res["folder"]), "status": res["status"], "subject": str(payload.get("subject") or "")[:120]})

    httpd = ingest_server.make_server(0, inbox_root=inbox_root or ingest_server.INBOX_ROOT, token=token, on_ingest=on_ingest)
    thread = threading.Thread(target=httpd.serve_forever, name="mail-ingest", daemon=True)
    thread.start()
    interrupted: Exception | None = None
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/ingest/email"
        code, out, err = (runner or _subprocess_runner)(_argv(req, "fetch", OrchUrl=url, ApiToken=token), FETCH_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError) as exc:
        # 063: a megszakadt letöltés (időkorlát, leállított szkript) már megérkezett levelei se vesszenek el
        interrupted, code, out, err = exc, -1, "", f"{type(exc).__name__}: {exc}"
    finally:
        httpd.shutdown()
        httpd.server_close()
    if interrupted is not None and not stored:
        raise interrupted
    messages = [s["folder"] / "message.json" for s in stored]
    # 063: a már letöltött, de csomagba nem került levél is friss (pl. egy korábbi megszakadt letöltésből)
    packaged = work.packaged_sources([m for m, s in zip(messages, stored) if s["status"] == "duplicate"])
    fresh = list(dict.fromkeys(m for m, s in zip(messages, stored) if s["status"] in ("new", "changed") or m not in packaged))
    result: dict[str, Any] = {"label": req.label(), "exit_code": code, "log": _tail(out + "\n" + err),
                              "stored": len(stored), "new": sum(s["status"] == "new" for s in stored),
                              "changed": sum(s["status"] == "changed" for s in stored),
                              "duplicate": sum(s["status"] == "duplicate" for s in stored), "workpackage": None}
    if interrupted is not None:
        result["error"] = f"A letöltés megszakadt ({type(interrupted).__name__}); a megérkezett levelekből csomag készült."
    if code != 0 and not stored:
        raise BridgeError(_error_text(err, out, code))
    if fresh:
        result["workpackage"] = _workpackage(req, fresh, actor=actor)["id"]
    return result


def pdf_attachments(messages: list[Path]) -> dict[Path, Path]:
    """058 K5.2: a levelek fájlként meglévő PDF-csatolmányai (csatolmány → a levél `message.json`-ja). A csatolmány csak a
    megengedett helyről olvasható (`emails.load_message_dir` ellenőrzi); a kép-csatolmány most nem kerül be."""
    from jav import emails

    out: dict[Path, Path] = {}
    for m in messages:
        for a in emails.load_message_dir(Path(m).parent).attachments:
            if a.path and a.ext == ".pdf":
                out.setdefault(Path(a.path).resolve(), Path(m))
    return out


def missing_attachments(wp: dict[str, Any]) -> list[Path]:
    """A csomag leveleinek azon PDF-csatolmányai, amelyek még nem tételei a csomagnak (058 előtti levélcsomag)."""
    mails = [Path(i["source_path"]) for i in wp["items"] if i["kind"] == "email"]
    have = {Path(i["source_path"]).resolve() for i in wp["items"] if i["kind"] == "document"}
    return [p for p in pdf_attachments(mails) if p not in have]


def add_attachments(wp_id: str, *, expected_revision: int) -> dict[str, Any]:
    """A levelek PDF-csatolmányai iratként a csomagba, a levélre mutatva (a csatolmány eredete). A levél-recept a
    csatolmányon a teljes irat-feldolgozást futtatja (058 K5.2, automatikus lánc). Nincs új csatolmány: változatlan csomag."""
    wp = work.get(wp_id)
    mails = [Path(i["source_path"]) for i in wp["items"] if i["kind"] == "email"]
    missing = set(missing_attachments(wp))
    if not missing:
        return wp
    item_of = {Path(i["source_path"]).resolve(): i["item_id"] for i in wp["items"] if i["kind"] == "email"}
    parents = {pdf: item_of[Path(msg).resolve()] for pdf, msg in pdf_attachments(mails).items() if pdf in missing}
    return work.add_items(wp_id, sorted(missing), kind="document", expected_revision=expected_revision, parents=parents)


_SCHEDULED_ACTOR = re.compile(r"^ütemezés \((.+)\)$")


def owner_of(actor: str) -> str:
    """065: a letöltésből készült csomag felelőse: az indító, ütemezett letöltésnél az ütemezést mentő felhasználó."""
    m = _SCHEDULED_ACTOR.match(actor)
    return m.group(1) if m else actor


def _workpackage(req: MailboxRequest, messages: list[Path], *, actor: str) -> dict[str, Any]:
    name = f"Postafiók: {', '.join(req.accounts)} · {datetime.now():%Y-%m-%d %H:%M}"
    wp = work.create_workpackage(name=name, source_kind="mailbox", source_ref=req.label(), owner=owner_of(actor))
    wp = work.add_items(wp["id"], messages, kind="email", expected_revision=0)
    wp = add_attachments(wp["id"], expected_revision=wp["revision"])  # 058 K5.2: a PDF-csatolmányok is (a levélre mutatva)
    r = work.recipe(EMAIL_RECIPE)
    params = {k: spec["default"] for k, spec in r["params"].items()}
    work.assign_recipe(wp["id"], EMAIL_RECIPE, params=params, expected_revision=0, actor=actor,
                       note="postafiók-letöltés után automatikusan (a futtatás kézi)")
    return work.get(wp["id"])


# --- letöltések és ütemezés (048 T2.2) ---------------------------------------------------------------------
# Minden letöltés (kézi vagy ütemezett) egy `mailbox_pulls` sor + egy `mail_pull` munkasor-feladat: a feldolgozó futtatja
# (`run_pull_job`), mert a letöltés percekig is tarthat; az állapot és az eredmény a soron látszik. Egy ütemezés =
# postafiók(ok) + mappák + visszatekintés (napok) + gyakoriság. A feldolgozó minden körben `tick()`-et hív: az esedékes
# ütemezéshez letöltést indít (időrésenként egyszer), és a következő időpontot előre lépteti. Hiba (pl. nem fut az
# Outlook) nem ismétlődik azonnal, a következő időpontban újra próbál.

PULL_JOB_KIND = "mail_pull"
DEFAULT_INTERVAL_MIN = 60  # 2026-09-28 döntés: óránként
DEFAULT_LOOKBACK_DAYS = 3  # az ütemezett olvasás ablaka; a már beolvasott levelet a szkript és a fogadó is kihagyja

store.register_schema("mailbox", """
CREATE TABLE IF NOT EXISTS mailbox_schedules (
    id           TEXT PRIMARY KEY,
    request      TEXT NOT NULL,                -- JSON: MailboxRequest (visszatekintés napokban)
    interval_min INTEGER NOT NULL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    actor        TEXT NOT NULL,
    next_at      TEXT NOT NULL,                -- UTC ISO
    last_at      TEXT,
    last_status  TEXT,                         -- ok | error
    last_result  TEXT,                         -- JSON: a letöltés összesítője vagy a hibaüzenet
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mailbox_pulls (
    id           TEXT PRIMARY KEY,
    schedule_id  TEXT,                         -- NULL = kézi letöltés
    request      TEXT NOT NULL,
    actor        TEXT NOT NULL,
    status       TEXT NOT NULL,                -- queued | running | ok | error
    result       TEXT,                         -- JSON: új / változott / ismételt levelek, munkacsomag; vagy hiba
    created_at   TEXT NOT NULL,
    finished_at  TEXT
);
""")


def _utc(dt: datetime | None = None) -> str:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def _schedule_row(row) -> dict[str, Any]:
    out = dict(row)
    out["request"] = json.loads(out["request"])
    out["last_result"] = json.loads(out["last_result"]) if out["last_result"] else None
    out["enabled"] = bool(out["enabled"])
    out["label"] = MailboxRequest.model_validate(out["request"]).label()
    return out


def schedules() -> list[dict[str, Any]]:
    with store.connect() as c:
        return [_schedule_row(r) for r in c.execute("SELECT * FROM mailbox_schedules ORDER BY created_at")]


def schedule(schedule_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM mailbox_schedules WHERE id=?", (schedule_id,)).fetchone()
    if row is None:
        raise KeyError(schedule_id)
    return _schedule_row(row)


def create_schedule(req: MailboxRequest, *, actor: str, interval_min: int = DEFAULT_INTERVAL_MIN,
                    enabled: bool = True) -> dict[str, Any]:
    """Új ütemezés; az első letöltés a következő feldolgozó-körben esedékes. Dátumtól-dátumig időszak itt nem értelmes."""
    if req.received_from is not None:
        raise ValueError("a schedule reads the last N days; a fixed date range is for one-off fetches")
    if not 15 <= interval_min <= 7 * 24 * 60:
        raise ValueError("interval_min must be between 15 minutes and 7 days")
    sid = f"mbx-{uuid.uuid4().hex[:10]}"
    now = _utc()
    with store.connect() as c:
        c.execute("INSERT INTO mailbox_schedules(id, request, interval_min, enabled, actor, next_at, created_at, updated_at)"
                  " VALUES (?,?,?,?,?,?,?,?)", (sid, req.model_dump_json(), interval_min, int(enabled), actor, now, now, now))
    return schedule(sid)


def update_schedule(schedule_id: str, *, enabled: bool | None = None, interval_min: int | None = None) -> dict[str, Any]:
    cur = schedule(schedule_id)
    if interval_min is not None and not 15 <= interval_min <= 7 * 24 * 60:
        raise ValueError("interval_min must be between 15 minutes and 7 days")
    en = cur["enabled"] if enabled is None else enabled
    iv = cur["interval_min"] if interval_min is None else interval_min
    # bekapcsoláskor azonnal esedékes; gyakoriság-változáskor a következő időpont az újhoz igazodik
    nxt = _utc() if (enabled and not cur["enabled"]) else cur["next_at"]
    if interval_min is not None and cur["last_at"]:
        nxt = _utc(datetime.fromisoformat(cur["last_at"]) + timedelta(minutes=iv))
    with store.connect() as c:
        c.execute("UPDATE mailbox_schedules SET enabled=?, interval_min=?, next_at=?, updated_at=? WHERE id=?",
                  (int(en), iv, nxt, _utc(), schedule_id))
    return schedule(schedule_id)


def delete_schedule(schedule_id: str) -> None:
    schedule(schedule_id)
    with store.connect() as c:
        c.execute("DELETE FROM mailbox_schedules WHERE id=?", (schedule_id,))


def request_pull(req: MailboxRequest, *, actor: str, schedule_id: str | None = None,
                 dedup_key: str | None = None) -> dict[str, Any]:
    """Letöltés sorba állítása (a feldolgozó futtatja). Ismételt `dedup_key`-nél a meglévő letöltést adja vissza."""
    from jav.runtime import queue

    pid = f"pull-{uuid.uuid4().hex[:10]}"
    # 063: a letöltés sora a feladat előtt jön létre — a feldolgozó már a felvétel pillanatában lefoglalhatja
    with store.connect() as c:
        c.execute("INSERT INTO mailbox_pulls(id, schedule_id, request, actor, status, created_at) VALUES (?,?,?,?,?,?)",
                  (pid, schedule_id, req.model_dump_json(), actor, "queued", _utc()))
    job = queue.enqueue(PULL_JOB_KIND, run_id=None, payload={"pull_id": pid}, dedup_key=dedup_key)
    if job.deduped:
        with store.connect() as c:
            c.execute("DELETE FROM mailbox_pulls WHERE id=?", (pid,))
        return pull(job.payload["pull_id"])
    return pull(pid)


def abandon_pull(pull_id: str, error: str) -> None:
    """063: a feldolgozó rendes lezárás nélkül hagyta el a letöltést (leállás, váratlan hiba): hibaként lezárva."""
    body = json.dumps({"error": error[:500]}, ensure_ascii=False)
    with store.connect() as c:
        row = c.execute("SELECT schedule_id FROM mailbox_pulls WHERE id=?", (pull_id,)).fetchone()
        if row is None:
            return
        c.execute("UPDATE mailbox_pulls SET status='error', result=?, finished_at=? WHERE id=?", (body, _utc(), pull_id))
        if row["schedule_id"]:
            c.execute("UPDATE mailbox_schedules SET last_at=?, last_status='error', last_result=?, updated_at=? WHERE id=?",
                      (_utc(), body, _utc(), row["schedule_id"]))


def _pull_row(row) -> dict[str, Any]:
    out = dict(row)
    out["request"] = json.loads(out["request"])
    out["result"] = json.loads(out["result"]) if out["result"] else None
    out["label"] = MailboxRequest.model_validate(out["request"]).label()
    return out


def pull(pull_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM mailbox_pulls WHERE id=?", (pull_id,)).fetchone()
    if row is None:
        raise KeyError(pull_id)
    return _pull_row(row)


def pulls(limit: int = 20) -> list[dict[str, Any]]:
    with store.connect() as c:
        return [_pull_row(r) for r in c.execute("SELECT * FROM mailbox_pulls ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))]


def known_accounts() -> list[str]:
    """A már használt postafiók-címek (058: választhatók, nem kell újra begépelni): az ütemezések és a sikeres letöltések
    címei, a legutóbb használt elöl, kisbetűs egyezéssel egyszer."""
    seen: dict[str, str] = {}
    with store.connect() as c:
        rows = [*c.execute("SELECT request FROM mailbox_pulls WHERE status='ok' ORDER BY created_at DESC, rowid DESC"),
                *c.execute("SELECT request FROM mailbox_schedules ORDER BY created_at DESC")]
    for r in rows:
        for a in json.loads(r["request"]).get("accounts") or []:
            seen.setdefault(str(a).strip().lower(), str(a).strip())
    return [v for v in seen.values() if v]


def tick(now: datetime | None = None) -> list[str]:
    """Az esedékes, bekapcsolt ütemezésekhez egy-egy letöltés (időrésenként egyszer); visszaadja a letöltések azonosítóit."""
    now = now or datetime.now(timezone.utc)
    out = []
    with store.connect() as c:
        due = c.execute("SELECT * FROM mailbox_schedules WHERE enabled=1 AND next_at<=?", (_utc(now),)).fetchall()
    for row in due:
        p = request_pull(MailboxRequest.model_validate_json(row["request"]), actor=f"ütemezés ({row['actor']})",
                         schedule_id=row["id"], dedup_key=f"{PULL_JOB_KIND}:{row['id']}:{row['next_at']}")
        with store.connect() as c:
            c.execute("UPDATE mailbox_schedules SET next_at=?, updated_at=? WHERE id=?",
                      (_utc(now + timedelta(minutes=row["interval_min"])), _utc(now), row["id"]))
        out.append(p["id"])
    return out


def run_pull_job(payload: dict[str, Any], *, runner: Runner | None = None, inbox_root: Path | None = None) -> dict[str, Any]:
    """Egy letöltés a feldolgozóban. A hibát a letöltésre (és az ütemezésre) írja, nem dob: a munkasor ne ismételje."""
    p = pull(payload["pull_id"])
    with store.connect() as c:
        c.execute("UPDATE mailbox_pulls SET status='running' WHERE id=?", (p["id"],))
    try:
        res = fetch(MailboxRequest.model_validate(p["request"]), actor=p["actor"], runner=runner, inbox_root=inbox_root)
        status, result = "ok", {k: res[k] for k in ("new", "changed", "duplicate", "workpackage", "log")}
        if res.get("error"):  # 063: megszakadt letöltés — a megérkezett levelek csomagba kerültek, de a hiba látszik
            status, result["error"] = "error", res["error"]
    except (BridgeError, subprocess.TimeoutExpired, OSError) as exc:
        status, result = "error", {"error": str(exc)[:500]}
    except Exception as exc:  # noqa: BLE001 - 063: minden hiba a letöltésen látszik, a feldolgozó nem áll le miatta
        log.exception("mailbox pull %s failed", p["id"])
        status, result = "error", {"error": f"{type(exc).__name__}: {exc}"[:500]}
    body = json.dumps(result, ensure_ascii=False)
    with store.connect() as c:
        c.execute("UPDATE mailbox_pulls SET status=?, result=?, finished_at=? WHERE id=?", (status, body, _utc(), p["id"]))
        if p["schedule_id"]:
            c.execute("UPDATE mailbox_schedules SET last_at=?, last_status=?, last_result=?, updated_at=? WHERE id=?",
                      (_utc(), status, body, _utc(), p["schedule_id"]))
    return {"status": status, **result}


# --- levél-tétel az ellenőrző felületen (048 T2.3) ---------------------------------------------------------------


def intent_name(key: str | None) -> str | None:
    """A szándék magyar neve a regiszterből (ismeretlen kulcsnál maga a kulcs)."""
    from jav import intents

    return (intents.BY_KEY[key].display_name if key in intents.BY_KEY else key) if key else None


def next_flow_labels() -> dict[str, str]:
    """A javasolt következő lépések magyar neve (058 K5.1): a rögzített kódoké a `configs/datasets.json`-ból, az
    „adatkinyerés a csatolmányból” típusonként az irattípus nevével. A felület ugyanezt a saját szótárával fordítja."""
    from jav import cfg

    out = dict(cfg.load("datasets")["labels"]["next_flow"])
    for key, name in cfg.load("field_labels")["doc_types"].items():
        out[f"m2:{key}"] = f"Adatkinyerés a csatolmányból ({name})"
    return out


def email_result_for(flow_run_id: str, message_id: str) -> tuple[dict[str, Any] | None, bool]:
    """A futás levél-eredménye és hogy ettől a futástól van-e. Elsőként a futás saját sora (058); a 058 előtti futásnál az
    `emails` sor, ha ettől a futástól való; különben a levél legutóbbi eredménye (`from_this_run=False`, a felület jelzi)."""
    own = store.email_result(flow_run_id)
    if own is not None:
        return own, True
    with store.connect() as c:
        row = c.execute("SELECT * FROM emails WHERE message_id=?", (message_id,)).fetchone()
    if row is None:
        return None, False
    out = dict(row)
    out["signals"] = json.loads(out["signals"]) if out["signals"] else None
    out["attachments"] = json.loads(out["attachments"] or "[]")
    out["body"] = None
    return out, row["run_id"] == flow_run_id


def effective_email_result(res: dict[str, Any], corrected_intent: str | None) -> dict[str, Any]:
    """A levél-eredmény a kézi javítással (058 K5.1): a javított szándék az erősebb, a továbbirányítás ebből számolódik
    kódban (a gépi jelek — pl. beszúrt utasítás — változatlanul számítanak). A gépi szándék megmarad (`machine_intent`)."""
    from jav import policy
    from jav.emails import Attachment, is_bookkeeping_file

    signals = {k: v for k, v in (res.get("signals") or {}).items() if k != "scores"}
    # a 048 előtti futások a levél mappájának nyilvántartó fájlját is csatolmányként tárolták: ez nem csatolmány
    atts = [a for a in res.get("attachments") or [] if not is_bookkeeping_file(str(a.get("filename") or ""))]
    out = {"intent": res.get("intent"), "intent_label": intent_name(res.get("intent")), "confidence": res.get("intent_conf"),
           "next_flow": res.get("next_flow"), "attachments": atts, "signals": signals,
           "corrected": False, "machine_intent": res.get("intent")}
    if corrected_intent and corrected_intent != res.get("intent"):
        atts = [Attachment.model_validate(a) for a in out["attachments"]]
        out.update(intent=corrected_intent, intent_label=intent_name(corrected_intent), corrected=True,
                   next_flow=policy.email_next_flow(corrected_intent, 1.0, atts, {corrected_intent: 1.0}, signals))
    elif corrected_intent:
        out["corrected"] = True  # a gépi szándékot ember megerősítette
    return out


def task_view(flow_run_id: str, raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """058 K5.3: a feladatjavaslat a döntésekkel (None = a futás nem kért javaslatot)."""
    tasks = (raw or {}).get("tasks")
    if not tasks:
        return None
    decisions = store.email_task_decisions(flow_run_id)
    items = [{**t, "index": n, "decision": decisions.get(n)} for n, t in enumerate(tasks.get("tasks") or [])]
    return {"status": tasks.get("status"), "reason": tasks.get("reason"), "error": tasks.get("error"), "tasks": items,
            "rejected": tasks.get("rejected") or []}


def decide_task(run_id: str, item_id: str, index: int, *, decision: str, actor: str, note: str | None = None) -> dict[str, Any]:
    """Emberi döntés egy feladatjavaslatról (elfogad / elvet). Ha a levél minden javaslatáról van döntés, a futás saját
    „javaslat vár döntésre” teendője lezárul (a döntések a lezárás tartalmában). Jóváhagyott futáson nem módosítható."""
    run = work.get_run(run_id)
    if run["approval"]:
        raise work.RevisionConflict(f"run {run_id} is approved; task decisions are frozen")
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id and i.get("kind") == "email"), None)
    if item is None:
        raise KeyError(item_id)
    flow_id = work.flow_run_id(run_id, item_id)
    view = task_view(flow_id, store.email_result(flow_id))
    if view is None or not 0 <= index < len(view["tasks"]):
        raise KeyError(f"task {index}")
    store.email_task_decide(flow_id, index, decision=decision, actor=actor, note=note)
    view = task_view(flow_id, store.email_result(flow_id))
    if all(t["decision"] for t in view["tasks"]):
        summary = {"decisions": [{"index": t["index"], "decision": t["decision"]["decision"]} for t in view["tasks"]]}
        for r in work.item_reasons(run_id, item_id, item)["run"]:
            if r["reason"].startswith("tasks:proposed"):
                work.resolve_reason(r["id"], actor=actor, resolution=summary, note="minden feladatjavaslatról döntöttek")
    return view


def mark_task_done(run_id: str, item_id: str, index: int, *, done: bool, actor: str) -> dict[str, Any]:
    """062 (döntés 2026-09-29): az elfogadott feladat kézzel elvégezve jelölhető, és visszavonható. A feladat a világban
    történik, ezért jóváhagyott futáson is jelölhető; elvetett vagy döntésre váró feladat nem végezhető el."""
    run = work.get_run(run_id)
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id and i.get("kind") == "email"), None)
    if item is None:
        raise KeyError(item_id)
    flow_id = work.flow_run_id(run_id, item_id)
    view = task_view(flow_id, store.email_result(flow_id))
    if view is None or not 0 <= index < len(view["tasks"]):
        raise KeyError(f"task {index}")
    if not store.email_task_done(flow_id, index, actor=actor, done=done):
        raise work.RevisionConflict(f"task {index} is not accepted; only an accepted task can be marked done")
    return task_view(flow_id, store.email_result(flow_id))  # type: ignore[return-value]


def email_item_view(item: dict[str, Any], flow_run_id: str, corrected_intent: str | None = None) -> dict[str, Any]:
    """A levél-tétel: a levél (a `message.json`-ból), a szándék-felismerés eredménye a kézi javítással, és hogy a levél
    szövegéből mennyit látott a felismerés (`body_coverage`, 058 K5.1)."""
    from jav.emails import EmailMessage, body_coverage

    path = Path(item["source_path"])
    msg = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    raw, from_this_run = email_result_for(flow_run_id, path.parent.name)
    res = {**effective_email_result(raw, corrected_intent), "from_this_run": from_this_run} if raw is not None else None
    body = msg.get("body") or ""
    coverage = (raw or {}).get("body") if from_this_run and (raw or {}).get("body") else body_coverage(
        EmailMessage(message_id=path.parent.name, body=body))
    return {"subject": msg.get("subject") or "", "sender": msg.get("sender"), "sender_name": msg.get("sender_name"),
            "to": msg.get("to") or [], "received_at": msg.get("received_at"), "mailbox": msg.get("mailbox"),
            "body": body[:20000], "attachments": [a.get("filename") for a in msg.get("attachments") or []],
            "body_coverage": coverage, "result": res, "tasks": task_view(flow_run_id, raw) if from_this_run else None}
