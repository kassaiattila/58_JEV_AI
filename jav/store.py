"""Durable store: SQLite (`store/jav.sqlite`, git-ignored - contains PII).

Core tables (ROADMAP §2): documents, datapoints, emails, review_queue, ledger, golden_labels.
Schema version in the `meta` table; extensions are additive only (new column / table), never a destructive migration.
Simple function API, no ORM: every writer function is one transaction.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from jav.config import STORE_PATH

SCHEMA_VERSION = 1
_scoped_path: ContextVar[Path | None] = ContextVar("jav_scoped_store", default=None)


@contextmanager
def use_store(path: Path):
    """Run-local store, without switching the global one."""
    token = _scoped_path.set(path)
    try:
        yield
    finally:
        _scoped_path.reset(token)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
    kind TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (kind, artifact_id)
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,          -- sha256 a fájl tartalmáról
    source_path   TEXT NOT NULL,
    source_email  TEXT,                      -- emails.message_id, ha e-mailből jött
    doc_type      TEXT,                      -- M1 kategória (invoice_hu, utility_bill_hu, ...)
    type_conf     REAL,
    issuer_hu     REAL,                      -- P(kiállító magyar)
    has_text      INTEGER,
    page_count    INTEGER,
    year          INTEGER,
    first_seen    TEXT NOT NULL,
    last_run_id   TEXT
);

CREATE TABLE IF NOT EXISTS datapoints (
    run_id        TEXT NOT NULL,
    doc_id        TEXT NOT NULL,
    doc_type      TEXT NOT NULL,
    arm           TEXT NOT NULL,             -- S | G
    datapoints    TEXT NOT NULL,             -- JSON (a típus sémája szerint)
    field_conf    TEXT NOT NULL,             -- JSON: mező -> confidence (S) / max flag (G)
    validation    TEXT NOT NULL,             -- JSON: CheckResult lista
    route         TEXT,
    review_reasons TEXT NOT NULL,            -- JSON lista
    final_status  TEXT,
    config_hash   TEXT,
    record_conf   REAL,                      -- a rekord leggyengebb Jev-itelete (S-kar, jelenlet-Noullal)
    evidence      TEXT,                      -- JSON: mezo -> {line_no, present_p}
    provenance    TEXT,                      -- JSON: mezo -> forráshely (045, jav/grounding.py)
    source_layer_id TEXT,                    -- a szóréteg (045, jav/source_layer.py)
    created_at    TEXT NOT NULL,
    PRIMARY KEY (run_id, doc_id)
);
CREATE INDEX IF NOT EXISTS ix_datapoints_doc ON datapoints(doc_id, created_at);

CREATE TABLE IF NOT EXISTS emails (
    message_id    TEXT PRIMARY KEY,
    mailbox       TEXT,
    sender        TEXT,
    subject       TEXT,
    received_at   TEXT,
    body_excerpt  TEXT,
    attachments   TEXT NOT NULL,             -- JSON: doc_id lista
    intent        TEXT,
    intent_conf   REAL,
    signals       TEXT,                      -- JSON: Noul-jelek
    next_flow     TEXT,
    run_id        TEXT,
    created_at    TEXT NOT NULL
);

-- 058 K5.1: a levél-eredmény futásonként (a folyamat-azonosítóval), mint a datapoints az iratoknál; az `emails` sor
-- levelenként a legutóbbi eredmény marad
CREATE TABLE IF NOT EXISTS email_results (
    run_id        TEXT PRIMARY KEY,          -- a tétel folyamat-azonosítója (<futás>:<tétel>)
    message_id    TEXT NOT NULL,
    intent        TEXT,
    intent_conf   REAL,
    signals       TEXT,                      -- JSON
    next_flow     TEXT,
    attachments   TEXT NOT NULL,             -- JSON: csatolmányok felismeréssel (doc_id, doc_type, status)
    body          TEXT,                      -- JSON: a levél szövegéből látott rész (emails.body_coverage)
    tasks         TEXT,                      -- JSON: 058 K5.3 feladatjavaslat a kapu után (NULL = nem kértük)
    created_at    TEXT NOT NULL
);

-- 058 K5.3: emberi döntés a feladatjavaslatról (javaslatonként; a legutóbbi döntés érvényes, a korábbi a naplóban)
CREATE TABLE IF NOT EXISTS email_task_decisions (
    run_id        TEXT NOT NULL,             -- a levél folyamat-azonosítója (email_results.run_id)
    task_index    INTEGER NOT NULL,
    decision      TEXT NOT NULL,             -- accepted | rejected
    actor         TEXT NOT NULL,
    note          TEXT,
    decided_at    TEXT NOT NULL,
    done_by       TEXT,                      -- 062: az elfogadott feladatot ki jelölte elvégzettnek
    done_at       TEXT,
    PRIMARY KEY (run_id, task_index)
);

CREATE TABLE IF NOT EXISTS review_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_kind  TEXT NOT NULL,             -- document | email
    subject_id    TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    reasons       TEXT NOT NULL,             -- JSON lista
    payload       TEXT,                      -- JSON: S-G diff, flagek, stb.
    status        TEXT NOT NULL DEFAULT 'open',
    decision      TEXT,                      -- JSON: a kézi döntés
    created_at    TEXT NOT NULL,
    decided_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_review_open ON review_queue(status, created_at);

-- Okonkénti teendő (040 K1, F04): a review_queue.reasons JSON csak a nyitott okok tükre; a tétel akkor zárul,
-- ha az utolsó nyitott oka is lezárult. producer = a felvevő lépés (detect, m2, email_intent, ...; 'legacy' = régi sor).
CREATE TABLE IF NOT EXISTS review_reasons (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id     INTEGER NOT NULL REFERENCES review_queue(id),
    reason        TEXT NOT NULL,
    producer      TEXT NOT NULL,
    run_id        TEXT,
    status        TEXT NOT NULL DEFAULT 'open',   -- open | resolved | superseded
    actor         TEXT,                          -- emberi döntésnél ki döntött
    resolution    TEXT,                          -- JSON: a döntés tartalma
    note          TEXT,
    created_at    TEXT NOT NULL,
    closed_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_review_reasons_item ON review_reasons(review_id, status);

CREATE TABLE IF NOT EXISTS ledger (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    step          TEXT NOT NULL,
    provider      TEXT NOT NULL,             -- jev | openai
    model         TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    seconds       REAL,
    cached        INTEGER NOT NULL DEFAULT 0,
    cache_key     TEXT,
    config_hash   TEXT,                      -- a hívási hely konfig-verziója (jav/cfg.py)
    error         TEXT,                      -- SDK-hiba rövid alakja (pl. TypeSafeRateLimitError:429:retry_after_ms=1500), különben NULL
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ledger_run ON ledger(run_id);

CREATE TABLE IF NOT EXISTS golden_labels (
    doc_id        TEXT NOT NULL,
    field         TEXT NOT NULL,
    value         TEXT,                      -- JSON
    source        TEXT NOT NULL,             -- review | agreement | imported
    created_at    TEXT NOT NULL,
    PRIMARY KEY (doc_id, field)
);
"""


