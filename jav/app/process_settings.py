"""A process pack's own settings in the store (231, plan stage B, B2 and B3; DECISIONS 231).

Plain-language summary: a process pack names its resources in its file (which price list its quotes are priced from,
how its letters are sent, which letter frame and which output template they use), and its steps' capabilities read
rule files (how many lines a quote may hold, the unit its amounts are rounded to). A process may set its own value
over a resource of its file (B2) or over a rule key its capabilities let a process set (B3, `capabilities.RuleKey`),
kept in versions as everything a person edits is (`jav/core/versions.py`): a person saves a value as a draft, and it
becomes the process's value when it is made active; retiring it brings the file's value back. Who may make a value
active is itself a rule (`configs/process_settings.json`, the owner's decision of 2026-10-24): by default the person
who edits it; it can be only the listed owners, or a second person (four eyes). A case takes the values active when
it starts and keeps them: a change reaches the cases started after it.

- `propose(pack_id, key, value, actor, kind=, note=)`: a draft value, checked as the pack would be with it (a
  resource) or as its capability declares the key (a rule).
- `activate(pack_id, key, version, actor, kind=)`, `retire(pack_id, key, actor, kind=)`: a value made the process's,
  or the file's brought back; `SettingRefused` when the rule does not let this person.
- `effective_resources(pack)`: the pack's resources with its active values over the file's; `effective_rules(pack)`:
  its active rule values, as a case keeps them (`capabilities.RULES`); `rule_keys(pack)`: the rule keys its steps'
  capabilities let it set; `view(pack_id)`: every resource and rule key with its file value, its active value and its
  versions.
- `preview(pack_id, key, value)` (B3): what a rule value would have changed: the decisions of the process's cases that
  read the key (the decision trace), each one's rule run again with the value it was made with and with this one.
- B4: a resource's name and the values it may take come from the capabilities whose parameters it sets (`Capability.
  choices`, the parameter's field title); a process's own value of such a resource is one of them. The settings page
  also shows the roles the process's partners play.
- 231 (stage U, U0): `missing_at_start(pack)`: what a case of the pack cannot start without now, before anyone tries.
- 231 (U3c; the owner's decision of 2026-10-28: the tariff is part of the product): a pack's `derived` resource follows
  from its source (a product brings its tariff, `AtStart.brings`): its value is the source's, shown read only, and a
  process sets no value of its own for it.
- 231 (U3a): `view` describes the process too (`description`: what it is for, its steps, outputs, golden sets, what
  starts a case of it, whether it has example material), for its own settings page.

Layer: application, the shared library; it uses the process packs, the capabilities, the shared versioning and the
output templates.
"""

from __future__ import annotations

import json
from typing import Any

from jav.app import capabilities, partners, process_packs
from jav.core import cfg, identity, store, trace, versions
from jav.core.clock import utc_stamp as _now
from jav.core.user_messages import explained

__all__ = ["CONFIG", "KINDS", "RESOURCE", "RULE", "MissingAtStart", "SettingError", "SettingRefused", "UnknownSetting", "activate", "at_start",
           "effective_resources", "effective_rules", "may_activate", "missing_at_start", "policy", "preview", "propose",
           "resource_info", "retire", "kept_resources", "kept_view", "rule_keys", "view"]

CONFIG = "process_settings"
RESOURCE = "resource"  # a value over a pack's resource (B2)
RULE = "rule"  # a value over a rule key its capabilities let a process set (B3)
KINDS = (RESOURCE, RULE)
TEMPLATE_PREFIX = "template:"  # a resource naming an output's template for the pack's cases: `template:<output>`
EDITOR, OWNER, SECOND_PERSON = "editor", "owner", "second_person"
PREVIEW_EXAMPLES = 20  # the changed decisions a preview lists

