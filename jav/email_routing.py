"""The email routing: a logic pack that proposes, for every document that arrived by email, the package it belongs to
(181, plan 170 L5; DECISIONS 181: the owner asked for it, "recognise an emailed invoice, statement or sent outgoing
invoice and route it to the right work package").

Plain-language summary: an email package downloads the emails of a mailbox; each PDF attachment becomes a document of
that package, and its type and data are read there. A routing package looks at the attachments of one or more email
packages. For each one whose result places it (an incoming invoice, an outgoing invoice, a bank statement of an own
party, with a day), it proposes the open package whose scope fits it (the same role and party, the day in its period;
`jav/package_scope.py`), or a new package for the party, the day's calendar month and the role. A person accepts the
proposals (one by one, or every clear one at once), rejects them or chooses another package. Accepting adds the
document to the package; its run is started by a person, or by the workflow within its approved budget. An attachment
the routing cannot place by itself is a blocker: no result yet, no own party, an unclear direction (or an invoice
between two own parties), no date, a suspicious email, or an incoming invoice in a sent email. A document of another
kind (a contract, say) is only listed. The routing package is done when every attachment it can route is decided.

Code only, no AI call; the placement of a document is the domains' (`package_scope.place`).

- `create(name, sources, actor)`: a routing package over email packages.
- `view(wp_id)`: every attachment with its email, its placement, the proposal and the decision; the counts.
- `accept(wp_id, item_ids, actor, target=None)`, `reject(...)`, `undo(...)`: a person's decisions.
- `LOGIC`, `STEP`: the logic pack and the workflow step (registered by the email domain, `jav/domains/email.py`).

Layer: application operation (it adds documents to packages through `jav/work.py` and the statement package's own
adding).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jav import activity_kinds, logic_packs, package_result, package_scope, source_instances, store, work, workflow_steps
from jav.user_messages import explained

KIND = "email_routing"
# the actions this module records in a routing package's log (`jav/activity_kinds.py`)
activity_kinds.register_events("package", ("routing_accept", "routing_reject", "routing_undo"), __name__)

store.register_schema("email_routing", """
CREATE TABLE IF NOT EXISTS email_routing_scopes (
    workpackage_id TEXT PRIMARY KEY,
    sources        TEXT NOT NULL,      -- JSON: the email packages whose attachments it routes
    actor          TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS email_routing_decisions (
    workpackage_id TEXT NOT NULL,
    item_id        TEXT NOT NULL,      -- the attachment (its content hash)
    decision       TEXT NOT NULL,      -- accepted | rejected
    target         TEXT,               -- accepted: the package it was added to
    made           INTEGER NOT NULL DEFAULT 0,  -- accepted: the package was made for it
    actor          TEXT NOT NULL,
    decided_at     TEXT NOT NULL,
    PRIMARY KEY (workpackage_id, item_id)
);
""")

# what keeps an attachment from being routed by itself (the interface names each)
BLOCKERS = ("no_result", "unknown_party", "unclear_direction", "internal", "not_own", "no_day", "suspicious",
            "sent_incoming")


class RoutingError(ValueError):
    """A routing request that cannot be met: no email package, an unknown attachment, a target that cannot take it."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- making one ---------------------------------------------------------------------------------------------------------


def _email_packages(sources: list[str]) -> list[str]:
    if not sources:
        raise explained(RoutingError, "choose at least one email package")
    out = []
    for wp_id in dict.fromkeys(sources):
        try:
            wp = work.get(wp_id)
        except KeyError as exc:
            raise explained(RoutingError, "no work package {{wp_id}}", wp_id=repr(wp_id)) from exc
        if not any(i["kind"] == "email" for i in wp["items"]):
            raise explained(RoutingError, "work package {{name}} has no email", name=repr(wp["name"]))
        out.append(wp_id)
    return out


def create(*, name: str, sources: list[str], actor: str) -> dict[str, Any]:
    """A routing package over the given email packages (their attachments as they are now and as they come later)."""
    chosen = _email_packages(sources)
    wp = work.create_workpackage(name=name, source_kind=KIND, source_ref=None, owner=actor)
    with store.connect() as c:
        store.begin_immediate(c)
        c.execute("INSERT INTO email_routing_scopes(workpackage_id, sources, actor, created_at) VALUES (?,?,?,?)",
                  (wp["id"], json.dumps(chosen), actor, _now()))
    return {"workpackage_id": wp["id"], "sources": chosen}


def sources_of(wp_id: str) -> list[str]:
    with store.connect() as c:
        row = c.execute("SELECT sources FROM email_routing_scopes WHERE workpackage_id=?", (wp_id,)).fetchone()
    if row is None:
        raise KeyError(wp_id)
    return json.loads(row["sources"])


# --- what each attachment is -----------------------------------------------------------------------------------------------


def _email_of(item: dict[str, Any]) -> dict[str, Any]:
    """The email an attachment came with: its subject, sender, day and folder (the message as downloaded)."""
    from jav import emails

    try:
        msg = emails.load_message_dir(Path(item["source_path"]).parent)
    except (OSError, ValueError):
        return {"item_id": item["item_id"], "subject": None, "sender": None, "received_at": None, "folder": None}
    return {"item_id": item["item_id"], "subject": msg.subject, "sender": msg.sender, "received_at": msg.received_at,
            "folder": msg.folder}


def _attachments(sources: list[str]) -> list[dict[str, Any]]:
    """The attachments of the email packages in use, each once (the first package's), with its email."""
    seen: set[str] = set()
    out = []
    for wp_id in sources:
        try:
            wp = work.get(wp_id)
        except KeyError:
            continue
        mails = {i["item_id"]: i for i in wp["items"] if i["kind"] == "email"}
        for i in wp["items"]:
            if i["kind"] == "email" or not i.get("parent_item_id") or i["item_id"] in seen:
                continue
            seen.add(i["item_id"])
            mail = mails.get(i["parent_item_id"])
            out.append({"item_id": i["item_id"], "file": Path(i["source_path"]).name, "path": _file_of(i),
                        "package": wp_id, "email": _email_of(mail) if mail else None})
    return out


def _file_of(item: dict[str, Any]) -> str:
    """The attachment's file to add elsewhere: where it was downloaded, else its copy taken when it was added."""
    original = Path(item["source_path"])
    if not original.is_file() and item.get("instance"):
        copy = source_instances.path_of(item["instance"])
        if copy.is_file():
            return str(copy)
    return str(original)


def _results(c: sqlite3.Connection, doc_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Each attachment's counted result (`jav/package_result.py`): its type, its effective values, its tier and whether
    it came from a suspicious email (154: the attachment's to-do)."""
    from jav.mailbox import SUSPICIOUS_ATTACHMENT

    counted = package_result.counted_documents(c, doc_ids)
    rows = package_result.result_rows(c, counted, "datapoints")
    corrected = package_result.latest_corrections(c)
    suspicious = {r["run_id"] for r in c.execute("SELECT DISTINCT run_id FROM review_reasons WHERE reason=?",
                                                 (SUSPICIOUS_ATTACHMENT,))}
    out = {}
    for r in rows:
        x = counted[r["doc_id"]]
        values = package_result.effective_values(json.loads(r["datapoints"] or "{}"),
                                                 corrected.get((x.work_run, x.item_id)))
        out[r["doc_id"]] = {"doc_type": r["doc_type"], "values": values, "tier": x.tier,
                            "suspicious": r["run_id"] in suspicious}
    return out


def _month(day: str) -> tuple[str, str]:
    d = date.fromisoformat(day)
    first = d.replace(day=1)
    last = (first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1))
    return first.isoformat(), (last - timedelta(days=1)).isoformat()


def _placement(att: dict[str, Any], result: dict[str, Any] | None, cache: dict[str, Any]) -> dict[str, Any]:
    """Where an attachment belongs (role, party, day) and what keeps it from being routed by itself; `routable`: it is
    a document of a role at all (another kind is only listed)."""
    if result is None:
        return {"routable": True, "role": None, "party_id": None, "day": None, "problem": "no_result"}
    found = package_scope.place(result["doc_type"], result["values"], cache)
    if found is None:
        return {"routable": False, "role": None, "party_id": None, "day": None, "problem": None}
    problem = found.problem
    folder = (att.get("email") or {}).get("folder")
    if problem is None and result["suspicious"]:
        problem = "suspicious"
    if problem is None and folder == "sent" and found.direction == "incoming":
        problem = "sent_incoming"  # a sent email carries what the own party sends
    if problem is None and found.day is None:
        problem = "no_day"
    return {"routable": True, "role": found.role, "party_id": found.party_id, "day": found.day, "problem": problem}


def _proposal(placement: dict[str, Any], party_names: dict[str, str], among: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The package proposed for a placed attachment: the open package whose scope fits it (the latest changed of
    several, the others offered too), or a new one for its party, its day's calendar month and its role."""
    if placement["problem"] is not None or placement["role"] is None:
        return None
    fits = package_scope.fitting(placement["role"], placement["party_id"], placement["day"], among=among)
    if fits:
        return {"target": {"id": fits[0]["id"], "name": fits[0]["name"]},
                "others": [{"id": f["id"], "name": f["name"]} for f in fits[1:]], "new": None}
    start, end = _month(placement["day"])
    role = package_scope.role(placement["role"])
    name = f"{party_names.get(placement['party_id'], placement['party_id'])} · {start[:7]} · {role.title}"
    return {"target": None, "others": [], "new": {"name": name, "party_id": placement["party_id"], "period_start": start,
                                                   "period_end": end, "role": placement["role"]}}


def _decisions(wp_id: str) -> dict[str, dict[str, Any]]:
    with store.connect() as c:
        return {r["item_id"]: dict(r) for r in c.execute(
            "SELECT item_id, decision, target, made, actor, decided_at FROM email_routing_decisions WHERE workpackage_id=?",
            (wp_id,))}


def view(wp_id: str) -> dict[str, Any]:
    """The routing package's attachments, each with its email, its result, its placement, the proposal, the decision
    and whether the decided package holds it; the counts and the email packages."""
    from jav import parties

    sources = sources_of(wp_id)
    atts = _attachments(sources)
    with store.connect() as c:
        results = _results(c, [a["item_id"] for a in atts]) if atts else {}
    party_names = {p["id"]: p["name"] for p in parties.parties()}
    decided = _decisions(wp_id)
    held = _held(atts, decided)
    among = package_scope.scoped_packages() if atts else []
    names = _names({d["target"] for d in decided.values() if d["target"]})
    cache: dict[str, Any] = {}
    rows = []
    for a in atts:
        res = results.get(a["item_id"])
        placement = _placement(a, res, cache)
        role = package_scope.role(placement["role"]) if placement["role"] else None
        dec = decided.get(a["item_id"])
        rows.append({"item_id": a["item_id"], "file": a["file"], "package": a["package"], "email": a["email"],
                     "doc_type": res["doc_type"] if res else None, "tier": res["tier"] if res else None,
                     "placement": placement | {"party": party_names.get(placement["party_id"]) if placement["party_id"] else None,
                                               "role_title": role.title if role else None},
                     "proposal": _proposal(placement, party_names, among) if placement["routable"] and not dec else None,
                     "decision": dec | {"target_name": names.get(dec["target"])} if dec else None,
                     "held": held.get(a["item_id"])})
    routable = [r for r in rows if r["placement"]["routable"]]
    counts = {"attachments": len(rows), "routable": len(routable),
              "decided": sum(1 for r in routable if r["decision"]),
              "blocked": sum(1 for r in routable if not r["decision"] and r["placement"]["problem"]),
              "clear": sum(1 for r in routable if not r["decision"] and r["proposal"]),
              "accepted": sum(1 for r in routable if (r["decision"] or {}).get("decision") == "accepted")}
    source_names = _names(set(sources))
    return {"sources": [{"id": s, "name": source_names.get(s)} for s in sources], "items": rows, "counts": counts}


def _names(ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    with store.connect() as c:
        return {r["id"]: r["name"] for r in c.execute(
            f"SELECT id, name FROM workpackages WHERE id IN ({','.join('?' * len(ids))})", sorted(ids))}


def _held(atts: list[dict[str, Any]], decided: dict[str, dict[str, Any]]) -> dict[str, bool]:
    """Whether the package an attachment was accepted into still holds it (a person may have removed it there)."""
    out: dict[str, bool] = {}
    with store.connect() as c:
        for a in atts:
            dec = decided.get(a["item_id"])
            if dec and dec["decision"] == "accepted" and dec["target"]:
                row = c.execute("SELECT removed_revision FROM workpackage_items WHERE workpackage_id=? AND item_id=?",
                                (dec["target"], a["item_id"])).fetchone()
                out[a["item_id"]] = row is not None and row["removed_revision"] is None
    return out


# --- a person's decisions --------------------------------------------------------------------------------------------------


def _row(rows: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    for r in rows:
        if r["item_id"] == item_id:
            return r
    raise explained(RoutingError, "no attachment {{item_id}} in the routing package", item_id=repr(item_id))


def _add(target: str, att: dict[str, Any], role: str | None, actor: str) -> None:
    """Adds the attachment to an existing package: the statement package's own way, any other the shared way."""
    from jav import statement_package

    wp = work.get(target)
    if wp["status"] != "open":
        raise explained(RoutingError, "work package {{name}} is hidden", name=repr(wp["name"]))
    if role is not None and wp["source_kind"] not in package_scope.role(role).package_kinds:
        raise explained(RoutingError, "work package {{name}} cannot collect {{role}}", name=repr(wp["name"]),
                        role=package_scope.role(role).title)
    path = Path(att["path"])
    if wp["source_kind"] == statement_package.KIND:
        found = statement_package.survey_for(target, [path])
        statement_package.add(target, paths=[path], statements=[s["id"] for s in found["statements"] if s["chosen"]],
                              pdfs=[p["path"] for p in found["pdfs"] if p["chosen"]], expected_revision=wp["revision"],
                              actor=actor)
    else:
        work.add_to_package(target, [path], expected_revision=wp["revision"], actor=actor)


def _make(new: dict[str, Any], att: dict[str, Any], actor: str) -> str:
    """Makes the proposed new package with the attachment, and gives it its scope."""
    from jav import statement_package

    path = Path(att["path"])
    if new["role"] == statement_package.ROLE:
        found = statement_package.survey([path], party_id=new["party_id"], period_start=new["period_start"],
                                         period_end=new["period_end"])
        made = statement_package.create(name=new["name"], party_id=new["party_id"], period_start=new["period_start"],
                                        period_end=new["period_end"], paths=[path],
                                        statements=[s["id"] for s in found["statements"] if s["chosen"]],
                                        pdfs=[p["path"] for p in found["pdfs"] if p["chosen"]], actor=actor)
        return made["workpackage_id"]
    wp = work.create_from_files([path], name=new["name"], owner=actor)
    package_scope.set_scope(wp["id"], party_id=new["party_id"], period_start=new["period_start"],
                            period_end=new["period_end"], role_name=new["role"], actor=actor)
    return wp["id"]


def _record(wp_id: str, item_id: str, decision: str, target: str | None, made: bool, actor: str) -> None:
    with store.connect() as c:
        store.begin_immediate(c)
        c.execute("INSERT INTO email_routing_decisions(workpackage_id, item_id, decision, target, made, actor, decided_at)"
                  " VALUES (?,?,?,?,?,?,?) ON CONFLICT(workpackage_id, item_id) DO UPDATE SET decision=excluded.decision,"
                  " target=excluded.target, made=excluded.made, actor=excluded.actor, decided_at=excluded.decided_at",
                  (wp_id, item_id, decision, target, int(made), actor, _now()))
        detail = {"item_id": item_id, "target": target, "made": made}
        if decision == "accepted":
            work.record_event(c, wp_id, "routing_accept", actor, detail)
        else:
            work.record_event(c, wp_id, "routing_reject", actor, detail)


def accept(wp_id: str, item_ids: list[str], *, actor: str, target: str | None = None) -> dict[str, Any]:
    """Accepts the proposals of the given attachments (or puts each into `target`, a person's choice): the document is
    added to the package, or the proposed new package is made with it. An attachment with a blocker can only go to a
    package a person chose. Returns the view."""
    rows = view(wp_id)["items"]
    files = {a["item_id"]: a for a in _attachments(sources_of(wp_id))}
    made_now: dict[tuple[str, str, str, str], str] = {}  # one new package per party, month and role in one call
    for item_id in dict.fromkeys(item_ids):
        r = _row(rows, item_id)
        if r["decision"] is not None:
            continue
        if not r["placement"]["routable"]:
            raise explained(RoutingError, "{{file}} is not a document the routing places", file=r["file"])
        att = files[item_id]
        role = r["placement"]["role"]
        if target is not None:
            _add(target, att, role, actor)
            _record(wp_id, item_id, "accepted", target, False, actor)
            continue
        prop = r["proposal"]
        if prop is None:
            raise explained(RoutingError, "{{file}} has no proposal: choose its package", file=r["file"])
        if prop["target"] is not None:
            _add(prop["target"]["id"], att, role, actor)
            _record(wp_id, item_id, "accepted", prop["target"]["id"], False, actor)
            continue
        new = prop["new"]
        key = (new["party_id"], new["period_start"], new["period_end"], new["role"])
        if key in made_now:
            _add(made_now[key], att, role, actor)
            _record(wp_id, item_id, "accepted", made_now[key], False, actor)
        else:
            made_now[key] = _make(new, att, actor)
            _record(wp_id, item_id, "accepted", made_now[key], True, actor)
    return view(wp_id)


def accept_clear(wp_id: str, *, actor: str) -> dict[str, Any]:
    """Accepts every proposal without a blocker that is not decided yet."""
    rows = view(wp_id)["items"]
    return accept(wp_id, [r["item_id"] for r in rows if r["proposal"] and not r["decision"]], actor=actor)


def reject(wp_id: str, item_ids: list[str], *, actor: str) -> dict[str, Any]:
    """The attachments are not routed (decided: they stay only in their email package)."""
    rows = view(wp_id)["items"]
    for item_id in dict.fromkeys(item_ids):
        r = _row(rows, item_id)
        if r["decision"] is None:
            _record(wp_id, item_id, "rejected", None, False, actor)
    return view(wp_id)


def undo(wp_id: str, item_id: str, *, actor: str) -> dict[str, Any]:
    """A decision is taken back; an accepted document stays in its package (a person removes it there if it should go)."""
    with store.connect() as c:
        store.begin_immediate(c)
        if c.execute("DELETE FROM email_routing_decisions WHERE workpackage_id=? AND item_id=?", (wp_id, item_id)).rowcount:
            work.record_event(c, wp_id, "routing_undo", actor, {"item_id": item_id})
    return view(wp_id)


# --- the offer on an email package's page (DECISIONS 170 K3: the email's intent proposes a logic pack, a person starts it)


def offer(wp: dict[str, Any]) -> dict[str, Any]:
    """A mailbox package's part of its page: how many of its documents came as an email's attachment, and the routing
    packages that route it; nothing for a package without attachments."""
    attachments = sum(1 for i in wp.get("items") or [] if i.get("parent_item_id"))
    if not attachments:
        return {}
    with store.connect() as c:
        rows = c.execute("SELECT s.workpackage_id, s.sources, w.name FROM email_routing_scopes s"
                         " JOIN workpackages w ON w.id = s.workpackage_id ORDER BY s.created_at").fetchall()
    routings = [{"id": r["workpackage_id"], "name": r["name"]} for r in rows if wp["id"] in json.loads(r["sources"])]
    return {"routing_offer": {"attachments": attachments, "routings": routings}}


# --- the logic pack ---------------------------------------------------------------------------------------------------------


def _approved(wp_id: str) -> bool:
    """Done when it has something to route and every such attachment is decided."""
    counts = view(wp_id)["counts"]
    return counts["routable"] > 0 and counts["decided"] == counts["routable"]


def _next(wp_id: str) -> dict[str, Any]:
    return _next_of(view(wp_id)["counts"])


def _next_of(counts: dict[str, int]) -> dict[str, Any]:
    if counts["routable"] == 0:
        return {"code": "routing_empty", "label": "Nothing to route", "stage": "process"}
    if counts["decided"] < counts["routable"]:
        return {"code": "routing_decide", "label": "Route the documents", "stage": "review",
                "params": {"n": counts["routable"] - counts["decided"]}}
    return {"code": "routing_done", "label": "Routed", "stage": "result"}


def _list_mark() -> Any:
    with store.connect() as c:
        return c.execute("SELECT COUNT(*), MAX(decided_at) FROM email_routing_decisions").fetchone()[:]


def _page(wp_id: str) -> dict[str, Any]:
    """The package's page (`work_views.workpackage_view`): its readiness (nothing runs), its next step and its own part."""
    current = view(wp_id)
    return {"readiness": {"ready": False, "blockers": [], "counts": {"items": current["counts"]["attachments"]}},
            "next": _next_of(current["counts"]), "routing": current}


def _delete_guard(c: sqlite3.Connection, wp_id: str) -> None:
    c.execute("DELETE FROM email_routing_decisions WHERE workpackage_id=?", (wp_id,))
    c.execute("DELETE FROM email_routing_scopes WHERE workpackage_id=?", (wp_id,))


def _release_refusal() -> Exception:
    return explained(work.NotReady, "a routing package has no result to release: its documents are released in their packages")


LOGIC = logic_packs.LogicPack(
    kind=KIND, module=__name__,
    roles=(logic_packs.InputRole("emails", "linked_package", "the email packages whose attachments it routes"),
           logic_packs.InputRole("targets", "linked_package", "the open packages whose scope fits a document")),
    has_runs=False, add_refusal="a routing package has no documents of its own: it routes its email packages' attachments",
    release_refusal=_release_refusal, delete_guard=_delete_guard, page=_page, approved=_approved, next_step=_next,
    list_next=_next, list_mark=_list_mark, outputs=())


# --- the workflow step -----------------------------------------------------------------------------------------------------


def workflow_start(ctx: workflow_steps.StepStart) -> None:
    """A workflow's routing step: a routing package over the email packages of the steps it waits for."""
    sources = [wp for step, wp in ctx.packages.items() if step in (ctx.step.get("after") or []) and wp]
    if not sources:
        raise explained(RoutingError, "the steps it waits for made no email package")
    made = create(name=ctx.state["name"], sources=sources, actor=ctx.workflow["actor"])
    ctx.made(made["workpackage_id"])


STEP = workflow_steps.StepKind("routing", __name__, (KIND,), start=workflow_start, paid=False, own_engine=False,
                               repeat_from=lambda wp_id: {"kind": "none"},
                               statuses={"routing_decide": "review", "routing_done": "approved",
                                         "routing_empty": "attention"})


__all__ = ["BLOCKERS", "KIND", "LOGIC", "STEP", "RoutingError", "accept", "accept_clear", "create", "offer", "reject",
           "sources_of", "undo", "view"]
