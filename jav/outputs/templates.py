"""Own output templates: their store, their versions, the choice per package, and making an output (178, plan 170 L4).

Plain-language summary (DECISIONS 178): a person uploads their own Excel file with markers for one output (a
package's result, its utility cost, a reconciliation statement). The upload is checked (`jav/outputs/fill.py`); a
refused file is not stored, and the check names every problem. A stored file is a version of its template: a draft
first, which can be previewed with made-up data, then made active (the earlier active version is superseded), and a
template can be retired. Each package chooses, per output, the built-in template or an active own one; the download
and the release use the choice, and what a release or an approval stores records the template and its version. A
template version never changes (its bytes are kept), so a stored output can always be traced to the file it came from.

Layer: application operation over `jav/outputs` (contract, fill, built-in, samples) and the store.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from jav import activity_kinds, decisions, logic_packs, store, work
from jav.outputs import builtin, contract, fill, samples

# the package log's action of a person choosing a package's template (`jav/activity_kinds.py`)
activity_kinds.register_events("package", ("output_template_choose",), __name__)

BUILTIN = "builtin"
STATES = ("draft", "active", "superseded", "retired")

store.register_schema("output_templates", """
-- 178 (plan 170 L4): a person's own template of an output, each uploaded file a version; the bytes never change
CREATE TABLE IF NOT EXISTS output_templates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    template      TEXT NOT NULL,      -- the template's identifier, the same for all its versions
    output        TEXT NOT NULL,      -- configs/outputs.json
    name          TEXT NOT NULL,
    version       INTEGER NOT NULL,
    state         TEXT NOT NULL,      -- draft, active, superseded, retired
    file_name     TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    content       BLOB NOT NULL,
    checks        TEXT NOT NULL,      -- JSON: the upload's check (warnings, the values and tables it uses)
    uploaded_by   TEXT NOT NULL,
    uploaded_at   TEXT NOT NULL,
    activated_by  TEXT,
    activated_at  TEXT,
    retired_by    TEXT,
    retired_at    TEXT,
    UNIQUE (template, version)
);
-- the template a package's output is made with (no row: the built-in template)
CREATE TABLE IF NOT EXISTS output_template_choices (
    workpackage_id TEXT NOT NULL,
    output         TEXT NOT NULL,
    template       TEXT NOT NULL,
    chosen_by      TEXT NOT NULL,
    chosen_at      TEXT NOT NULL,
    PRIMARY KEY (workpackage_id, output)
);
""")


class TemplateRefused(ValueError):
    """An upload whose check found problems (`check`: the check as a dict)."""

    def __init__(self, check: dict[str, Any]) -> None:
        super().__init__("the template was refused: " + "; ".join(f"{p['code']} {p['where']}".strip() for p in check["problems"]))
        self.check = check


class TemplateNotFound(KeyError):
    """No such template or version."""


class TemplateStateError(ValueError):
    """The template or version is not in a state that allows this (a retired template chosen, a draft retired)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _view(row: Any) -> dict[str, Any]:
    out = {k: row[k] for k in ("template", "output", "name", "version", "state", "file_name", "sha256", "uploaded_by",
                               "uploaded_at", "activated_by", "activated_at", "retired_by", "retired_at")}
    out["check"] = json.loads(row["checks"])
    out["size"] = len(row["content"]) if "content" in row.keys() else None
    return out


# --- the store ------------------------------------------------------------------------------------------------------


def add(output: str, name: str, file_name: str, content: bytes, *, actor: str, template: str | None = None) -> dict[str, Any]:
    """Checks and stores an upload as a draft version: of `template` (its next version), or of a new template.
    `TemplateRefused` with the check when it has problems."""
    name = (name or "").strip()
    if not name:
        raise ValueError("a template needs a name")
    check = fill.check(output, content).as_dict()
    if not check["ok"]:
        raise TemplateRefused(check)
    with store.connect() as c:
        store.begin_immediate(c)
        if template is None:
            template, version = "tpl-" + secrets.token_hex(5), 1
        else:
            row = c.execute("SELECT output, MAX(version) AS n FROM output_templates WHERE template=?", (template,)).fetchone()
            if row is None or row["n"] is None:
                raise TemplateNotFound(template)
            if row["output"] != output:
                raise TemplateStateError(f"template {template} is a template of {row['output']}")
            version = row["n"] + 1
        c.execute("INSERT INTO output_templates(template, output, name, version, state, file_name, sha256, content, checks,"
                  " uploaded_by, uploaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (template, output, name, version, "draft", file_name, hashlib.sha256(content).hexdigest(), content,
                   json.dumps(check, ensure_ascii=False), actor, _now()))
    return get(template, version)