store.register_schema("process_settings", """
-- 231 (B2): a process pack's own values over its file's, every change a version of its own
CREATE TABLE IF NOT EXISTS process_setting_versions (
    setting_id      TEXT NOT NULL,     -- <pack>/<kind>/<key>
    version         INTEGER NOT NULL,
    state           TEXT NOT NULL,     -- draft | active | superseded | retired (`jav/core/versions.py`)
    pack_id         TEXT NOT NULL,
    kind            TEXT NOT NULL,     -- resource (B2) | rule (B3)
    key             TEXT NOT NULL,
    value           TEXT NOT NULL,     -- JSON
    note            TEXT,
    made_by         TEXT NOT NULL,
    made_by_id      TEXT,
    made_at         TEXT NOT NULL,
    activated_by    TEXT,
    activated_by_id TEXT,
    activated_at    TEXT,
    retired_by      TEXT,
    retired_by_id   TEXT,
    retired_at      TEXT,
    PRIMARY KEY (setting_id, version)
);
CREATE INDEX IF NOT EXISTS ix_process_settings_pack ON process_setting_versions(pack_id, state);
""")


class MissingAtStart(ValueError):
    """Stage D (D-a): a case of the pack cannot start: a resource it needs at its start has no version to keep."""


class SettingError(ValueError):
    """A value the process cannot take (its pack's check refuses it, an unknown resource or rule key)."""


class SettingRefused(SettingError):
    """The rule of who may make a value active does not let this person."""


class UnknownSetting(versions.VersionNotFound):
    """No such setting or version."""


class SettingStateError(versions.VersionStateError):
    """A version not in a state that allows this."""


VERSIONS = versions.VersionTable("process_setting_versions", "setting_id", UnknownSetting, SettingStateError)


def _id(pack_id: str, kind: str, key: str) -> str:
    return f"{pack_id}/{kind}/{key}"


def policy() -> dict[str, Any]:
    """Who may make a value active: `activation` (editor, owner or second_person) and the `owners` by name."""
    data = cfg.load(CONFIG)
    return {"activation": data["activation"], "owners": list(data.get("owners") or [])}


def may_activate(actor: identity.Who, made_by: str) -> bool:
    """Whether this person may make a draft made by `made_by` active, by the rule."""
    rule, name = policy(), identity.name_of(actor)
    if rule["activation"] == OWNER:
        return name in rule["owners"]
    if rule["activation"] == SECOND_PERSON:
        return name != made_by
    return True


def _active_rows(c: Any, pack_id: str, kind: str) -> list[Any]:
    return c.execute("SELECT key, value, setting_id, version FROM process_setting_versions WHERE pack_id=? AND kind=?"
                     " AND state=?", (pack_id, kind, versions.ACTIVE)).fetchall()


def effective_resources(pack: process_packs.ProcessPack) -> dict[str, str]:
    """The pack's resources: its file's, with the process's active values over them; 231 (U3c) a derived resource as its
    source brings it (a product its tariff), whatever value it had of its own."""
    with store.connect() as c:
        own = {r["key"]: json.loads(r["value"]) for r in _active_rows(c, pack.id, RESOURCE)}
    resources = {**pack.resources, **{k: str(v) for k, v in own.items() if k in pack.resources and k not in pack.derived}}
    for key in pack.derived:
        if (brought := _brought(pack, key, resources)) is not None:
            resources[key] = brought
    return resources


def _brought(pack: process_packs.ProcessPack, key: str, resources: dict[str, str]) -> str | None:
    """231 (U3c): a derived resource's value as its source brings it (the source's keeper's `brings`, by the derived
    resource's kind); None when the source brings none."""
    keepers = _keepers(pack)
    source, mine = keepers.get(pack.derived[key]), keepers.get(key)
    bring = source.brings.get(str(mine.kind)) if source is not None and mine is not None else None
    return bring(resources[pack.derived[key]]) if bring is not None else None


def rule_keys(pack: process_packs.ProcessPack) -> dict[str, tuple[capabilities.RuleKey, list[str]]]:
    """231 (B3): the rule keys the pack's steps' capabilities let it set, by id, each with the steps that read it."""
    out: dict[str, tuple[capabilities.RuleKey, list[str]]] = {}
    for step in pack.steps:
        for rule in capabilities.of(step.uses).rule_keys:
            out.setdefault(rule.id, (rule, []))[1].append(step.id)
    return out


