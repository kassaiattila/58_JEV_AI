"""Tartós adattár: SQLite (`store/jav.sqlite`, git-ignorált - PII-s adat).

Táblák (ROADMAP §2): documents, datapoints, emails, review_queue, ledger, golden_labels.
Séma-verzió a `meta` táblában; bővítés csak additív (új oszlop / tábla), soha nem destruktív migráció.
Egyszerű függvény-API, nincs ORM: minden író függvény egy tranzakció.
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
    """Futáshelyi adattár, globális átállítás nélkül."""
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
    """Modul-saját additív migráció (pl. új oszlop egy `register_schema`-val létrehozott táblán); minden kapcsolódáskor fut,
    ezért idempotensnek kell lennie."""
    _EXTRA_MIGRATIONS[name] = fn


def register_schema(name: str, ddl: str) -> None:
    """Egy modul saját táblái (pl. jav.runtime.queue); minden kapcsolódáskor idempotensen lefut (CREATE ... IF NOT EXISTS)."""
    _EXTRA_SCHEMAS[name] = ddl


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def current_path() -> Path:
    """Az éppen használt adattár fájlja (futáshelyi vagy alapértelmezett); mellé kerülnek a futtatási állapotfájlok."""
    return _scoped_path.get() or STORE_PATH


def active_path() -> Path:
    """A most használt adattár útvonala (gyorsítótár-kulcshoz: két adattár sora ne keveredjen)."""
    return _scoped_path.get() or STORE_PATH


# Adattáranként az utolsó szerkezet-ellenőrzés kulcsa: (SQLite `schema_version`, a regisztrált modul-sémák és -migrációk
# nevei). Ha egyik sem változott, a kapcsolódás nem futtatja újra a sémát és a migrációkat (061: előtte minden kapcsolódás
# ~7 ms volt, a munkacsomag-lista egy lekérése ~3 s). Külső sémaváltozás (pl. tábla eldobása) és új fájl is új kulcs.
_initialized: dict[str, tuple[int, tuple[str, ...]]] = {}


def _registry_key() -> tuple[str, ...]:
    return tuple(sorted(_EXTRA_SCHEMAS)) + ("|",) + tuple(sorted(_EXTRA_MIGRATIONS))


def _initialize(conn: sqlite3.Connection) -> None:
    """Séma + additív migrációk; idempotens."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    for ddl in _EXTRA_SCHEMAS.values():
        conn.executescript(ddl)
    try:
        _run_migrations(conn)
    except sqlite3.OperationalError as exc:
        # 063: a szolgáltatás és a feldolgozó egyszerre indulhat egy frissítés után; ha a másik közben felvette ugyanazt
        # az oszlopot, a második kör már nem talál teendőt (a migrációk a meglévő oszlopot kihagyják)
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
    """Egy kapcsolat a blokk összes `connect()` hívására ugyanazon az adattáron (061: a listanézetek és az eredmény-
    összeállítás elemenként nyitott-zárt kapcsolatai helyett; egy nyitás-zárás ~3 ms). A belső `connect()` blokkok
    ugyanúgy véglegesítenek (commit), hibánál visszavonnak (rollback), mint önálló kapcsolatnál. Egymásba ágyazva a
    külső kapcsolat marad; szálak között nem osztható (a kapcsolat a nyitó szálé)."""
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
    # híváskor oldjuk fel, hogy tesztben átirányítható legyen (monkeypatch jav.store.STORE_PATH)
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
    """Additív oszlop-migrációk meglévő adattáron (a CREATE TABLE IF NOT EXISTS nem bővít)."""
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
    if "provenance" not in dcols:  # 045: mezőnkénti forráshely (oldal, keretek, alternatívák)
        conn.execute("ALTER TABLE datapoints ADD COLUMN provenance TEXT")
    if "source_layer_id" not in dcols:  # 045: melyik szórétegre vonatkoznak a keretek
        conn.execute("ALTER TABLE datapoints ADD COLUMN source_layer_id TEXT")
    tcols = {r[1] for r in conn.execute("PRAGMA table_info(email_task_decisions)")}
    for col in ("done_by", "done_at"):  # 062: kézi „elvégezve” az elfogadott feladaton
        if tcols and col not in tcols:
            conn.execute(f"ALTER TABLE email_task_decisions ADD COLUMN {col} TEXT")
    ecols = {r[1] for r in conn.execute("PRAGMA table_info(email_results)")}
    if ecols and "tasks" not in ecols:  # 058 K5.3: a feladatjavaslat a levél-eredmény mellett
        conn.execute("ALTER TABLE email_results ADD COLUMN tasks TEXT")
    doc_cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    for col, typ in (("detail_type", "TEXT"), ("detail_conf", "REAL"), ("detail_method", "TEXT")):  # 047 T1.2: részletes típus
        if col not in doc_cols:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {typ}")
    # Régi (okonkénti sor nélküli) review-tételek okainak átvétele; a lezárt tétel okai a tétel státuszát kapják.
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