_EXTRA_SCHEMAS: dict[str, str] = {}
_EXTRA_MIGRATIONS: dict[str, Any] = {}


def register_migration(name: str, fn: Any) -> None:
    """A module's own additive migration (e.g. a new column on a table created with `register_schema`); it can run on
    any connection (see `_initialized`), so it must be idempotent."""
    _EXTRA_MIGRATIONS[name] = fn


def register_schema(name: str, ddl: str) -> None:
    """A module's own tables (e.g. jav.runtime.queue); runs idempotently when connecting (CREATE ... IF NOT EXISTS)."""
    _EXTRA_SCHEMAS[name] = ddl


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def current_path() -> Path:
    """The file of the store currently in use (run-local or default); the runtime state files are placed next to it."""
    return _scoped_path.get() or STORE_PATH


def active_path() -> Path:
    """Path of the store currently in use (for cache keys, so that rows of two stores do not mix)."""
    return _scoped_path.get() or STORE_PATH


# Per store, the key of the last structure check: (SQLite `schema_version`, the names of the registered module schemas
# and migrations). If neither has changed, connecting does not re-run the schema and the migrations (061: before this,
# every connection took ~7 ms and one fetch of the work package list ~3 s). An external schema change (e.g. a dropped
# table) and a new file also give a new key.
_initialized: dict[str, tuple[int, tuple[str, ...]]] = {}