def effective_rules(pack: process_packs.ProcessPack) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """231 (B3): the process's active rule values, as a case keeps them: ({config name: {key: value}}, {config name:
    {key: {"setting": id, "version": n}}}); a key its capabilities no longer declare is left out."""
    keys = rule_keys(pack)
    values: dict[str, dict[str, Any]] = {}
    refs: dict[str, dict[str, Any]] = {}
    with store.connect() as c:
        for r in _active_rows(c, pack.id, RULE):
            if r["key"] in keys:
                rule = keys[r["key"]][0]
                values.setdefault(rule.file, {})[rule.key] = json.loads(r["value"])
                refs.setdefault(rule.file, {})[rule.key] = {"setting": r["setting_id"], "version": r["version"]}
    return values, refs


def kept_resources(pack: process_packs.ProcessPack, resources: dict[str, str]) -> dict[str, str]:
    """Stage D0 (D0-e; the owner's decision of 2026-10-26): the resources a case keeps from its start: each one naming
    a versioned thing (a parameter its capability keeps, `Capability.at_start`, as a price list; an output's template)
    at the version current now, so a newer version reaches only the cases started after it."""
    keepers = _keepers(pack)
    return {key: keepers[key].kept(value) if key in keepers else value for key, value in resources.items()}


def at_start(pack: process_packs.ProcessPack) -> process_packs.ProcessPack:
    """Stage D (D-a; the reassessment after D0, P04): the pack as a case starts it: its resources at the versions it keeps
    (`kept_resources`), and a step parameter naming a versioned thing itself (a price list's id or `newest_active`,
    not a resource) at its version now too. `MissingAtStart` when a resource the pack needs at its start
    (`needs_at_start`) has no version to keep (none is active): the case does not start, rather than read another
    version later."""
    resources = kept_resources(pack, effective_resources(pack))
    if missing := _missing(pack, resources):
        names = ", ".join(_resource_title(pack, k) for k in missing)
        raise explained(MissingAtStart, "the case cannot start: {{what}} has no active version to keep", what=names)
    steps = [step.model_copy(update={"params": _kept_params(step)}) for step in pack.steps]
    return pack.model_copy(update={"resources": resources, "steps": tuple(steps)})


def _missing(pack: process_packs.ProcessPack, kept: dict[str, str]) -> list[str]:
    keepers = _keepers(pack)
    return [key for key in pack.needs_at_start if key in keepers and not keepers[key].resolved(str(kept.get(key, "")))]


def _resource_title(pack: process_packs.ProcessPack, key: str) -> str:
    return "Output template" if key.startswith(TEMPLATE_PREFIX) else _param_title(pack, key)


def missing_at_start(pack: process_packs.ProcessPack) -> list[dict[str, str]]:
    """231 (stage U, U0): what a case of the pack cannot start without now, before anyone tries: each resource it needs
    at its start (`needs_at_start`) with no active version to keep, {key, label}; empty when a case may start."""
    return [{"key": key, "label": _resource_title(pack, key)}
            for key in _missing(pack, kept_resources(pack, effective_resources(pack)))]


def _kept_params(step: Any) -> dict[str, Any]:
    """D-a: a step's parameters with each one naming a versioned thing itself (not `@<resource>`) at its version now."""
    cap = capabilities.of(step.uses)
    return {name: cap.at_start[name].kept(value) if name in cap.at_start and isinstance(value, str) and not value.startswith("@")
            else value for name, value in (step.params or {}).items()}


def kept_view(pack: process_packs.ProcessPack, resources: dict[str, Any]) -> list[dict[str, Any]]:
    """D0-e: the versioned resources a case keeps, as its history shows them: {key, label, name, version}."""
    keepers = _keepers(pack)
    out = []
    for key in sorted(k for k in resources if k in keepers):
        out.append({"key": key, "label": _resource_title(pack, key), **keepers[key].named(str(resources[key]))})
    return out


def _keepers(pack: process_packs.ProcessPack) -> dict[str, capabilities.AtStart]:
    """The pack's resources that name a versioned thing, each with how a case keeps it."""
    from jav.app.outputs import templates

    found: dict[str, capabilities.AtStart] = {}
    for step in pack.steps:
        cap = capabilities.of(step.uses)
        for param, value in (step.params or {}).items():
            if isinstance(value, str) and value.startswith("@") and param in cap.at_start:
                found.setdefault(value[1:], cap.at_start[param])
    found.update({key: capabilities.AtStart(templates.kept, templates.named,
                                            resolved=lambda value: value == templates.BUILTIN or "@" in value)
                  for key in pack.resources if key.startswith(TEMPLATE_PREFIX)})
    return found