# --- írók ---------------------------------------------------------------------------------


def save_artifact(kind: str, artifact_id: str, payload: dict) -> None:
    """Változatlan futás-/értékelési bizonylat; azonos ismétlés megengedett, felülírás nem."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
    with connect() as c:
        c.commit()  # A connect séma-meta inicializálását lezárjuk a saját tranzakció előtt.
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
            # 047: a részletes típus egy újabb döntése (módszerrel) felülírja a korábbit, akkor is, ha most nyitva maradt
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
    """`record_conf`: a rekord leggyengébb Jev-ítélete (S-kar); `evidence`: mezőnként sor-szám + jelenlét-P (review-hoz)."""
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
    """058 K5.1: a levél-eredmény a futás saját soraként (ismételt futás nem írja felül a korábbit); K5.3: a feladatjavaslat."""
    with connect() as c:
        c.execute("INSERT INTO email_results(run_id, message_id, intent, intent_conf, signals, next_flow, attachments, body, tasks, created_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET message_id=excluded.message_id,"
                  " intent=excluded.intent, intent_conf=excluded.intent_conf, signals=excluded.signals, next_flow=excluded.next_flow,"
                  " attachments=excluded.attachments, body=excluded.body, tasks=excluded.tasks, created_at=excluded.created_at",
                  (run_id, message_id, intent, intent_conf, _json(signals) if signals is not None else None, next_flow,
                   _json(attachments), _json(body) if body is not None else None, _json(tasks) if tasks is not None else None, _now()))


def email_task_decide(run_id: str, index: int, *, decision: str, actor: str, note: str | None) -> None:
    if decision not in ("accepted", "rejected"):
        raise ValueError(f"unknown decision: {decision}")
    with connect() as c:
        c.execute("INSERT INTO email_task_decisions(run_id, task_index, decision, actor, note, decided_at) VALUES (?,?,?,?,?,?)"
                  " ON CONFLICT(run_id, task_index) DO UPDATE SET decision=excluded.decision, actor=excluded.actor,"
                  " note=excluded.note, decided_at=excluded.decided_at,"
                  # 062: az elvetés az elvégzést is törli (elvégezve csak elfogadott feladat lehet)
                  " done_by=CASE WHEN excluded.decision='accepted' THEN done_by END,"
                  " done_at=CASE WHEN excluded.decision='accepted' THEN done_at END", (run_id, index, decision, actor, note, _now()))


def email_task_done(run_id: str, index: int, *, actor: str, done: bool) -> bool:
    """062: az elfogadott feladat elvégezve (vagy vissza); False, ha a feladat nincs elfogadva."""
    with connect() as c:
        cur = c.execute("UPDATE email_task_decisions SET done_by=?, done_at=? WHERE run_id=? AND task_index=? AND decision='accepted'",
                        (actor if done else None, _now() if done else None, run_id, index))
        return cur.rowcount == 1


def email_task_decisions(run_id: str) -> dict[int, dict[str, Any]]:
    with connect() as c:
        return {r["task_index"]: dict(r) for r in c.execute("SELECT * FROM email_task_decisions WHERE run_id=?", (run_id,))}


def email_result(run_id: str) -> dict[str, Any] | None:
    """Egy folyamat-futás levél-eredménye (None, ha a futás még nem mentette, vagy 058 előtti)."""
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
    """M3: egy levél egy sor; újrafuttatásnál felülírjuk (a run_id mutatja, melyik futásból)."""
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
    """A tétel oklistája = a nyitott okai (066: két futás ugyanazon oka egyszer szerepel); ha nincs több nyitott ok, a
    tétel is lezárul."""
    open_reasons = list(dict.fromkeys(r["reason"] for r in c.execute(
        "SELECT reason FROM review_reasons WHERE review_id=? AND status='open' ORDER BY id", (review_id,))))
    if open_reasons:
        c.execute("UPDATE review_queue SET reasons=? WHERE id=?", (_json(open_reasons), review_id))
    else:
        c.execute("UPDATE review_queue SET reasons='[]', status=?, decided_at=? WHERE id=? AND status='open'",
                  (closing_status, _now(), review_id))


# 066 Á06 (döntés 2026-09-29): a még jóvá nem hagyott éles futás okai rögzítettek: másik futás nem veszi át és nem zárja le
# őket, így a korábbi éles futás nem hagyható jóvá ellenőrzés nélkül. A futásokat a munkaréteg ismeri (`jav/work.py`), ezért
# az ellenőrzést ő regisztrálja: `(kapcsolat, futás-azonosító) -> rögzített-e`. Nélküle (régi hívók) nincs rögzítés.
_pinned_run_check: Callable[[sqlite3.Connection, str], bool] | None = None


def begin_immediate(c: sqlite3.Connection) -> None:
    """Írási zár a blokk elején, még az első olvasás előtt (066 Á32): az olvasás–döntés–írás így két párhuzamos hívás
    között sem keveredik. Az addigi, még nem véglegesített munkát előbb lezárja (mint a `connect()` blokk vége)."""
    if c.in_transaction:
        c.commit()
    c.execute("BEGIN IMMEDIATE")


def set_pinned_run_check(fn: Callable[[sqlite3.Connection, str], bool] | None) -> None:
    global _pinned_run_check
    _pinned_run_check = fn


def _run_of(flow_run_id: str | None) -> str:
    """A futás azonosítója egy tétel-folyamat azonosítójából (`<futás>:<tétel>[-lépcső]` → `<futás>`)."""
    return (flow_run_id or "").split(":", 1)[0]


def _pinned_for(c: sqlite3.Connection, reason_run_id: str | None, acting_run_id: str | None) -> bool:
    """Az ok egy MÁSIK, rögzített futásé: a most dolgozó futás (vagy ismeretlen szereplő) nem veheti át, nem zárhatja le."""
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
    """Egy alanyhoz egy nyitott tétel, okonként külön sorral.

    Az új okok hozzáadódnak (duplikátum nélkül); más lépés okai érintetlenek maradnak. Ha `producer` meg van adva,
    ugyanannak a lépésnek az új listában már nem szereplő nyitott okai `superseded`-dé válnak (újrafuttatás).
    `producer=None` tisztán additív (a régi hívók viselkedése, mínusz a felülírás). 066 Á06: egy másik, még jóvá nem
    hagyott éles futás okát ez a futás nem veszi át és nem írja felül; ugyanarra az okra saját sort kap.
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
                # 045: az újra felvetett nyitott ok a legutóbbi felvevő futásé (a futás saját teendői ebből számolódnak)
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
    """Nyitott okok lezárása egy alanyon: az `reason_prefix`-szel kezdődő és/vagy a `producer` által felvett okok
    (szűrő nélkül mind). Más okok nyitva maradnak; a tétel csak az utolsó nyitott okkal zárul. Visszaadja a lezárt okok számát.
    066 Á06: `run_id` a lezárást végző futás; egy másik, még jóvá nem hagyott éles futás okát nem zárja le."""
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
    """Emberi döntés egyetlen okra: szerző, tartalom, megjegyzés. Már lezárt ok nem zárható újra (ValueError)."""
    with connect() as c:
        begin_immediate(c)
        row = c.execute("SELECT review_id, status FROM review_reasons WHERE id=?", (reason_id,)).fetchone()
        if row is None or row["status"] != "open":
            raise ValueError(f"review reason {reason_id} is not open")
        c.execute("UPDATE review_reasons SET status='resolved', actor=?, resolution=?, note=?, closed_at=? WHERE id=?",
                  (actor, _json(resolution) if resolution is not None else None, note, _now(), reason_id))
        _sync_review_item(c, int(row["review_id"]), closing_status="resolved")