def _registry_key() -> tuple[str, ...]:
    return tuple(sorted(_EXTRA_SCHEMAS)) + ("|",) + tuple(sorted(_EXTRA_MIGRATIONS))


def _initialize(conn: sqlite3.Connection) -> None:
    """Schema + additive migrations; idempotent."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    for ddl in _EXTRA_SCHEMAS.values():
        conn.executescript(ddl)
    try:
        _run_migrations(conn)
    except sqlite3.OperationalError as exc:
        # 063: the service and the worker may start at the same time after an update; if the other one has added the
        # same column meanwhile, the second round finds nothing left to do (the migrations skip existing columns)
        if "duplicate column name" not in str(exc):
            raise
        conn.rollback()
        _run_migrations(conn)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.commit()


def _run_migrations(conn: sqlite3.Connection) -> None:
    _migrate(conn)
    for fn in _EXTRA_MIGRATIONS.values():
        fn(conn)


_shared: ContextVar[tuple[str, sqlite3.Connection] | None] = ContextVar("jav_shared_connection", default=None)


@contextmanager
def session() -> Iterator[None]:
    """One connection for all `connect()` calls in the block on the same store (061: instead of the per-element
    open/close connections of the list views and the result assembly; one open-close costs ~3 ms). The inner
    `connect()` blocks commit, and roll back on error, just as with a standalone connection. When nested, the outer
    connection is kept; it cannot be shared between threads (the connection belongs to the thread that opened it)."""
    if _shared.get() is not None:
        yield
        return
    path = _scoped_path.get() or STORE_PATH
    with connect(path) as conn:
        token = _shared.set((str(path), conn))
        try:
            yield
        finally:
            _shared.reset(token)


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    # resolved at call time so that tests can redirect it (monkeypatch jav.store.STORE_PATH)
    path = path or _scoped_path.get() or STORE_PATH
    shared = _shared.get()
    if shared is not None and shared[0] == str(path):
        try:
            yield shared[1]
            shared[1].commit()
        except BaseException:
            shared[1].rollback()
            raise
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        key = str(path)
        registry = _registry_key()
        if _initialized.get(key) != (conn.execute("PRAGMA schema_version").fetchone()[0], registry):
            _initialize(conn)
            _initialized[key] = (conn.execute("PRAGMA schema_version").fetchone()[0], registry)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive column migrations on an existing store (CREATE TABLE IF NOT EXISTS does not add columns)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ledger)")}
    if "config_hash" not in cols:
        conn.execute("ALTER TABLE ledger ADD COLUMN config_hash TEXT")
    if "error" not in cols:
        conn.execute("ALTER TABLE ledger ADD COLUMN error TEXT")
    dcols = {r[1] for r in conn.execute("PRAGMA table_info(datapoints)")}
    if "record_conf" not in dcols:
        conn.execute("ALTER TABLE datapoints ADD COLUMN record_conf REAL")
    if "evidence" not in dcols:
        conn.execute("ALTER TABLE datapoints ADD COLUMN evidence TEXT")
    if "provenance" not in dcols:  # 045: per-field source location (page, boxes, alternatives)
        conn.execute("ALTER TABLE datapoints ADD COLUMN provenance TEXT")
    if "source_layer_id" not in dcols:  # 045: which word layer the boxes refer to
        conn.execute("ALTER TABLE datapoints ADD COLUMN source_layer_id TEXT")
    tcols = {r[1] for r in conn.execute("PRAGMA table_info(email_task_decisions)")}
    for col in ("done_by", "done_at"):  # 062: manual "done" mark on an accepted task
        if tcols and col not in tcols:
            conn.execute(f"ALTER TABLE email_task_decisions ADD COLUMN {col} TEXT")
    ecols = {r[1] for r in conn.execute("PRAGMA table_info(email_results)")}
    if ecols and "tasks" not in ecols:  # 058 K5.3: the task proposal next to the email result
        conn.execute("ALTER TABLE email_results ADD COLUMN tasks TEXT")
    doc_cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    for col, typ in (("detail_type", "TEXT"), ("detail_conf", "REAL"), ("detail_method", "TEXT")):  # 047 T1.2: detailed type
        if col not in doc_cols:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {typ}")
    # Take over the reasons of old review items (no per-reason rows); a closed item's reasons get the item's status.
    legacy = conn.execute(
        "SELECT q.id, q.reasons, q.status, q.run_id, q.created_at, q.decided_at FROM review_queue q"
        " WHERE q.reasons NOT IN ('', '[]') AND NOT EXISTS (SELECT 1 FROM review_reasons r WHERE r.review_id = q.id)"
    ).fetchall()
    for row in legacy:
        for reason in dict.fromkeys(json.loads(row["reasons"] or "[]")):
            conn.execute(
                "INSERT INTO review_reasons(review_id, reason, producer, run_id, status, created_at, closed_at) VALUES (?,?,?,?,?,?,?)",
                (row["id"], reason, "legacy", row["run_id"], row["status"], row["created_at"],
                 None if row["status"] == "open" else row["decided_at"]),
            )


# --- writers ------------------------------------------------------------------------------


def save_artifact(kind: str, artifact_id: str, payload: dict) -> None:
    """Immutable run/evaluation record; an identical repeat is allowed, overwriting is not."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
    with connect() as c:
        c.commit()  # Commit the schema/meta initialisation done by connect before our own transaction.
        c.execute("BEGIN IMMEDIATE")
        previous = c.execute("SELECT payload FROM artifacts WHERE kind=? AND artifact_id=?", (kind, artifact_id)).fetchone()
        if previous:
            if previous["payload"] != encoded:
                raise ValueError("artifact identity already belongs to different content")
            return
        c.execute("INSERT INTO artifacts VALUES (?,?,?,?)", (kind, artifact_id, encoded, _now()))