def _param_title(pack: process_packs.ProcessPack, key: str) -> str:
    """The title of the parameter a resource sets (its name on the settings page), else the key."""
    for step in pack.steps:
        cap = capabilities.of(step.uses)
        for param, value in (step.params or {}).items():
            if value == f"@{key}" and param in cap.params.model_fields and cap.params.model_fields[param].title:
                return str(cap.params.model_fields[param].title)
    return key


def _template_choices(output: str) -> list[tuple[str, str]]:
    from jav.app.outputs import templates

    return [(templates.BUILTIN, "The built-in template"),
            *((t["template"], t["name"]) for t in templates.listing() if t["output"] == output and t["active"])]


def resource_info(pack: process_packs.ProcessPack, key: str) -> tuple[str, list[tuple[str, str]] | None]:
    """231 (B4): a resource's name and the values it may take (None: any the pack's check passes), from the capabilities
    whose parameters it sets (`"@<key>"` in a step's parameters): the parameter's field title and its `choices`. An
    output's template: the built-in one or an active own template of that output."""
    if key.startswith(TEMPLATE_PREFIX):
        return "Output template", _template_choices(key[len(TEMPLATE_PREFIX):])
    label, options = key, None
    for step in pack.steps:
        cap = capabilities.of(step.uses)
        for param, value in (step.params or {}).items():
            if value != f"@{key}" or param not in cap.params.model_fields:
                continue
            label = cap.params.model_fields[param].title or label
            if param in cap.choices_for:  # U3b: the values that fit this step
                return label, cap.choices_for[param](pack, step)
            if param in cap.choices:
                return label, cap.choices[param]()
    return label, options


def _problems(pack: process_packs.ProcessPack, kind: str, key: str, value: Any) -> list[str]:
    """What the pack's check says with this value over the resource (and whether it is one of the values the resource
    may take, B4); for a rule key, what its capability's declaration says."""
    if kind == RULE:
        keys = rule_keys(pack)
        return keys[key][0].problems(value) if key in keys else [f"the process sets no rule {key!r}"]
    if key not in pack.resources:
        return [f"the process has no resource {key!r}"]
    _label, options = resource_info(pack, key)
    if options is not None and value not in {v for v, _ in options}:
        return [f"{value!r} is not one of the values {key} may take"]
    if key.startswith(TEMPLATE_PREFIX):
        return []
    trial = pack.model_copy(update={"resources": {**effective_resources(pack), key: value}})
    return process_packs._problems(trial)


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown kind of setting {kind!r}")
    return kind


def propose(pack_id: str, key: str, value: Any, actor: identity.Who, *, kind: str = RESOURCE,
            note: str | None = None) -> dict[str, Any]:
    """A draft value of the pack's resource or rule `key`, refused (`SettingError`, every problem named) when the
    pack's check (a resource) or the capability's declaration (a rule) does not take it."""
    pack = process_packs.load(pack_id)
    if _kind(kind) == RESOURCE:
        value = " ".join(str(value).split())
    if value is None or value == "":
        raise explained(SettingError, "a setting needs a value")
    if kind == RESOURCE and key in pack.derived:  # U3c: it follows its source (a product's tariff)
        raise explained(SettingError, "the {{what}} follows from the {{source}}: set the {{source}} instead",
                        what=_resource_title(pack, key), source=_resource_title(pack, pack.derived[key]))
    if problems := _problems(pack, kind, key, value):
        raise explained(SettingError, "the process cannot take this value: {{problems}}", problems="; ".join(problems))
    sid = _id(pack_id, kind, key)
    with store.connect() as c:
        store.begin_immediate(c)
        try:
            version = int(VERSIONS.latest(c, sid)["version"]) + 1
        except UnknownSetting:
            version = 1
        c.execute("INSERT INTO process_setting_versions(setting_id, version, state, pack_id, kind, key, value, note, made_by,"
                  " made_by_id, made_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (sid, version, versions.DRAFT, pack_id, kind, key, json.dumps(value), (note or "").strip() or None,
                   identity.name_of(actor), identity.id_of(actor), _now()))
    return view(pack_id)


