"""The lists of Settings as datasets (263, plan E, E1; the owner's decisions of 2026-10-30: one list everywhere,
searchable, sortable and grouped by more than one thing, a row opening its thing's page).

Each list here is the shared table (`jav/app/tablequery.py`): the processes, the partners with the own parties, the
product registry's products, tariffs, rules, condition documents and rule proposal runs, the own output templates and
the letter frames (the price lists and the own parties are their domains' lists, registered by them). A row's link opens the thing's
page in Settings (`link="settings"`, with the column's `section` and `list`; an own party's row names its own section in
`_settings`). The columns a list may be grouped by say so (`group=True`). A text a person reads (a process's title, a
rule's kind) comes in the request's language (`jav/core/display.py`), so the search and the order go by what is shown.
The lists are cheap to build and have no cache: a change shows at the next request.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

from jav.app import app_settings, datasets, partners, process_packs, product_rules, rule_proposal_runs
from jav.app.datasets import Dataset, LabelSet, Rows, col
from jav.app.tablequery import fold
from jav.core import display, store, versions

_STATE = {versions.ACTIVE: "Active", versions.DRAFT: "Draft", versions.RETIRED: "Retired"}
# the state marks of the interface (`ui/src/components/VersionState.tsx`): active green, a draft a ring, retired a dash
_MARKS = {versions.ACTIVE: "done", versions.DRAFT: "trial", versions.RETIRED: "removed"}
_RULE_KIND = {"eligibility": "Eligibility", "exclusion": "Exclusion", "requirement": "Requirement", "sublimit": "Sublimit",
              "deductible": "Deductible", "premium_factor": "Premium factor", "valuation": "Valuation", "obligation": "Obligation"}
_DOCUMENT_KIND = {"general": "General conditions", "special": "Special conditions", "supplementary": "Supplementary rules",
                  "clause": "Clause"}
_PARTNER_KIND = {"partner": "Partner", "own": "Own party"}
_RUN_STATE = {"queued": "Queued", "running": "Running", "done": "Done", "failed": "Failed"}
# the outputs an own template may serve (the interface's names, `ui/src/views/settings/OutputTemplatesPanel.tsx`)
_OUTPUT = {"package_result": "Package result", "utility_cost": "Utility cost", "reconcile_statement": "Reconciliation statement",
           "quote": "Quote", "rated_offer": "Rated offer"}
_FRAME_STATE = {"own": "Its own text", "system": "The system's text"}
_FRAME_MARKS = {"own": "done", "system": "held"}
_RUN_MARKS = {"queued": "queued", "running": "running", "done": "done", "failed": "failed"}


def _state_col() -> Any:
    return col("state", "State", "enum", labels="registry_state", badge=True, marks=_MARKS, group=True)


def _thing_state(thing: dict[str, Any]) -> str:
    """A registry thing's state: retired, active (a version in use) or a draft only."""
    if thing.get("retired"):
        return versions.RETIRED
    return versions.ACTIVE if thing.get("active") is not None else versions.DRAFT


def _shown(thing: dict[str, Any]) -> dict[str, Any]:
    """The version a list shows: the one in use, else the newest (a draft)."""
    return next((v for v in thing["versions"] if v["version"] == thing.get("active")), thing["versions"][0])


def _short(title: str) -> str:
    """A condition document's short name: the code in its title's last brackets ("… (GC-2026)"), else the title."""
    head, _, rest = title.rpartition("(")
    return rest.rstrip(") ").strip() if head and rest.rstrip().endswith(")") else title


def _processes(_scope: dict[str, str]) -> Rows:
    from jav.app import intake

    cols = [
        col("title", "Process", link="settings", section="processes"),
        col("summary", "What it is for", clamp=2),
        col("steps", "Steps", "number"),
        col("repeats", "Repeats by period", "bool", group=True),
        col("manual", "Started by hand", "bool", group=True),
        col("version", "Version", hidden=True),
    ]
    rows = [{"_key": p.id, "title": display.text(p.title), "summary": display.text(p.summary) if p.summary else None,
             "steps": len(p.steps), "repeats": p.repeats, "manual": any(i.on == intake.MANUAL for i in p.intake),
             "version": p.version} for p in process_packs.packs()]
    return cols, rows