def get(template: str, version: int) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM output_templates WHERE template=? AND version=?", (template, version)).fetchone()
    if row is None:
        raise TemplateNotFound(f"{template} version {version}")
    return _view(row)


def content(template: str, version: int) -> tuple[bytes, str]:
    """A version's file as it was uploaded, and its file name."""
    with store.connect() as c:
        row = c.execute("SELECT content, file_name FROM output_templates WHERE template=? AND version=?", (template, version)).fetchone()
    if row is None:
        raise TemplateNotFound(f"{template} version {version}")
    return bytes(row["content"]), row["file_name"]


def listing(output: str | None = None) -> list[dict[str, Any]]:
    """Every template (of one output, or all), newest first, each with its versions (newest first) and its active one."""
    with store.connect() as c:
        rows = c.execute("SELECT template, output, name, version, state, file_name, sha256, checks, uploaded_by, uploaded_at,"
                         " activated_by, activated_at, retired_by, retired_at, length(content) AS size FROM output_templates"
                         " ORDER BY id DESC").fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if output and r["output"] != output:
            continue
        v = _view(r) | {"size": r["size"]}
        t = out.setdefault(r["template"], {"template": r["template"], "output": r["output"], "name": r["name"],
                                           "active": None, "retired": False, "versions": []})
        t["versions"].append(v)
        if v["state"] == "active":
            t["active"] = v["version"]
        if v["state"] == "retired":
            t["retired"] = True
    return list(out.values())


def activate(template: str, version: int, *, actor: str) -> dict[str, Any]:
    """Makes the version the template's active one (a draft, or an earlier version again); the active one before it is
    superseded. A retired template comes back with it."""
    with store.connect() as c:
        store.begin_immediate(c)
        row = c.execute("SELECT state FROM output_templates WHERE template=? AND version=?", (template, version)).fetchone()
        if row is None:
            raise TemplateNotFound(f"{template} version {version}")
        if row["state"] == "active":
            raise TemplateStateError(f"{template} version {version} is already active")
        c.execute("UPDATE output_templates SET state='superseded' WHERE template=? AND state IN ('active', 'retired')", (template,))
        c.execute("UPDATE output_templates SET state='active', activated_by=?, activated_at=?, retired_by=NULL, retired_at=NULL"
                  " WHERE template=? AND version=?", (actor, _now(), template, version))
    return get(template, version)


def retire(template: str, *, actor: str) -> dict[str, Any]:
    """Retires the template: its active version is no longer chosen; a package that chose it gets the built-in template."""
    with store.connect() as c:
        store.begin_immediate(c)
        row = c.execute("SELECT version FROM output_templates WHERE template=? AND state='active'", (template,)).fetchone()
        if row is None:
            raise TemplateStateError(f"{template} has no active version")
        c.execute("UPDATE output_templates SET state='retired', retired_by=?, retired_at=? WHERE template=? AND version=?",
                  (actor, _now(), template, row["version"]))
    return get(template, row["version"])


def _active(c: Any, template: str) -> Any:
    return c.execute("SELECT * FROM output_templates WHERE template=? AND state='active'", (template,)).fetchone()


def preview(template: str, version: int) -> tuple[bytes, str]:
    """The version filled with made-up data (never a person's): the document types it names, a few rows of each."""
    v = get(template, version)
    data, file_name = content(template, version)
    parts = tuple(name for name in v["check"]["tables"] if name not in contract.spec(v["output"])["tables"]) or (samples.DEFAULT_PART,)
    return fill.fill(samples.data(v["output"], parts), data), f"preview-{file_name}"


# --- the choice per package -----------------------------------------------------------------------------------------


def outputs_for(wp: dict[str, Any]) -> tuple[str, ...]:
    return logic_packs.outputs_of(wp["source_kind"])


# 187 (plan G-full-move T2c): a person's template choices of a package's outputs, in the shared decision journal
CHOICE_KIND = "output_template"
decisions.register(decisions.Kind(CHOICE_KIND, ("choose",), __name__))