def activate(pack_id: str, key: str, version: int, actor: identity.Who, *, kind: str = RESOURCE) -> dict[str, Any]:
    """The version becomes the process's value (checked again, as the store or the code may have changed since)."""
    pack = process_packs.load(pack_id)
    sid = _id(pack_id, _kind(kind), key)
    with store.connect() as c:
        store.begin_immediate(c)
        row = VERSIONS.row(c, sid, version)
        if not may_activate(actor, row["made_by"]):
            raise explained(SettingRefused, "by the rule of this installation, {{name}} may not make this value active",
                            name=identity.name_of(actor))
        if problems := _problems(pack, kind, key, json.loads(row["value"])):
            raise explained(SettingError, "the process cannot take this value: {{problems}}", problems="; ".join(problems))
        VERSIONS.activate(c, sid, version, actor=actor)
    return view(pack_id)


def retire(pack_id: str, key: str, actor: identity.Who, *, kind: str = RESOURCE) -> dict[str, Any]:
    """The process's own value is set aside: the file's value counts again. Where the rule names owners only they may;
    otherwise anyone may, as it brings back the value the pack was checked with (no second person is needed)."""
    process_packs.load(pack_id)
    sid = _id(pack_id, _kind(kind), key)
    with store.connect() as c:
        store.begin_immediate(c)
        current = VERSIONS.active(c, sid)
        if current is None:
            raise explained(SettingStateError, "the process has no value of its own for {{key}}", key=key)
        rule = policy()
        if rule["activation"] == OWNER and identity.name_of(actor) not in rule["owners"]:
            raise explained(SettingRefused, "by the rule of this installation, {{name}} may not make this value active",
                            name=identity.name_of(actor))
        VERSIONS.retire(c, sid, actor=actor)
    return view(pack_id)


def _versions(rows: list[Any]) -> list[dict[str, Any]]:
    return [{"version": r["version"], "state": r["state"], "value": json.loads(r["value"]), "note": r["note"],
             "made_by": r["made_by"], "made_at": r["made_at"], "activated_by": r["activated_by"],
             "activated_at": r["activated_at"]} for r in rows]


def _own(rows: list[Any]) -> Any:
    active = next((r for r in rows if r["state"] == versions.ACTIVE), None)
    return (json.loads(active["value"]), True) if active else (None, False)


def view(pack_id: str) -> dict[str, Any]:
    """The pack's resources and rule keys: each with its file value, the process's active value (the file's when it
    has none) and its versions newest first; and the rule of who may make a value active."""
    pack = process_packs.load(pack_id)
    with store.connect() as c:
        rows = c.execute("SELECT * FROM process_setting_versions WHERE pack_id=? ORDER BY kind, key, version DESC",
                         (pack_id,)).fetchall()
    by_key: dict[tuple[str, str], list[Any]] = {}
    for r in rows:
        by_key.setdefault((r["kind"], r["key"]), []).append(r)
    resources = []
    effective = effective_resources(pack)
    for key, file_value in pack.resources.items():
        mine = by_key.get((RESOURCE, key), [])
        value, own = _own(mine)
        label, options = resource_info(pack, key)
        if key in pack.derived:  # U3c: shown as its source brings it, read only
            resources.append({"key": key, "label": label, "options": None, "file_value": file_value,
                              "value": effective[key], "own": False, "versions": [], "derived_from": pack.derived[key]})
            continue
        resources.append({"key": key, "label": label,
                          "options": None if options is None else [{"value": v, "label": lbl} for v, lbl in options],
                          "file_value": file_value, "value": value if own else file_value, "own": own,
                          "versions": _versions(mine), "derived_from": None})
    rules = []
    for key, (rule, steps) in rule_keys(pack).items():
        mine = by_key.get((RULE, key), [])
        value, own = _own(mine)
        file_value = rule.file_value()
        titles = {s.id: s.title for s in pack.steps}
        rules.append({"key": key, "file": rule.file, "path": rule.key, "what": rule.what, "kind": rule.kind,
                      "least": rule.least, "most": rule.most, "options": list(rule.options),
                      "steps": [titles.get(s, s) for s in steps],
                      "file_value": file_value, "value": value if own else file_value, "own": own,
                      "versions": _versions(mine)})
    roles = partners.roles()
    titles = {s.id: s.title for s in pack.steps}
    links = [{"role": link.role, "label": (roles.get(link.role) or {}).get("label", link.role), "step": link.from_step,
              "step_title": titles.get(link.from_step, link.from_step)} for link in pack.partners]
    return {"pack": {"id": pack.id, "title": pack.title, "version": pack.version}, "resources": resources, "rules": rules,
            "partners": links, "policy": policy(), "description": _description(pack)}