def _partners(_scope: dict[str, str]) -> Rows:
    roles = partners.roles()
    cols = [
        col("name", "Name", link="settings", section="partners"),
        col("kind", "Kind", "enum", labels="partner_kind", group=True),
        col("role", "First role", "enum", labels="partner_role", group=True, hidden=True),
        col("roles", "Roles"),
        col("tax_number", "Tax number", "id"),
        col("email", "Email"),
        col("state", "State", "enum", labels="registry_state", badge=True, marks=_MARKS, group=True),
        col("changed_at", "Changed", "datetime"),
    ]
    rows = [{"_key": p["partner_id"], "name": p["name"], "kind": "partner", "role": p["roles"][0] if p["roles"] else None,
             "roles": " · ".join(display.text(roles[r]["label"]) if r in roles else r for r in p["roles"]),
             "tax_number": p["tax_number"], "email": p["email"],
             "state": versions.RETIRED if p["retired"] else versions.ACTIVE, "changed_at": p["changed_at"]}
            for p in partners.listing(retired=True)]
    # 231 (U3e): the own parties among them, each edited in its own register
    rows += [{"_key": f"own:{o['party_id']}", "_settings": ["parties"], "name": o["name"], "kind": "own", "role": None,
              "roles": display.text("Own party"), "tax_number": o["tax_number"], "email": None, "state": versions.ACTIVE,
              "changed_at": o["changed_at"]} for o in partners.own_listing()]
    return cols, sorted(rows, key=lambda r: fold(r["name"]))  # by name, the own parties among them


def _users(_scope: dict[str, str]) -> Rows:
    """264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): the names "Who is
    working?" offers, each opening its own page."""
    cols = [col("name", "Name", link="settings", section="users"), col("added", "Added", "datetime")]
    return cols, [{"_key": u["name"], "name": u["name"], "added": u["created_at"]} for u in app_settings.user_rows()]


def _folders(_scope: dict[str, str]) -> Rows:
    """264 (plan E, F6): the watched work folders - the path, whether it is on, the packaging, how often it is checked
    and how its last check ended (its batch linked) - each opening its own page."""
    cols = [
        col("name", "Name", link="settings", section="folders"),
        col("path", "Full folder path", wrap="anywhere", clamp=2),
        col("state", "State", "enum", labels="folder_state", badge=True, group=True, marks={"on": "done", "off": "muted"}),
        col("batch_mode", "Packaging", "enum", labels="folder_batch_mode", group=True),
        col("recursive", "Include subfolders", "bool", hidden=True),
        col("interval_min", "Look over", "enum", labels="folder_interval", group=True),
        col("last_at", "Last check", "datetime"),
        col("last_status", "Its outcome", "enum", labels="folder_check", badge=True, group=True),
        col("last_new", "New documents", "number"),
        col("last_batch", "Batch", "enum", labels="folder_batch", link="workpackage"),
    ]
    rows = []
    for f in app_settings.folders():
        last = f.get("last_result") or {}
        rows.append({"_key": f["id"], "_wp": last.get("workpackage"), "name": f["name"], "path": f["path"],
                     "state": "on" if f["enabled"] else "off", "batch_mode": f["batch_mode"], "recursive": f["recursive"],
                     "interval_min": str(f["interval_min"]), "last_at": f.get("last_at"), "last_status": f.get("last_status"),
                     "last_new": last.get("new") if f.get("last_status") == "ok" else None,
                     "last_batch": "batch" if last.get("workpackage") else None})
    return cols, rows


_FOLDER_LABELS = (
    ("folder_state", {"on": "Active (state)", "off": "Off (value)"}),
    ("folder_batch_mode", {"folder": "One shared batch", "daily": "Daily batches"}),
    ("folder_interval", {"5": "every 5 minutes", "15": "every 15 minutes", "30": "every 30 minutes", "60": "hourly",
                         "240": "every 4 hours", "1440": "daily"}),
    ("folder_check", {"ok": "Done", "error": "Failed (value)"}),
    ("folder_batch", {"batch": "batch"}),
)


