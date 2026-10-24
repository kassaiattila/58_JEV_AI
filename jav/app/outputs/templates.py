"""Own output templates: their store, their versions, the choice per package, and making an output (178, plan 170 L4).

Plain-language summary (DECISIONS 178): a person uploads their own Excel file with markers for one output (a
package's result, its utility cost, a reconciliation statement). The upload is checked (`jav/app/outputs/fill.py`); a
refused file is not stored, and the check names every problem. A stored file is a version of its template: a draft
first, which can be previewed with made-up data, then made active (the earlier active version is superseded), and a
template can be retired (224: the shared versions, `jav/core/versions.py`). Each package chooses, per output, the built-in template or an active own one; the download
and the release use the choice, and what a release or an approval stores records the template and its version. A
template version never changes (its bytes are kept), so a stored output can always be traced to the file it came from.

Layer: application operation over `jav/app/outputs` (contract, fill, built-in, samples) and the store.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from jav.app import logic_packs, work
from jav.core import activity_kinds, decisions, identity, store, versions
from jav.app.outputs import builtin, contract, docx, fill, samples
from jav.core.clock import utc_stamp as _now

# the package log's action of a person choosing a package's template (`jav/core/activity_kinds.py`)
activity_kinds.register_events("package", ("output_template_choose",), __name__)

BUILTIN = "builtin"
STATES = versions.STATES
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def engine(output: str) -> Any:
    """196: the check and the filling of the output's file format (`configs/outputs.json` `format`): a Word
    document's (`jav/app/outputs/docx.py`) or a workbook's (`jav/app/outputs/fill.py`)."""
    return docx if contract.spec(output)["format"] == "docx" else fill


def media(output: str) -> str:
    """196: the media type of the output's file."""
    return docx.MEDIA if contract.spec(output)["format"] == "docx" else XLSX


def extension(output: str) -> str:
    """196: the file name suffix of the output's file (`.docx`, `.xlsx`)."""
    return "." + contract.spec(output)["format"]

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
    uploaded_by_id TEXT,              -- 229 (SZ2c): the stable ids beside the names (`jav.core.identity`)
    uploaded_at   TEXT NOT NULL,
    activated_by  TEXT,
    activated_by_id TEXT,
    activated_at  TEXT,
    retired_by    TEXT,
    retired_by_id TEXT,
    retired_at    TEXT,
    UNIQUE (template, version)
);
-- the template a package's output is made with (no row: the built-in template)
CREATE TABLE IF NOT EXISTS output_template_choices (
    workpackage_id TEXT NOT NULL,
    output         TEXT NOT NULL,
    template       TEXT NOT NULL,
    chosen_by      TEXT NOT NULL,
    chosen_by_id   TEXT,
    chosen_at      TEXT NOT NULL,
    PRIMARY KEY (workpackage_id, output)
);
""")


def _actor_ids(conn) -> None:
    """229 (SZ2c): the stable id beside every name of who acted; the earlier rows' from their names."""
    store.add_actor_ids(conn, "output_templates", ("uploaded_by", "activated_by", "retired_by"))
    store.add_actor_ids(conn, "output_template_choices", ("chosen_by",))


store.register_migration("output_templates_actor_ids", _actor_ids)


class TemplateRefused(ValueError):
    """An upload whose check found problems (`check`: the check as a dict)."""

    def __init__(self, check: dict[str, Any]) -> None:
        super().__init__("the template was refused: " + "; ".join(f"{p['code']} {p['where']}".strip() for p in check["problems"]))
        self.check = check


class TemplateNotFound(versions.VersionNotFound):
    """No such template or version."""


class TemplateStateError(versions.VersionStateError):
    """The template or version is not in a state that allows this (a retired template chosen, a draft retired)."""


# 224 (plan G-process-core P3c): the versions' states and their changes are the shared ones (`jav/core/versions.py`)
VERSIONS = versions.VersionTable("output_templates", "template", not_found=TemplateNotFound, state_error=TemplateStateError)


def _view(row: Any) -> dict[str, Any]:
    out = {k: row[k] for k in ("template", "output", "name", "version", "state", "file_name", "sha256", "uploaded_by",
                               "uploaded_at", "activated_by", "activated_at", "retired_by", "retired_at")}
    out["check"] = json.loads(row["checks"])
    out["size"] = len(row["content"]) if "content" in row.keys() else None
    return out


# --- the store ------------------------------------------------------------------------------------------------------


def add(output: str, name: str, file_name: str, content: bytes, *, actor: identity.Who, template: str | None = None) -> dict[str, Any]:
    """Checks and stores an upload as a draft version: of `template` (its next version), or of a new template.
    `TemplateRefused` with the check when it has problems."""
    name = (name or "").strip()
    if not name:
        raise ValueError("a template needs a name")
    check = engine(output).check(output, content).as_dict()
    if not check["ok"]:
        raise TemplateRefused(check)
    with store.connect() as c:
        store.begin_immediate(c)
        if template is None:
            template, version = "tpl-" + secrets.token_hex(5), 1
        else:
            latest = VERSIONS.latest(c, template)
            if latest["output"] != output:
                raise TemplateStateError(f"template {template} is a template of {latest['output']}")
            version = latest["version"] + 1
        c.execute("INSERT INTO output_templates(template, output, name, version, state, file_name, sha256, content, checks,"
                  " uploaded_by, uploaded_by_id, uploaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (template, output, name, version, "draft", file_name, hashlib.sha256(content).hexdigest(), content,
                   json.dumps(check, ensure_ascii=False), identity.name_of(actor), identity.id_of(actor), _now()))
    return get(template, version)