def load_artifact(kind: str, artifact_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT payload FROM artifacts WHERE kind=? AND artifact_id=?", (kind, artifact_id)).fetchone()
    return json.loads(row["payload"]) if row else None


def ledger_add(
    *,
    run_id: str,
    step: str,
    provider: str,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_usd: float | None,
    seconds: float | None,
    cached: bool = False,
    cache_key: str | None = None,
    config_hash: str | None = None,
    error: str | None = None,
) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO ledger(run_id, step, provider, model, input_tokens, output_tokens, cost_usd, seconds, cached, cache_key, config_hash, error, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, step, provider, model, input_tokens, output_tokens, cost_usd, seconds, int(cached), cache_key, config_hash, error, _now()),
        )


def upsert_document(
    *,
    doc_id: str,
    source_path: str,
    has_text: bool | None = None,
    page_count: int | None = None,
    year: int | None = None,
    doc_type: str | None = None,
    type_conf: float | None = None,
    issuer_hu: float | None = None,
    source_email: str | None = None,
    run_id: str | None = None,
    detail_type: str | None = None,
    detail_conf: float | None = None,
    detail_method: str | None = None,
) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO documents(doc_id, source_path, source_email, doc_type, type_conf, issuer_hu, has_text, page_count, year, first_seen, last_run_id,"
            " detail_type, detail_conf, detail_method)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(doc_id) DO UPDATE SET"
            "  source_path=excluded.source_path,"
            "  source_email=COALESCE(excluded.source_email, documents.source_email),"
            "  doc_type=COALESCE(excluded.doc_type, documents.doc_type),"
            "  type_conf=COALESCE(excluded.type_conf, documents.type_conf),"
            "  issuer_hu=COALESCE(excluded.issuer_hu, documents.issuer_hu),"
            "  has_text=COALESCE(excluded.has_text, documents.has_text),"
            "  page_count=COALESCE(excluded.page_count, documents.page_count),"
            "  year=COALESCE(excluded.year, documents.year),"
            "  last_run_id=COALESCE(excluded.last_run_id, documents.last_run_id),"
            # 047: a newer detailed-type decision (with a method) overrides the earlier one, even if it is open now
            "  detail_type=CASE WHEN excluded.detail_method IS NOT NULL THEN excluded.detail_type ELSE documents.detail_type END,"
            "  detail_conf=CASE WHEN excluded.detail_method IS NOT NULL THEN excluded.detail_conf ELSE documents.detail_conf END,"
            "  detail_method=COALESCE(excluded.detail_method, documents.detail_method)",
            (
                doc_id,
                source_path,
                source_email,
                doc_type,
                type_conf,
                issuer_hu,
                None if has_text is None else int(has_text),
                page_count,
                year,
                _now(),
                run_id,
                detail_type,
                detail_conf,
                detail_method,
            ),
        )