def _partner_proposals(_scope: dict[str, str]) -> Rows:
    """264 (plan E, F6): the partner register's proposals from the data (the domains' sources: an incoming invoice's
    supplier, an outgoing invoice's buyer) - each party with its tax number, the roles it was seen in, how many
    documents and when last - grouped by its first role; a row's "Accept" opens the new partner's form from it."""
    roles = partners.roles()
    cols = [
        col("name", "Name"),
        col("tax_number", "Tax number", "id"),
        col("role", "First role", "enum", labels="partner_role", group=True),
        col("roles", "Seen as"),
        col("seen", "Documents", "number"),
        col("last", "Last", "date"),
        col("sources", "Source", hidden=True),
    ]
    rows = [{"_key": s["tax_number"] or f"name:{s['name']}", "name": s["name"], "tax_number": s["tax_number"],
             "role": s["roles"][0] if s["roles"] else None,
             "roles": " · ".join(display.text(roles[r]["label"]) if r in roles else r for r in s["roles"]),
             "seen": s["seen"], "last": s["last"], "sources": ", ".join(s["sources"]),
             "_roles": s["roles"]}  # the new partner's form starts from them
            for s in partners.suggestions(limit=100_000)]
    return cols, rows


# 264 (F6): what the proposals read - the results and their corrections, the register itself and the own parties
_PROPOSAL_INPUTS = {"run_items": "MAX(updated_at)", "run_item_corrections": None, "workpackage_items": None,
                    "partner_versions": "SUM(state='active')", "own_parties": None, "own_party_identities": None,
                    "duplicate_decisions": None}


def _proposals_fingerprint(_scope: dict[str, str]) -> str:
    """Reading the proposals goes through every invoice, so the list is kept until what it reads changes."""
    with store.connect() as c:
        parts = [store.table_marks(c, _PROPOSAL_INPUTS), sorted(partners.suggestion_sources())]
    return hashlib.sha256(json.dumps(parts, default=str).encode("utf-8")).hexdigest()


# the tables of the outputs, by their contract keys (`configs/outputs.json`), as the interface names them
_TABLE_TITLES = {"native_facts": "Native facts", "native_readings": "Native readings", "emails": "Emails", "tasks": "Tasks",
                 "documents": "Documents", "datapoints": "Data points", "line_items": "Line items", "utility_cost": "Utility cost",
                 "utility_sources": "Utility cost sources", "invoices": "Invoices", "lines": "Statement lines"}
_MARKER_KIND = {"text": "text", "date": "date", "money": "amount", "number": "number", "count": "count",
                "probability": "probability", "flag": "yes or empty", "json": "structured text", "months": "months"}


def _output_markers(scope: dict[str, str]) -> Rows:
    """264 (plan E, F6): the markers an own template of an output may use (Settings › Output templates › The markers) -
    each with its label, its kind and the marker of its total - grouped by the table it belongs to (the values first);
    a table's row count and its months are rows of their own kind in its group."""
    from jav.app.outputs import samples

    groups = samples.markers(scope["output"])
    tables: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for g in groups:
        key = "values" if g["table"] is None else f"{g['table']}:{g['part']}" if g["part"] else g["table"]
        title = display.text("Values (each written once)") if g["table"] is None else display.text(_TABLE_TITLES.get(g["table"], g["table"]))
        tables[key] = f"{title}: {g['label'] or g['part']}" if g["part"] else title
        extra = ([{"marker": g["count"], "label": display.text("row count"), "kind": "count", "sum": None}] if g["count"] else [])
        if g["months"]:
            extra += [{"marker": g["months"]["row"], "label": display.text("months"), "kind": "months", "sum": None},
                      {"marker": g["months"]["names"], "label": display.text("the months' names"), "kind": "months", "sum": None}]
        rows += [{"_key": r["marker"], "marker": r["marker"], "label": display.text(r["label"]), "kind": r["kind"], "sum": r["sum"],
                  "table": key} for r in [*g["rows"], *extra]]
    cols = [
        col("marker", "Marker", "id"),
        col("label", "Label in the built-in template"),
        col("kind", "Kind", "enum", labels="marker_kind", group=True),
        col("sum", "Total", "id"),
        replace(col("table", "Table", "enum", group=True), labels=tables),
    ]
    return cols, rows


# 264 (F6): a workflow step's state, as the workflow screens say it (`ui/src/views/workflows/labels.ts`), and its mark
_STEP_STATUS = {"waiting": "waits for its earlier steps", "ready": "ready to start", "starting": "starting…",
                "pulling": "downloading the emails…", "needs_budget": "waits for a budget", "nothing_new": "nothing new: done",
                "failed": "did not start", "running": "running", "review": "to-dos in its package", "approve": "awaiting approval",
                "approved": "approved", "pairing": "pairing in its package", "attention": "needs a person in its package",
                "missing": "its package is missing", "stale": "out of date"}