def _description(pack: process_packs.ProcessPack) -> dict[str, Any]:
    """231 (stage U, U3a; the owner's decision of 2026-10-28: each process its own settings page): what the process is
    for, its steps in order (each with what its capability does, whether a person starts it, the steps it waits for by
    their titles, whether it may be left out), its outputs, the golden sets that measure it, what may start a case of it
    and whether it has example material."""
    titles = {s.id: s.title or s.id for s in pack.steps}
    outputs = cfg.load("outputs").get("outputs", {})
    steps = [{"id": s.id, "title": titles[s.id], "uses": s.uses, "summary": capabilities.of(s.uses).summary,
              "start": s.start, "after": [titles.get(x, x) for x in dict.fromkeys((*s.after, *s.gates))],
              "optional": s.optional} for s in pack.steps]
    return {"summary": pack.summary, "steps": steps,
            "outputs": [{"id": o, "what": outputs.get(o, {}).get("what"), "format": outputs.get(o, {}).get("format")}
                        for o in pack.outputs],
            "goldens": list(pack.goldens),
            "intake": [{"on": i.on, "starts": i.starts, "intent": i.intent} for i in pack.intake],
            "examples": pack.examples is not None and bool(pack.examples.sets or pack.examples.documents
                                                            or pack.examples.note)}


def _case_name(case_id: str) -> str:
    from jav.app import work

    try:
        return str(work.get(case_id)["name"])
    except KeyError:
        return case_id


def _with(over: cfg.Overlay | None, file: str, key: str, value: Any) -> cfg.Overlay:
    values = {name: dict(v) for name, v in (over.values if over else {}).items()}
    values.setdefault(file, {})[key] = value
    return cfg.Overlay(values, over.refs if over else {})


def preview(pack_id: str, key: str, value: Any) -> dict[str, Any]:
    """231 (B3): what the rule value `value` of `key` would have changed, from the decision trace: every decision of the
    process's cases that read the key, its rule run again with the values it was made with and with `value` in place
    of the key's (nothing is written, no AI is asked). A decision whose rule fails is counted, not left out."""
    pack = process_packs.load(pack_id)
    keys = rule_keys(pack)
    if problems := _problems(pack, RULE, key, value):
        raise explained(SettingError, "the process cannot take this value: {{problems}}", problems="; ".join(problems))
    rule = keys[key][0]
    from jav.app import process_runtime

    packs: dict[str, str | None] = {}
    decided = changed = failed = 0
    examples: list[dict[str, Any]] = []
    first_error: str | None = None
    for row in trace.reading(trace.file_of(rule.file), rule.key):
        case_id = row.get("case_id")
        if case_id and case_id not in packs:
            packs[case_id] = (process_runtime.pack_of(case_id) or (None, None))[0]
        if not case_id or packs[case_id] != pack.id:
            continue
        decided += 1
        try:
            before = trace.replay(row)
            after = trace.replay(row, over=_with(trace.recorded_overlay(row), rule.file, rule.key, value))
        except Exception as exc:  # noqa: BLE001 - a rule that fails on this value is counted in the preview, the first named
            failed += 1
            first_error = first_error or f"{row['point']}: {type(exc).__name__}: {exc}"
            continue
        if after != before:
            changed += 1
            if len(examples) < PREVIEW_EXAMPLES:
                examples.append({"point": row["point"], "subject": f"{row['subject_kind']}:{row['subject_id']}",
                                 "case_id": case_id, "case": _case_name(case_id), "at": row["at"], "before": before,
                                 "after": after})
    return {"key": key, "value": value, "file_value": rule.file_value(), "decisions": decided, "changed": changed,
            "failed": failed, "first_error": first_error, "examples": examples}
