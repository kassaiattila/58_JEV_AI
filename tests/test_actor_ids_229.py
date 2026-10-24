"""Who acted, by a stable id (229, plan structure stage 1, SZ2c): every column naming the person who acted has the
person's id beside it.

Plain-language summary: when a person decides, approves, corrects, closes a to-do or changes a setting, the store
records the name shown and, beside it, the person's stable id: today `local:<name>`, with the company sign-in the
organisation's id. A renamed person, or two people of the same name, are then told apart. Rows written before keep
their name and get `local:<name>`. Two guard tests keep it so: every such column of the store has its id column, and
every statement that writes one writes the id too.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav.app import human_tasks, work, workflows
from jav.core import decisions, identity, store
from jav.domains.email import mailbox
from jav.service import api, service_shared

ROOT = Path(__file__).resolve().parents[1]
WHO = re.compile(r"^(actor|owner|assignee|[a-z_]+_by)$")
# The columns that name who acted in another way: the process core keeps the whole actor (JSON, its id included) or
# the id itself; a worker's claim names a process on a machine, not a person.
STRUCTURED = {
    ("process_cases", "started_by"), ("process_history", "actor"), ("process_inbox", "sent_by"),
    ("process_tasks", "assignee"), ("process_tasks", "opened_by"), ("process_tasks", "closed_by"),
    ("process_task_history", "actor"), ("jobs", "claimed_by"),
}


def _schema(tmp_path: Path) -> dict[str, list[str]]:
    with store.use_store(tmp_path / "schema.sqlite"), store.connect() as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: [r[1] for r in c.execute(f"PRAGMA table_info({t})")] for t in tables}


def _who_columns(schema: dict[str, list[str]]) -> dict[str, set[str]]:
    return {t: {col for col in cols if WHO.match(col) and (t, col) not in STRUCTURED} for t, cols in schema.items()}


# --- the shared helpers --------------------------------------------------------------------------------------------

def test_a_name_is_a_local_person_and_an_actor_stays_itself() -> None:
    assert identity.who("Ann Example") == identity.Actor(id="local:Ann Example", name="Ann Example", kind="human")
    company = identity.Actor(id="entra:7f3c", name="Ann Example", kind="human", org="acme")
    assert identity.who(company) is company
    assert identity.id_of("Ann Example") == "local:Ann Example"
    assert identity.id_of(company) == "entra:7f3c"
    assert identity.id_of(None) is None
    assert identity.name_of(company) == "Ann Example" and identity.name_of("x") == "x" and identity.name_of(None) is None


def test_the_ids_of_earlier_rows_come_from_their_names_once(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "old.sqlite")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, actor TEXT, approved_by TEXT)")
    conn.executemany("INSERT INTO t(actor, approved_by) VALUES (?,?)", [("Ann Example", None), ("g", "Ann Example")])
    assert store.add_actor_ids(conn, "t", ("actor", "approved_by")) == ["actor_id", "approved_by_id"]
    rows = conn.execute("SELECT actor_id, approved_by_id FROM t ORDER BY id").fetchall()
    assert rows == [("local:Ann Example", None), ("local:g", "local:Ann Example")]
    # a row written afterwards keeps its own id: the earlier rows are filled only when the column is added
    conn.execute("INSERT INTO t(actor, actor_id) VALUES ('Ann Example', 'entra:7f3c')")
    assert store.add_actor_ids(conn, "t", ("actor", "approved_by")) == []
    assert conn.execute("SELECT actor_id FROM t ORDER BY id DESC LIMIT 1").fetchone() == ("entra:7f3c",)
    assert store.add_actor_ids(conn, "missing", ("actor",)) == []


# --- the guard tests -----------------------------------------------------------------------------------------------

def test_every_column_naming_who_acted_has_its_id_column(tmp_path: Path) -> None:
    schema = _schema(tmp_path)
    missing = sorted(f"{t}.{col}" for t, cols in _who_columns(schema).items() for col in cols
                     if f"{col}_id" not in schema[t])
    assert missing == []
    assert sum(len(cols) for cols in _who_columns(schema).values()) >= 47, "the columns the mapping found (DECISIONS 229)"


def _sql_texts(tree: ast.Module) -> list[str]:
    """Every string of the module, an f-string with its placeholders as `{}` (adjacent literals are one string)."""
    texts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            texts.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            texts.append("".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values))
    return texts


_INSERT = re.compile(r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)\s*\(([^)]*)\)", re.I)
_UPSERT = re.compile(r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)\b.*?\bDO\s+UPDATE\s+SET\s+(.*?)(?:\bWHERE\b|$)", re.I | re.S)
_UPDATE = re.compile(r"\bUPDATE\s+(\w+)\s+SET\s+(.*?)(?:\bWHERE\b|\bRETURNING\b|$)", re.I | re.S)
_POSITIONAL = re.compile(r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)\s+(?:VALUES|SELECT)\b", re.I)


def _assigned(text: str) -> set[str]:
    return set(re.findall(r"(\w+)\s*=", text))


def _written(text: str) -> list[tuple[str, set[str]]]:
    """The tables a statement writes and the columns it names: an insert's list, an update's and an upsert's
    assignments. An insert without a column list names every column (`_POSITIONAL`)."""
    out = [(m.group(1), {c.strip() for c in m.group(2).split(",")}) for m in _INSERT.finditer(text)]
    out += [(m.group(1), _assigned(m.group(2))) for m in _UPSERT.finditer(text)]
    out += [(m.group(1), _assigned(m.group(2))) for m in _UPDATE.finditer(text)]
    return out


def test_every_statement_writing_who_acted_writes_the_id_too(tmp_path: Path) -> None:
    who = _who_columns(_schema(tmp_path))
    wrong = []
    for path in sorted((ROOT / "jav").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for text in _sql_texts(ast.parse(path.read_text(encoding="utf-8"))):
            for table, columns in _written(text):
                wrong += [f"{rel}: {table}.{col}" for col in sorted(who.get(table, set()) & columns)
                          if f"{col}_id" not in columns]
            # an id column added to an older store comes last, so an insert there names its columns
            wrong += [f"{rel}: {m.group(1)} without a column list" for m in _POSITIONAL.finditer(text)
                      if who.get(m.group(1))]
    assert wrong == []


# --- the operations record the id they are given -------------------------------------------------------------------

COMPANY = identity.Actor(id="entra:7f3c", name="Ann Example", kind="human", org="acme")


@pytest.fixture()
def db(tmp_path: Path):
    with store.use_store(tmp_path / "jav.sqlite"):
        yield


def test_the_decision_journal_records_the_id(db: None) -> None:
    decisions.register(decisions.Kind("test_229", ("decide",), __name__))
    with store.connect() as c:
        decisions.record(c, "test_229", "k1", "decide", actor=COMPANY)
        decisions.record(c, "test_229", "k2", "decide", actor="g")
        c.commit()
        rows = c.execute("SELECT key, actor, actor_id FROM decision_journal ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("k1", "Ann Example", "entra:7f3c"), ("k2", "g", "local:g")]


def test_a_package_owner_is_recorded_and_its_tasks_assigned_by_id(db: None) -> None:
    wp = work.create_workpackage(name="owned", source_kind="manual", source_ref=None, owner=COMPANY)
    with store.connect() as c:
        row = c.execute("SELECT owner, owner_id FROM workpackages WHERE id=?", (wp["id"],)).fetchone()
        assert tuple(row) == ("Ann Example", "entra:7f3c")
        assert human_tasks.assignee_for(c, wp["id"], None) == "entra:7f3c"
    work.set_owner(wp["id"], "Bob Example", actor=COMPANY)
    with store.connect() as c:
        row = c.execute("SELECT owner, owner_id FROM workpackages WHERE id=?", (wp["id"],)).fetchone()
        event = c.execute("SELECT actor, actor_id, detail FROM workpackage_events WHERE action='owner'").fetchone()
    assert tuple(row) == ("Bob Example", "local:Bob Example")
    assert (event["actor"], event["actor_id"]) == ("Ann Example", "entra:7f3c")
    assert "owner_id" not in event["detail"]  # the log keeps what a person sees


# --- the service hands who acts on (SZ2c-3) ------------------------------------------------------------------------

BASE = "http://127.0.0.1:8930"


def _renamed_by(tmp_path: Path, **client_kw) -> tuple[str, str]:
    db = tmp_path / "service.sqlite"
    app = api.create_app(store_path=db)
    with store.use_store(db):
        wp = work.create_workpackage(name="before", source_kind="manual", source_ref=None)
        client = TestClient(app, base_url=BASE)
        r = client.post(f"/api/workpackages/{wp['id']}/rename", json={"name": "after"}, **client_kw)
        assert r.status_code == 200, r.text
        with store.connect() as c:
            row = c.execute("SELECT actor, actor_id FROM workpackage_events WHERE action='rename'").fetchone()
    return row["actor"], row["actor_id"]


def test_a_named_person_is_stored_as_the_local_person(tmp_path: Path) -> None:
    assert _renamed_by(tmp_path, headers={"X-Actor": "Ann Example"}) == ("Ann Example", "local:Ann Example")


def test_the_actor_the_entrance_knows_reaches_the_store_with_its_id(tmp_path: Path, monkeypatch) -> None:
    """The company sign-in will change only the entrance (`service_shared.acting`): the actor it knows is the one
    every operation records."""
    monkeypatch.setattr(service_shared, "acting", lambda raw: COMPANY)
    assert _renamed_by(tmp_path, headers={"X-Actor": "Ann Example"}) == ("Ann Example", "entra:7f3c")


def test_an_actor_prints_as_its_name() -> None:
    assert f"{COMPANY}" == "Ann Example" and str(identity.who("g")) == "g"


def test_the_machine_acting_for_a_person_keeps_its_shown_name_and_whom_it_acts_for() -> None:
    auto = workflows.auto_actor({"actor": "Ann Example", "actor_id": "entra:7f3c"})
    assert (auto.id, auto.name, auto.kind, auto.on_behalf_of) == (
        "machine:workflow-chain", "Ann Example (auto)", "machine", "entra:7f3c")
    scheduled = mailbox.scheduled_actor({"actor": "Ann Example", "actor_id": "entra:7f3c"})
    assert (scheduled.id, scheduled.kind, scheduled.on_behalf_of) == ("machine:mailbox-schedule", "machine", "entra:7f3c")
    # the package a scheduled download makes is owned by the person who saved the schedule
    assert mailbox.owner_of(scheduled) == identity.recorded("Ann Example", "entra:7f3c")