def get(template: str, version: int) -> dict[str, Any]:
    with store.connect() as c:
        return _view(VERSIONS.row(c, template, version))


def content(template: str, version: int) -> tuple[bytes, str]:
    """A version's file as it was uploaded, and its file name."""
    with store.connect() as c:
        row = VERSIONS.row(c, template, version)
    return bytes(row["content"]), row["file_name"]


def listing(output: str | None = None) -> list[dict[str, Any]]:
    """Every template (of one output, or all), newest first, each with its versions (newest first) and its active one."""
    with store.connect() as c:
        rows = c.execute("SELECT template, output, name, version, state, file_name, sha256, checks, uploaded_by, uploaded_at,"
                         " activated_by, activated_at, retired_by, retired_at, length(content) AS size FROM output_templates"
                         " ORDER BY id DESC").fetchall()
    return VERSIONS.grouped((r for r in rows if not output or r["output"] == output),
                            lambda r: {"template": r["template"], "output": r["output"], "name": r["name"]},
                            lambda r: _view(r) | {"size": r["size"]})


def activate(template: str, version: int, *, actor: identity.Who) -> dict[str, Any]:
    """Makes the version the template's active one (a draft, or an earlier version again); the active one before it is
    superseded. A retired template comes back with it."""
    with store.connect() as c:
        store.begin_immediate(c)
        VERSIONS.activate(c, template, version, actor=actor)
    return get(template, version)


def retire(template: str, *, actor: identity.Who) -> dict[str, Any]:
    """Retires the template: its active version is no longer chosen; a package that chose it gets the built-in template."""
    with store.connect() as c:
        store.begin_immediate(c)
        n = VERSIONS.retire(c, template, actor=actor)
    return get(template, n)


def _active(c: Any, template: str) -> Any:
    return VERSIONS.active(c, template)


def preview(template: str, version: int) -> tuple[bytes, str]:
    """The version filled with made-up data (never a person's): the document types it names, a few rows of each."""
    v = get(template, version)
    data, file_name = content(template, version)
    parts = tuple(name for name in v["check"]["tables"] if name not in contract.spec(v["output"])["tables"]) or samples.default_parts()
    return engine(v["output"]).fill(samples.data(v["output"], parts), data), f"preview-{file_name}"


# --- the choice per package -----------------------------------------------------------------------------------------


def outputs_for(wp: dict[str, Any]) -> tuple[str, ...]:
    """The outputs a package has; 231 (A6): a case's container has its process pack's."""
    from jav.app import process_runtime

    if wp["source_kind"] == process_runtime.CONTAINER:
        return process_runtime.outputs_of(wp["id"])
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


def choose(wp_id: str, output: str, template: str | None, *, actor: identity.Who, expected_state: int | None = None) -> dict[str, Any]:
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
            c.execute("INSERT INTO output_template_choices(workpackage_id, output, template, chosen_by, chosen_by_id, chosen_at)"
                      " VALUES (?,?,?,?,?,?) ON CONFLICT(workpackage_id, output) DO UPDATE SET template=excluded.template,"
                      " chosen_by=excluded.chosen_by, chosen_by_id=excluded.chosen_by_id, chosen_at=excluded.chosen_at",
                      (wp_id, output, template, identity.name_of(actor), identity.id_of(actor), _now()))
        work.record_event(c, wp_id, "output_template_choose", actor, {"output": output, "template": template})
        decisions.record(c, CHOICE_KIND, _choice_key(wp_id, output), "choose", actor=actor, value={"template": template},
                         workpackage_id=wp_id)
    return choices(wp_id)


# --- making an output -----------------------------------------------------------------------------------------------


def builtin_version(output: str) -> str:
    return contract.spec(output)["builtin"]["version"]


def _chosen(c: Any, wp_id: str, output: str) -> Any:
    """The package's chosen template's active version; without a choice, (231 B2) a case's own default from its
    process's resource `template:<output>` (the built-in one unless the process set one)."""
    ch = c.execute("SELECT template FROM output_template_choices WHERE workpackage_id=? AND output=?", (wp_id, output)).fetchone()
    if ch:
        return _active(c, ch["template"])
    from jav.app import process_runtime  # the process runtime imports the release, which imports this module

    default = process_runtime.resource_of(c, wp_id, f"template:{output}")
    return _active(c, default) if default and default != BUILTIN else None


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
            made = {"template": row["template"], "template_version": str(row["version"])}
            return engine(data.output).fill(data, bytes(row["content"])), made
    return builtin.render(data), {"template": BUILTIN, "template_version": builtin_version(data.output)}


def render_with(data: contract.OutputData, template: str, version: str) -> bytes:
    """The output's file made with a recorded template version (a reopened statement keeps its approval's template)."""
    if template == BUILTIN:
        return builtin.render(data)
    return engine(data.output).fill(data, content(template, int(version))[0])