_STEP_MARKS = {"approved": "done", "nothing_new": "done", "failed": "failed", "missing": "failed", "needs_budget": "review",
               "review": "review", "approve": "review", "attention": "review", "pairing": "review", "running": "running",
               "pulling": "running", "starting": "queued", "waiting": "waiting", "stale": "waiting", "ready": "startable"}
_WORKFLOW_STATUS = {"open": "Open", "archived": "Archived"}


def _earlier_workflows(_scope: dict[str, str]) -> Rows:
    """264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): the workflows made before
    the processes (Settings › Operations › Earlier workflows) - each with its template, party, period, how many of its
    steps are done, its next step and its state - each opening its own page; the archived ones among them."""
    from jav.app import workflow_records

    cols = [
        col("name", "Name", link="workflow"),
        col("template", "Template", group=True),
        col("party", "Own party", group=True),
        col("period", "Period"),
        col("done", "Steps done", "number"),
        col("total", "Steps", "number", hidden=True),
        col("next_step", "Next"),
        col("next_status", "Its state", "enum", labels="workflow_step_status", badge=True, group=True, marks=_STEP_MARKS),
        col("status", "State", "enum", labels="workflow_status", badge=True, group=True, marks={"open": "done", "archived": "muted"}),
        col("updated_at", "Changed", "datetime"),
    ]
    rows = []
    for w in workflow_records.workflows(include_archived=True):
        nxt = next((s for s in w["steps"] if w["next"] and s["id"] == w["next"]["step"]), None)
        rows.append({"_key": w["id"], "name": w["name"], "template": display.text(w["template_title"]), "party": w.get("party"),
                     "period": f"{w['period_start']} – {w['period_end']}" if w.get("period_start") else None,
                     "done": w["done"], "total": w["total"], "next_step": display.text(nxt["title"]) if nxt else None,
                     "next_status": w["next"]["status"] if w["next"] else None, "status": w["status"],
                     "updated_at": w.get("updated_at"),
                     "_steps": [{"title": display.text(s["title"]), "status": s["status"]} for s in w["steps"]]})
    return cols, rows


def _registry(kind: str) -> list[dict[str, Any]]:
    return product_rules.listing(kind)


def _products(_scope: dict[str, str]) -> Rows:
    tariffs = {t["ident"]: _shown(t)["content"] for t in _registry("tariff")}
    cols = [
        col("name", "Name", link="settings", section="products", list="products"),
        _state_col(),
        col("version", "Version", "number"),
        col("modules", "Cover modules", clamp=2),
        col("rules", "Rules", "number"),
        col("tariff", "Tariff"),
        col("catalogue", "Fact catalogue", "enum", group=True, hidden=True),
    ]
    rows = []
    for thing in _registry("product"):
        v = _shown(thing)
        c = v["content"]
        tariff = tariffs.get(c.get("tariff") or "")
        rows.append({"_key": thing["ident"], "name": v.get("name") or thing["name"], "state": _thing_state(thing),
                     "version": v["version"], "modules": " · ".join(m["name"] for m in c.get("modules", [])),
                     "rules": len(c.get("rules", [])), "tariff": (tariff or {}).get("title") or c.get("tariff"),
                     "catalogue": c.get("catalogue")})
    return cols, rows


def _tariffs(_scope: dict[str, str]) -> Rows:
    cols = [
        col("title", "Title", link="settings", section="products", list="tariffs"),
        _state_col(),
        col("version", "Version", "number"),
        col("currency", "Currency", "enum", group=True),
        col("valid_from", "Valid from", "date"),
        col("valid_to", "Valid until", "date"),
        col("modules", "Cover modules", "number"),
    ]
    rows = []
    for thing in _registry("tariff"):
        v = _shown(thing)
        c = v["content"]
        rows.append({"_key": thing["ident"], "title": c.get("title") or thing["ident"], "state": _thing_state(thing),
                     "version": v["version"], "currency": c.get("currency"), "valid_from": (c.get("valid") or {}).get("valid_from"),
                     "valid_to": (c.get("valid") or {}).get("valid_to"), "modules": len(c.get("modules") or {})})
    return cols, rows