def review_open_reasons(subject_kind: str, subject_id: str) -> list[dict[str, Any]]:
    """Egy alany nyitott okai (id, reason, producer, run_id), felvételi sorrendben."""
    with connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT r.id, r.reason, r.producer, r.run_id FROM review_reasons r JOIN review_queue q ON q.id = r.review_id"
            " WHERE q.subject_kind=? AND q.subject_id=? AND r.status='open' ORDER BY r.id", (subject_kind, subject_id))]


def review_open_reasons_many(subjects: list[tuple[str, str]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Több alany nyitott okai egy kapcsolattal (061: a listanézetek alanyonkénti lekérdezése helyett); minden kért alany
    szerepel a kimenetben, ok nélkül üres listával. Az okok sorrendje alanyonként ugyanaz, mint a `review_open_reasons`-é."""
    wanted = list(dict.fromkeys(subjects))
    out: dict[tuple[str, str], list[dict[str, Any]]] = {s: [] for s in wanted}
    if not wanted:
        return out
    with connect() as c:
        for kind in {k for k, _ in wanted}:
            ids = [i for k, i in wanted if k == kind]
            for start in range(0, len(ids), 500):  # az SQLite paraméterkorlátja alatt
                chunk = ids[start:start + 500]
                for r in c.execute(
                    "SELECT q.subject_id, r.id, r.reason, r.producer, r.run_id FROM review_reasons r"
                    " JOIN review_queue q ON q.id = r.review_id"
                    f" WHERE q.subject_kind=? AND q.subject_id IN ({','.join('?' * len(chunk))}) AND r.status='open'"
                    " ORDER BY r.id", (kind, *chunk)):
                    row = dict(r)
                    out[(kind, row.pop("subject_id"))].append(row)
    return out


# --- olvasók ------------------------------------------------------------------------------


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