def insert_datapoints(
    *,
    run_id: str,
    doc_id: str,
    doc_type: str,
    arm: str,
    datapoints: dict[str, Any],
    field_conf: dict[str, float],
    validation: list[dict[str, Any]],
    route: str | None,
    review_reasons: list[str],
    final_status: str | None,
    config_hash: str | None = None,
    record_conf: float | None = None,
    evidence: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    source_layer_id: str | None = None,
) -> None:
    """`record_conf`: the record's weakest JEV judgement (S path); `evidence`: per field, line number + presence P (for
    review)."""
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO datapoints(run_id, doc_id, doc_type, arm, datapoints, field_conf, validation, route, review_reasons, final_status, config_hash, record_conf, evidence, provenance, source_layer_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, doc_id, doc_type, arm, _json(datapoints), _json(field_conf), _json(validation), route, _json(review_reasons), final_status, config_hash,
             record_conf, _json(evidence) if evidence is not None else None, _json(provenance) if provenance is not None else None, source_layer_id, _now()),
        )


def upsert_email_result(*, run_id: str, message_id: str, intent: str | None, intent_conf: float | None,
                        signals: dict[str, Any] | None, next_flow: str | None, attachments: list[dict[str, Any]],
                        body: dict[str, Any] | None, tasks: dict[str, Any] | None = None) -> None:
    """058 K5.1: the email result as the run's own row (a repeated run does not overwrite the earlier one); K5.3: the
    task proposal."""
    with connect() as c:
        c.execute("INSERT INTO email_results(run_id, message_id, intent, intent_conf, signals, next_flow, attachments, body, tasks, created_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET message_id=excluded.message_id,"
                  " intent=excluded.intent, intent_conf=excluded.intent_conf, signals=excluded.signals, next_flow=excluded.next_flow,"
                  " attachments=excluded.attachments, body=excluded.body, tasks=excluded.tasks, created_at=excluded.created_at",
                  (run_id, message_id, intent, intent_conf, _json(signals) if signals is not None else None, next_flow,
                   _json(attachments), _json(body) if body is not None else None, _json(tasks) if tasks is not None else None, _now()))


def email_task_decide(run_id: str, index: int, *, decision: str, actor: str, note: str | None,
                      c: sqlite3.Connection | None = None) -> None:
    """`c` (086, audit N02): write inside the caller's transaction (which checks the approval first)."""
    if decision not in ("accepted", "rejected"):
        raise ValueError(f"unknown decision: {decision}")
    if c is None:
        with connect() as own:
            _email_task_decide(own, run_id, index, decision=decision, actor=actor, note=note)
    else:
        _email_task_decide(c, run_id, index, decision=decision, actor=actor, note=note)


def _email_task_decide(c: sqlite3.Connection, run_id: str, index: int, *, decision: str, actor: str, note: str | None) -> None:
    c.execute("INSERT INTO email_task_decisions(run_id, task_index, decision, actor, note, decided_at) VALUES (?,?,?,?,?,?)"
              " ON CONFLICT(run_id, task_index) DO UPDATE SET decision=excluded.decision, actor=excluded.actor,"
              " note=excluded.note, decided_at=excluded.decided_at,"
              # 062: rejecting also clears the done mark (only an accepted task can be done)
              " done_by=CASE WHEN excluded.decision='accepted' THEN done_by END,"
              " done_at=CASE WHEN excluded.decision='accepted' THEN done_at END", (run_id, index, decision, actor, note, _now()))


def email_task_done(run_id: str, index: int, *, actor: str, done: bool) -> bool:
    """062: marks an accepted task as done (or undoes it); False if the task is not accepted."""
    with connect() as c:
        cur = c.execute("UPDATE email_task_decisions SET done_by=?, done_at=? WHERE run_id=? AND task_index=? AND decision='accepted'",
                        (actor if done else None, _now() if done else None, run_id, index))
        return cur.rowcount == 1