def _rules(_scope: dict[str, str]) -> Rows:
    from jav.app import facts

    documents = {v["ref"]: v["content"] for d in _registry("document") for v in d["versions"]}
    labels: dict[str, dict[str, str]] = {}

    def level(catalogue: str, code: str) -> str:
        if catalogue not in labels:
            try:
                labels[catalogue] = dict(facts.catalogue(catalogue).labels)
            except FileNotFoundError:
                labels[catalogue] = {}
        return display.text(labels[catalogue].get(code, code))

    cols = [
        col("title", "Title", link="settings", section="products", list="rules"),
        col("kind", "Kind", "enum", labels="rule_kind", group=True),
        col("level", "Level", "enum", group=True),
        col("document", "Read from", "enum", group=True),
        col("clause", "Clause"),
        _state_col(),
        col("version", "Version", "number", hidden=True),
    ]
    rows = []
    for thing in _registry("rule"):
        v = _shown(thing)
        c = v["content"]
        source = c.get("source") or {}
        doc = documents.get(source.get("document") or "")
        rows.append({"_key": thing["ident"], "title": c.get("title") or thing["name"], "kind": c.get("kind"),
                     "level": level(c.get("catalogue", ""), c.get("level", "")),
                     "document": _short(doc["title"]) if doc else source.get("document"),
                     "clause": " · ".join(x for x in (source.get("clause"), None if source.get("page") is None
                                                       else display.text("p. {{n}}", n=source["page"])) if x),
                     "state": _thing_state(thing), "version": v["version"]})
    return cols, rows


def _documents(_scope: dict[str, str]) -> Rows:
    cols = [
        col("title", "Title", link="settings", section="products", list="documents"),
        col("kind", "Kind", "enum", labels="document_kind", group=True),
        col("valid_from", "In force from", "date"),
        col("valid_to", "In force until", "date"),
        col("clauses", "Clauses", "number"),
        _state_col(),
        col("version", "Version", "number", hidden=True),
    ]
    rows = []
    for thing in _registry("document"):
        v = _shown(thing)
        c = v["content"]
        rows.append({"_key": thing["ident"], "title": c.get("title") or thing["name"], "kind": c.get("kind"),
                     "valid_from": c.get("valid_from"), "valid_to": c.get("valid_to"), "clauses": len(c.get("sections") or []),
                     "state": _thing_state(thing), "version": v["version"]})
    return cols, rows


def _proposal_runs(_scope: dict[str, str]) -> Rows:
    titles = {v["ref"]: v["content"].get("title") for d in _registry("document") for v in d["versions"]}
    cols = [
        col("file", "File", link="settings", section="products", list="proposals"),
        col("document", "Condition document"),
        col("proposer", "Proposer", "enum", group=True),
        col("state", "State", "enum", labels="proposal_run_state", badge=True, marks=_RUN_MARKS, group=True),
        col("proposals", "Proposals", "number"),
        col("requested_by", "Requested by", "enum", group=True),
        col("requested_at", "Requested", "datetime"),
    ]
    rows = [{"_key": r["run_id"], "file": r["file"], "document": titles.get(r["document_ref"]) or r["document_ref"],
             "proposer": display.text("Stand-in (free)") if r["stand_in"] else "GPT", "state": r["state"],
             "proposals": sum((r.get("counts") or {}).values()), "requested_by": r["requested_by"], "requested_at": r["requested_at"]}
            for r in rule_proposal_runs.runs()]
    return cols, rows


def _templates(_scope: dict[str, str]) -> Rows:
    from jav.app.outputs import templates

    cols = [
        col("name", "Name", link="settings", section="outputs"),
        col("output", "Output", "enum", labels="output_name", group=True),
        _state_col(),
        col("version", "Version", "number"),
        col("versions", "Versions", "number", hidden=True),
        col("file", "File"),
        col("warnings", "Warnings", "number"),
        col("uploaded_by", "Uploaded by", "enum", group=True),
        col("uploaded_at", "Uploaded", "datetime"),
    ]
    rows = []
    for x in templates.listing():
        v = _shown(x)
        rows.append({"_key": x["template"], "name": x["name"], "output": x["output"], "state": _thing_state(x),
                     "version": v["version"], "versions": len(x["versions"]), "file": v.get("file_name"),
                     "warnings": len(((v.get("checks") or {}).get("warnings")) or []), "uploaded_by": v.get("uploaded_by"),
                     "uploaded_at": v.get("uploaded_at")})
    return cols, rows