def _choice_key(wp_id: str, output: str) -> str:
    return f"{wp_id}#{output}"


def choices(wp_id: str) -> dict[str, Any]:
    """Per output of the package: the chosen template (None: the built-in), whether it is still active, and the
    active templates it can choose; 187: the choice's `decision_state`, which the page sends back with a change."""
    wp = work.get(wp_id)
    with store.connect() as c:
        chosen = {r["output"]: dict(r) for r in c.execute("SELECT * FROM output_template_choices WHERE workpackage_id=?", (wp_id,))}
        state = decisions.states(c, CHOICE_KIND, [_choice_key(wp_id, o) for o in outputs_for(wp)])
    active = {}
    for t in listing():
        if t["active"] is not None:
            active.setdefault(t["output"], []).append({"template": t["template"], "name": t["name"], "version": t["active"]})
    out = {}
    for output in outputs_for(wp):
        ch = chosen.get(output)
        live = next((a for a in active.get(output, []) if ch and a["template"] == ch["template"]), None)
        out[output] = {"chosen": ch and {"template": ch["template"], "chosen_by": ch["chosen_by"], "chosen_at": ch["chosen_at"],
                                         "active": live is not None, "name": live and live["name"], "version": live and live["version"]},
                       "templates": active.get(output, []), "decision_state": state[_choice_key(wp_id, output)]}
    return {"workpackage_id": wp_id, "outputs": out}


def choose(wp_id: str, output: str, template: str | None, *, actor: str, expected_state: int | None = None) -> dict[str, Any]:
    """Chooses the template of a package's output (None: the built-in template); the template must be active. 187: in
    the decision journal, under the page's `expected_state`."""
    wp = work.get(wp_id)
    if output not in outputs_for(wp):
        raise TemplateStateError(f"a package of this kind has no output {output}")
    with store.connect() as c:
        store.begin_immediate(c)
        decisions.check(c, CHOICE_KIND, _choice_key(wp_id, output), expected_state)
        if template is None:
            c.execute("DELETE FROM output_template_choices WHERE workpackage_id=? AND output=?", (wp_id, output))
        else:
            row = _active(c, template)
            if row is None or row["output"] != output:
                raise TemplateStateError(f"{template} is not an active template of {output}")
            c.execute("INSERT INTO output_template_choices(workpackage_id, output, template, chosen_by, chosen_at) VALUES (?,?,?,?,?)"
                      " ON CONFLICT(workpackage_id, output) DO UPDATE SET template=excluded.template, chosen_by=excluded.chosen_by,"
                      " chosen_at=excluded.chosen_at", (wp_id, output, template, actor, _now()))
        work.record_event(c, wp_id, "output_template_choose", actor, {"output": output, "template": template})
        decisions.record(c, CHOICE_KIND, _choice_key(wp_id, output), "choose", actor=actor, value={"template": template},
                         workpackage_id=wp_id)
    return choices(wp_id)


# --- making an output -----------------------------------------------------------------------------------------------


def builtin_version(output: str) -> str:
    return contract.spec(output)["builtin"]["version"]


def _chosen(c: Any, wp_id: str, output: str) -> Any:
    ch = c.execute("SELECT template FROM output_template_choices WHERE workpackage_id=? AND output=?", (wp_id, output)).fetchone()
    return _active(c, ch["template"]) if ch else None


def render(data: contract.OutputData, wp_id: str | None = None, c: Any = None) -> tuple[bytes, dict[str, str]]:
    """The output's file made with the package's chosen template (the built-in one without a choice, or when the chosen
    template was retired), and which template and version made it; `c`: the caller's connection (in a transaction)."""
    if wp_id is not None:
        if c is not None:
            row = _chosen(c, wp_id, data.output)
        else:
            with store.connect() as conn:
                row = _chosen(conn, wp_id, data.output)
        if row is not None and row["output"] == data.output:
            return fill.fill(data, bytes(row["content"])), {"template": row["template"], "template_version": str(row["version"])}
    return builtin.render(data), {"template": BUILTIN, "template_version": builtin_version(data.output)}


def render_with(data: contract.OutputData, template: str, version: str) -> bytes:
    """The output's file made with a recorded template version (a reopened statement keeps its approval's template)."""
    if template == BUILTIN:
        return builtin.render(data)
    return fill.fill(data, content(template, int(version))[0])