def email_task_decisions(run_id: str) -> dict[int, dict[str, Any]]:
    with connect() as c:
        return {r["task_index"]: dict(r) for r in c.execute("SELECT * FROM email_task_decisions WHERE run_id=?", (run_id,))}


def email_result(run_id: str) -> dict[str, Any] | None:
    """The email result of one flow run (None if the run has not saved it yet, or it predates 058)."""
    with connect() as c:
        row = c.execute("SELECT * FROM email_results WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    for k in ("signals", "attachments", "body", "tasks"):
        out[k] = json.loads(out[k]) if out.get(k) is not None else None
    return out


def upsert_email(
    *,
    message_id: str,
    mailbox: str | None,
    sender: str | None,
    subject: str | None,
    received_at: str | None,
    body_excerpt: str | None,
    attachments: list[dict[str, Any]],
    intent: str | None,
    intent_conf: float | None,
    signals: dict[str, float] | None,
    next_flow: str | None,
    run_id: str | None,
) -> None:
    """M3: one row per email; overwritten on a re-run (run_id shows which run it came from)."""
    with connect() as c:
        c.execute(
            "INSERT INTO emails(message_id, mailbox, sender, subject, received_at, body_excerpt, attachments, intent, intent_conf,"
            " signals, next_flow, run_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(message_id) DO UPDATE SET"
            "  mailbox=excluded.mailbox, sender=excluded.sender, subject=excluded.subject, received_at=excluded.received_at,"
            "  body_excerpt=excluded.body_excerpt, attachments=excluded.attachments, intent=excluded.intent,"
            "  intent_conf=excluded.intent_conf, signals=excluded.signals, next_flow=excluded.next_flow, run_id=excluded.run_id,"
            "  created_at=excluded.created_at",
            (message_id, mailbox, sender, subject, received_at, body_excerpt, _json(attachments), intent, intent_conf,
             _json(signals) if signals is not None else None, next_flow, run_id, _now()),
        )


def _sync_review_item(c: sqlite3.Connection, review_id: int, closing_status: str = "superseded") -> None:
    """The item's reason list = its open reasons (066: the same reason from two runs appears once); when no open reason
    is left, the item is closed too."""
    open_reasons = list(dict.fromkeys(r["reason"] for r in c.execute(
        "SELECT reason FROM review_reasons WHERE review_id=? AND status='open' ORDER BY id", (review_id,))))
    if open_reasons:
        c.execute("UPDATE review_queue SET reasons=? WHERE id=?", (_json(open_reasons), review_id))
    else:
        c.execute("UPDATE review_queue SET reasons='[]', status=?, decided_at=? WHERE id=? AND status='open'",
                  (closing_status, _now(), review_id))


# 066 Á06 (decision of 2026-09-29): the reasons of a live run that is not yet approved are pinned: another run neither
# takes them over nor closes them, so the earlier live run cannot be approved without review. Runs are known to the work
# layer (`jav/work.py`), so it registers the check: `(connection, run ID) -> pinned?`. Without it (old callers) nothing
# is pinned.
_pinned_run_check: Callable[[sqlite3.Connection, str], bool] | None = None


def begin_immediate(c: sqlite3.Connection) -> None:
    """Write lock at the start of the block, before the first read (066 Á32): this way read–decide–write does not
    interleave even between two parallel calls. Any work not yet committed is committed first (like the end of a
    `connect()` block)."""
    if c.in_transaction:
        c.commit()
    c.execute("BEGIN IMMEDIATE")


def set_pinned_run_check(fn: Callable[[sqlite3.Connection, str], bool] | None) -> None:
    global _pinned_run_check
    _pinned_run_check = fn


def _run_of(flow_run_id: str | None) -> str:
    """The run ID from an item flow ID (`<run>:<item>[-stage]` → `<run>`)."""
    return (flow_run_id or "").split(":", 1)[0]


def _pinned_for(c: sqlite3.Connection, reason_run_id: str | None, acting_run_id: str | None) -> bool:
    """The reason belongs to ANOTHER, pinned run: the run acting now (or an unknown actor) may neither take it over nor
    close it."""
    if _pinned_run_check is None or not reason_run_id:
        return False
    if acting_run_id and _run_of(reason_run_id) == _run_of(acting_run_id):
        return False
    return _pinned_run_check(c, _run_of(reason_run_id))


def review_enqueue(
    *,
    subject_kind: str,
    subject_id: str,
    run_id: str,
    reasons: list[str],
    payload: dict[str, Any] | None = None,
    producer: str | None = None,
) -> int:
    """One open item per subject, with a separate row per reason.

    New reasons are added (without duplicates); other steps' reasons are left untouched. If `producer` is given, the
    same step's open reasons that are missing from the new list become `superseded` (re-run). `producer=None` is purely
    additive (the old callers' behaviour, minus the overwrite). 066 Á06: this run neither takes over nor overwrites a
    reason of another live run that is not yet approved; it gets its own row for the same reason.
    """
    who = producer or "legacy"
    with connect() as c:
        begin_immediate(c)
        existing = c.execute(
            "SELECT id FROM review_queue WHERE subject_kind=? AND subject_id=? AND status='open'", (subject_kind, subject_id)
        ).fetchone()
        if existing:
            review_id = int(existing["id"])
            c.execute("UPDATE review_queue SET run_id=?, payload=COALESCE(?, payload) WHERE id=?",
                      (run_id, _json(payload) if payload is not None else None, review_id))
        else:
            cur = c.execute(
                "INSERT INTO review_queue(subject_kind, subject_id, run_id, reasons, payload, status, created_at) VALUES (?,?,?,'[]',?,'open',?)",
                (subject_kind, subject_id, run_id, _json(payload) if payload is not None else None, _now()),
            )
            review_id = int(cur.lastrowid)
        wanted = list(dict.fromkeys(reasons))
        if producer is not None:
            stale = c.execute(
                f"SELECT id, run_id FROM review_reasons WHERE review_id=? AND producer=? AND status='open'"
                f" AND reason NOT IN ({','.join('?' * len(wanted)) or 'NULL'})",
                (review_id, who, *wanted),
            ).fetchall()
            for r in stale:
                if not _pinned_for(c, r["run_id"], run_id):
                    c.execute("UPDATE review_reasons SET status='superseded', closed_at=? WHERE id=?", (_now(), r["id"]))
        present: dict[str, int] = {}
        for r in c.execute("SELECT id, reason, run_id FROM review_reasons WHERE review_id=? AND status='open' ORDER BY id", (review_id,)):
            if r["reason"] not in present and not _pinned_for(c, r["run_id"], run_id):
                present[r["reason"]] = r["id"]
        for reason in wanted:
            if reason in present:
                # 045: a re-raised open reason belongs to the latest run that raised it
                # (the run's own to-dos are counted from this)
                c.execute("UPDATE review_reasons SET run_id=?, producer=? WHERE id=?", (run_id, who, present[reason]))
            else:
                c.execute("INSERT INTO review_reasons(review_id, reason, producer, run_id, status, created_at) VALUES (?,?,?,?,'open',?)",
                          (review_id, reason, who, run_id, _now()))
        _sync_review_item(c, review_id)
        return review_id


def review_close(
    *,
    subject_kind: str,
    subject_id: str,
    status: str = "superseded",
    reason_prefix: str | None = None,
    producer: str | None = None,
    run_id: str | None = None,
) -> int:
    """Closes open reasons on a subject: those starting with `reason_prefix` and/or raised by `producer` (all of them
    without a filter). Other reasons stay open; the item closes only with its last open reason. Returns the number of
    reasons closed. 066 Á06: `run_id` is the run doing the closing; it does not close a reason of another live run that
    is not yet approved."""
    with connect() as c:
        begin_immediate(c)
        items = [r["id"] for r in c.execute(
            "SELECT id FROM review_queue WHERE subject_kind=? AND subject_id=? AND status='open'", (subject_kind, subject_id))]
        closed = 0
        for review_id in items:
            rows = c.execute("SELECT id, reason, producer, run_id FROM review_reasons WHERE review_id=? AND status='open'",
                             (review_id,)).fetchall()
            ids = [r["id"] for r in rows
                   if (reason_prefix is None or r["reason"].startswith(reason_prefix)) and (producer is None or r["producer"] == producer)
                   and not _pinned_for(c, r["run_id"], run_id)]
            for i in ids:
                c.execute("UPDATE review_reasons SET status=?, closed_at=? WHERE id=?", (status, _now(), i))
            closed += len(ids)
            _sync_review_item(c, review_id, closing_status=status)
        return closed


def review_resolve(reason_id: int, *, actor: str, resolution: dict[str, Any] | None = None, note: str | None = None) -> None:
    """Human decision on a single reason: author, content, note. A reason already closed cannot be closed again
    (ValueError)."""
    with connect() as c:
        begin_immediate(c)
        row = c.execute("SELECT review_id, status FROM review_reasons WHERE id=?", (reason_id,)).fetchone()
        if row is None or row["status"] != "open":
            raise ValueError(f"review reason {reason_id} is not open")
        c.execute("UPDATE review_reasons SET status='resolved', actor=?, resolution=?, note=?, closed_at=? WHERE id=?",
                  (actor, _json(resolution) if resolution is not None else None, note, _now(), reason_id))
        _sync_review_item(c, int(row["review_id"]), closing_status="resolved")


def review_open_reasons(subject_kind: str, subject_id: str) -> list[dict[str, Any]]:
    """A subject's open reasons (id, reason, producer, run_id), in the order they were raised."""
    with connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT r.id, r.reason, r.producer, r.run_id FROM review_reasons r JOIN review_queue q ON q.id = r.review_id"
            " WHERE q.subject_kind=? AND q.subject_id=? AND r.status='open' ORDER BY r.id", (subject_kind, subject_id))]