def _frames(_scope: dict[str, str]) -> Rows:
    from jav.app import letter_frames

    cols = [
        col("name", "Letter frame", link="settings", section="letters"),
        col("kind", "Kind", "enum", group=True),
        col("language", "Language", "enum", group=True),
        col("state", "Text", "enum", labels="frame_state", badge=True, marks=_FRAME_MARKS, group=True),
        col("version", "Version in use", "number"),
        col("drafts", "Drafts", "number"),
        col("changed_at", "Changed", "datetime"),
        col("ident", "Code", "id", hidden=True),
    ]
    rows = []
    for k in letter_frames.listing()["kinds"]:
        for f in k["frames"]:
            newest = f["versions"][0] if f["versions"] else None
            rows.append({"_key": f"{k['kind']}/{f['ident']}", "_settings": ["letters", k["kind"], f["ident"]],
                         # its name is the subject of the letter in effect (document vocabulary, as a client reads it)
                         "name": str(f["content"].get("subject") or f["ident"]), "kind": display.text(k["title"]),
                         "language": f["content"].get("language"), "ident": f["ident"],
                         "state": "own" if f["active"] else "system", "version": f["active"],
                         "drafts": sum(1 for v in f["versions"] if v["state"] == versions.DRAFT),
                         "changed_at": newest["made_at"] if newest else None})
    return cols, rows


def library_names() -> dict[str, str]:
    """263 (E1; the owner's request of 2026-10-30: a process's "What it uses" showed codes): the readable name of every
    thing of the shared library a process may use, by its code - a product and a tariff by their name (a draft's too),
    an output template by its name, a letter frame by its subject, an output by its name - so a page names a thing
    wherever a name exists, not only for the active choices."""
    from jav.app import letter_frames
    from jav.app.outputs import templates

    names: dict[str, str] = {}
    for kind in ("product", "tariff"):
        for thing in _registry(kind):
            v = _shown(thing)
            names[thing["ident"]] = str((v["content"].get("title") if kind == "tariff" else None) or v.get("name") or thing["name"])
    for x in templates.listing():
        names[x["template"]] = x["name"]
    for k in letter_frames.listing()["kinds"]:
        for f in k["frames"]:
            names[f["ident"]] = str(f["content"].get("subject") or f["ident"])
    names |= {code: display.text(name) for code, name in _OUTPUT.items()}
    return names


_LABEL_SETS = tuple(LabelSet(name, __name__, labels.copy) for name, labels in (
    ("registry_state", _STATE), ("rule_kind", _RULE_KIND), ("document_kind", _DOCUMENT_KIND), ("partner_kind", _PARTNER_KIND),
    ("proposal_run_state", _RUN_STATE), ("output_name", _OUTPUT), ("frame_state", _FRAME_STATE), *_FOLDER_LABELS,
    ("marker_kind", _MARKER_KIND), ("workflow_step_status", _STEP_STATUS), ("workflow_status", _WORKFLOW_STATUS)))
_ROLE_LABELS = LabelSet("partner_role", __name__, lambda: {k: v["label"] for k, v in partners.roles().items()})

DATASETS = (
    Dataset("settings_processes", "Processes", (), _processes),
    Dataset("settings_partners", "Partners", (), _partners, natural_sort=(("name", False),)),
    Dataset("settings_products", "Products", (), _products),
    Dataset("settings_tariffs", "Tariffs", (), _tariffs),
    Dataset("settings_rules", "Rules", (), _rules),
    Dataset("settings_documents", "Condition documents", (), _documents),
    Dataset("settings_proposal_runs", "Rule proposals", (), _proposal_runs, natural_sort=(("requested_at", True),)),
    Dataset("settings_output_templates", "Output templates", (), _templates),
    Dataset("settings_letter_frames", "Letter frames", (), _frames),
    Dataset("settings_users", "Users", (), _users, natural_sort=(("name", False),)),  # 264 (F6)
    Dataset("settings_folders", "Work folders", (), _folders, natural_sort=(("name", False),)),
    Dataset("settings_partner_proposals", "Partner proposals", (), _partner_proposals, _proposals_fingerprint,
            natural_sort=(("seen", True),)),
    Dataset("output_markers", "Template markers", ("output",), _output_markers),
    Dataset("earlier_workflows", "Earlier workflows", (), _earlier_workflows, natural_sort=(("updated_at", True),)),
)


def register() -> None:
    for labels in (*_LABEL_SETS, _ROLE_LABELS):
        datasets.register_labels(labels)
    after = "started_cases"
    for ds in DATASETS:
        datasets.register(ds, after=after, module=__name__)
        after = ds.name


__all__ = ["DATASETS", "library_names", "register"]