def review_open_reasons_many(subjects: list[tuple[str, str]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Open reasons of several subjects over one connection (061: instead of the list views' per-subject queries); every
    requested subject appears in the output, with an empty list if it has no reason. Per subject the reasons are in the
    same order as in `review_open_reasons`."""
    wanted = list(dict.fromkeys(subjects))
    out: dict[tuple[str, str], list[dict[str, Any]]] = {s: [] for s in wanted}
    if not wanted:
        return out
    with connect() as c:
        for kind in {k for k, _ in wanted}:
            ids = [i for k, i in wanted if k == kind]
            for start in range(0, len(ids), 500):  # below SQLite's parameter limit
                chunk = ids[start:start + 500]
                for r in c.execute(
                    "SELECT q.subject_id, r.id, r.reason, r.producer, r.run_id FROM review_reasons r"
                    " JOIN review_queue q ON q.id = r.review_id"
                    f" WHERE q.subject_kind=? AND q.subject_id IN ({','.join('?' * len(chunk))}) AND r.status='open'"
                    " ORDER BY r.id", (kind, *chunk)):
                    row = dict(r)
                    out[(kind, row.pop("subject_id"))].append(row)
    return out


# --- readers ------------------------------------------------------------------------------


def stats() -> dict[str, Any]:
    with connect() as c:
        out: dict[str, Any] = {}
        for t in ("documents", "datapoints", "emails", "review_queue", "ledger", "golden_labels", "artifacts"):
            out[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        out["review_open"] = c.execute("SELECT COUNT(*) FROM review_queue WHERE status='open'").fetchone()[0]
        row = c.execute(
            "SELECT provider, COUNT(*) n, SUM(cached) cached, COALESCE(SUM(input_tokens),0) tok, COALESCE(SUM(cost_usd),0) usd FROM ledger GROUP BY provider"
        ).fetchall()
        out["ledger_by_provider"] = [dict(r) for r in row]
        out["ledger_errors"] = c.execute("SELECT COUNT(*) FROM ledger WHERE error IS NOT NULL").fetchone()[0]
        out["doc_types"] = [dict(r) for r in c.execute("SELECT doc_type, COUNT(*) n FROM documents GROUP BY doc_type ORDER BY n DESC").fetchall()]
        out["intents"] = [dict(r) for r in c.execute("SELECT intent, COUNT(*) n FROM emails GROUP BY intent ORDER BY n DESC").fetchall()]
        return out


def ledger_for_run(run_id: str) -> list[dict[str, Any]]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM ledger WHERE run_id=? ORDER BY id", (run_id,)).fetchall()]
