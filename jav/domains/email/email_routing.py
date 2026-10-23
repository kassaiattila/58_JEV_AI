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
the routing cannot place by itself is a blocker: not read yet, read but without data (183), no own party, an unclear
direction (or an invoice between two own parties), no date, or a suspicious email. An incoming invoice in a sent email
(a forwarded one) is proposed with a note (183; DECISIONS 183). A document of another kind (a contract, say) is only
listed, by its result's type or, without data points, by its recognised type (183). The routing package is done when
every attachment it can route is decided.

Code only, no AI call; the placement of a document is the domains' (`package_scope.place`).

- `create(name, sources, actor)`: a routing package over email packages.
- `view(wp_id)`: every attachment with its email, its placement, the proposal and the decision; the counts.
- `accept(wp_id, item_ids, actor, target=None)`, `reject(...)`, `undo(...)`: a person's decisions.
- `LOGIC`, `STEP`: the logic pack and the workflow step (registered by the email domain, `jav/domains/email/__init__.py`).

Layer: application operation (it adds documents to packages through `jav/work.py` and the statement package's own
adding).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from jav import logic_packs, package_result, package_scope, source_instances, work, workflow_steps
from jav.core import activity_kinds, decisions, store
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now

KIND = "email_routing"
# the actions this module records in a routing package's log (`jav/core/activity_kinds.py`)
activity_kinds.register_events("package", ("routing_accept", "routing_reject", "routing_undo"), __name__)

# 186 (plan G-full-move T2b): the email packages whose attachments it routes are its scope's further part `emails` (its
# input role's name) in the shared scope store (`jav/package_scope.py`)
EMAILS = "emails"

store.register_schema("email_routing", """
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



def _older_scope(row: dict[str, Any]) -> dict[str, Any]:
    """186: a row of the older own scope table (181-185) as the shared scope keeps it."""
    return {"workpackage_id": row["workpackage_id"], "party_id": None, "period_start": None, "period_end": None,
            "role": None, "parts": {EMAILS: json.loads(row["sources"])}, "revision": 1, "set_by": row["actor"],
            "set_at": row["created_at"]}


# 186: an older store's `email_routing_scopes` is copied into the shared scope store once
store.register_migration("email_routing_scope",
                         lambda conn: package_scope.copy_older(conn, "email_routing_scopes", _older_scope))

# what keeps an attachment from being routed by itself (the interface names each)
BLOCKERS = ("no_result", "no_data", "unknown_party", "unclear_direction", "internal", "not_own", "no_day", "suspicious")
# what a person should know about a proposal that does not keep it from being accepted (183)
NOTES = ("sent_incoming",)


class RoutingError(ValueError):
    """A routing request that cannot be met: no email package, an unknown attachment, a target that cannot take it."""


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
        package_scope.save(c, wp["id"], parts={EMAILS: chosen}, actor=actor)
    return {"workpackage_id": wp["id"], "sources": chosen}


def sources_of(wp_id: str) -> list[str]:
    row = package_scope.stored(wp_id)
    if row is None:
        raise KeyError(wp_id)
    return row["parts"][EMAILS]


# --- what each attachment is -----------------------------------------------------------------------------------------------


def _email_of(item: dict[str, Any]) -> dict[str, Any]:
    """The email an attachment came with: its subject, sender, day and folder (the message as downloaded)."""
    from jav.domains.email import emails

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
    it came from a suspicious email (154: the attachment's to-do); `data`: it has data points.

    183 (the first real trial): an attachment the type recognition read but that left no data points (a document of
    an unknown kind goes the facts way; an invoice whose data could not be read) has no counted result. It is given its
    recognised type (the detailed one if decided), without values, so that it is placed by its kind and not reported
    as not read yet."""
    from jav.core.todo_kinds import SUSPICIOUS_ATTACHMENT

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
                            "suspicious": r["run_id"] in suspicious, "data": True}
    rest = [d for d in doc_ids if d not in out]
    for start in range(0, len(rest), 400):  # below SQLite's parameter limit
        part = rest[start:start + 400]
        for r in c.execute("SELECT doc_id, doc_type, detail_type, last_run_id FROM documents"
                           f" WHERE doc_id IN ({','.join('?' * len(part))})", part):
            out[r["doc_id"]] = {"doc_type": r["detail_type"] or r["doc_type"], "values": {}, "tier": None,
                                "suspicious": r["last_run_id"] in suspicious, "data": False}
    return out


def _month(day: str) -> tuple[str, str]:
    d = date.fromisoformat(day)
    first = d.replace(day=1)
    last = (first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1))
    return first.isoformat(), (last - timedelta(days=1)).isoformat()


def _placement(att: dict[str, Any], result: dict[str, Any] | None, cache: dict[str, Any]) -> dict[str, Any]:
    """Where an attachment belongs (role, party, day), what keeps it from being routed by itself and what a person
    should know about it (`note`); `routable`: it is a document of a role at all (another kind is only listed).

    183 (DECISIONS 183): read without data points, a kind no role takes is only listed; an invoice, a statement or an
    unrecognised kind is a `no_data` blocker (its to-dos in its email package say why). An incoming invoice in a sent
    email is proposed, noted `sent_incoming` (a forwarded invoice; it was a blocker)."""
    nowhere = {"role": None, "party_id": None, "day": None, "note": None}
    if result is None:
        return {"routable": True, **nowhere, "problem": "no_result"}
    found = package_scope.place(result["doc_type"], result["values"], cache)
    if not result["data"]:
        if found is None and result["doc_type"] is not None:
            return {"routable": False, **nowhere, "problem": None}
        return {"routable": True, **nowhere, "role": found.role if found else None,
                "problem": "suspicious" if result["suspicious"] else "no_data"}
    if found is None:
        return {"routable": False, **nowhere, "problem": None}
    problem = found.problem
    if problem is None and result["suspicious"]:
        problem = "suspicious"
    if problem is None and found.day is None:
        problem = "no_day"
    folder = (att.get("email") or {}).get("folder")
    note = "sent_incoming" if folder == "sent" and found.direction == "incoming" else None
    return {"routable": True, "role": found.role, "party_id": found.party_id, "day": found.day, "problem": problem,
            "note": note}


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
    party = party_names.get(placement["party_id"], placement["party_id"])
    return {"target": None, "others": [], "new": {"name": _new_name(party, start, package_scope.role(placement["role"]).title),
                                                   "party": party, "party_id": placement["party_id"],
                                                   "period_start": start, "period_end": end, "role": placement["role"]}}


def _new_name(party: str, start: str, title: str) -> str:
    """A new package's name: its party, its month and its role's title (in the interface's language when it gave one)."""
    return f"{party} · {start[:7]} · {title}"


# 187 (plan G-full-move T2c): a person's decisions on a routing package's attachments, in the shared decision journal
ROUTING_KIND = "email_routing"
decisions.register(decisions.Kind(ROUTING_KIND, ("accept", "reject", "undo"), __name__))


def _key(wp_id: str, item_id: str) -> str:
    return f"{wp_id}#{item_id}"


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
        state = decisions.states(c, ROUTING_KIND, [_key(wp_id, a["item_id"]) for a in atts])  # 187: sent back
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
                     "held": held.get(a["item_id"]), "decision_state": state[_key(wp_id, a["item_id"])]})
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
    """Adds the attachment to an existing package: a logic pack that adds in its own way through its registry entry
    (the statement package, 204: without importing it), any other the shared way."""
    wp = work.get(target)
    if wp["status"] != "open":
        raise explained(RoutingError, "work package {{name}} is hidden", name=repr(wp["name"]))
    if role is not None and wp["source_kind"] not in package_scope.role(role).package_kinds:
        raise explained(RoutingError, "work package {{name}} cannot collect {{role}}", name=repr(wp["name"]),
                        role=package_scope.role(role).title)
    path = Path(att["path"])
    pack = logic_packs.of(wp["source_kind"])
    if pack is not None and pack.take_files is not None:
        pack.take_files(target, [path], expected_revision=wp["revision"], actor=actor)
    else:
        work.add_to_package(target, [path], expected_revision=wp["revision"], actor=actor)


def _make(new: dict[str, Any], att: dict[str, Any], actor: str) -> str:
    """Makes the proposed new package with the attachment, and gives it its scope: a role collected by a logic pack
    that makes its packages in its own way (the statement package) through its registry entry, any other the shared
    way."""
    path = Path(att["path"])
    scope = {"party_id": new["party_id"], "period_start": new["period_start"], "period_end": new["period_end"]}
    for kind in package_scope.role(new["role"]).package_kinds:
        pack = logic_packs.of(kind)
        if pack is not None and pack.create_with_files is not None:
            return pack.create_with_files(name=new["name"], paths=[path], scope=scope, actor=actor)
    wp = work.create_from_files([path], name=new["name"], owner=actor)
    package_scope.set_scope(wp["id"], party_id=new["party_id"], period_start=new["period_start"],
                            period_end=new["period_end"], role_name=new["role"], actor=actor)
    return wp["id"]


def _stale(row: dict[str, Any], expected_states: dict[str, int] | None) -> None:
    """187: the page's state of the attachment's decision must still hold (an attachment it sent none for is not
    compared)."""
    want = (expected_states or {}).get(row["item_id"])
    if want is not None and want != row["decision_state"]:
        raise explained(work.RevisionConflict, "the decision was changed meanwhile; reload the page")


def _record(wp_id: str, item_id: str, decision: str, target: str | None, made: bool, actor: str) -> None:
    """187 (survey 186, bug 2): the attachment must still be undecided inside the writing transaction; before, a second
    acceptance overwrote the first one's decision. The service runs a package's changes one at a time
    (`decisions.one_at_a_time`), so this refuses only a change made outside it."""
    with store.connect() as c:
        store.begin_immediate(c)
        if c.execute("SELECT 1 FROM email_routing_decisions WHERE workpackage_id=? AND item_id=?", (wp_id, item_id)).fetchone():
            raise explained(work.RevisionConflict, "the decision was changed meanwhile; reload the page")
        at = _now()
        c.execute("INSERT INTO email_routing_decisions(workpackage_id, item_id, decision, target, made, actor, decided_at)"
                  " VALUES (?,?,?,?,?,?,?)", (wp_id, item_id, decision, target, int(made), actor, at))
        detail = {"item_id": item_id, "target": target, "made": made}
        if decision == "accepted":
            work.record_event(c, wp_id, "routing_accept", actor, detail)
        else:
            work.record_event(c, wp_id, "routing_reject", actor, detail)
        decisions.record(c, ROUTING_KIND, _key(wp_id, item_id), "accept" if decision == "accepted" else "reject",
                         actor=actor, value={"target": target, "made": made}, workpackage_id=wp_id, at=at)


def accept(wp_id: str, item_ids: list[str], *, actor: str, target: str | None = None,
           titles: dict[str, str] | None = None, expected_states: dict[str, int] | None = None) -> dict[str, Any]:
    """Accepts the proposals of the given attachments (or puts each into `target`, a person's choice): the document is
    added to the package, or the proposed new package is made with it, named with its role's title in `titles` (the
    interface's language) when given. An attachment with a blocker can only go to a package a person chose. Returns the
    view. 187: one change of the package at a time, and a stale state in `expected_states` is refused before anything
    is added or made."""
    with decisions.one_at_a_time(ROUTING_KIND, wp_id):
        _accept(wp_id, item_ids, actor=actor, target=target, titles=titles, expected_states=expected_states)
    return view(wp_id)


def _accept(wp_id: str, item_ids: list[str], *, actor: str, target: str | None, titles: dict[str, str] | None,
            expected_states: dict[str, int] | None) -> None:
    rows = view(wp_id)["items"]
    files = {a["item_id"]: a for a in _attachments(sources_of(wp_id))}
    made_now: dict[tuple[str, str, str, str], str] = {}  # one new package per party, month and role in one call
    for item_id in dict.fromkeys(item_ids):
        _stale(_row(rows, item_id), expected_states)
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
        new = dict(prop["new"])
        if titles and titles.get(new["role"]):
            new["name"] = _new_name(new["party"], new["period_start"], titles[new["role"]])[:200]
        key = (new["party_id"], new["period_start"], new["period_end"], new["role"])
        if key in made_now:
            _add(made_now[key], att, role, actor)
            _record(wp_id, item_id, "accepted", made_now[key], False, actor)
        else:
            made_now[key] = _make(new, att, actor)
            _record(wp_id, item_id, "accepted", made_now[key], True, actor)


def accept_clear(wp_id: str, *, actor: str, titles: dict[str, str] | None = None) -> dict[str, Any]:
    """Accepts every proposal without a blocker that is not decided yet."""
    rows = view(wp_id)["items"]
    return accept(wp_id, [r["item_id"] for r in rows if r["proposal"] and not r["decision"]], actor=actor, titles=titles)


def reject(wp_id: str, item_ids: list[str], *, actor: str, expected_states: dict[str, int] | None = None) -> dict[str, Any]:
    """The attachments are not routed (decided: they stay only in their email package)."""
    with decisions.one_at_a_time(ROUTING_KIND, wp_id):
        rows = view(wp_id)["items"]
        for item_id in dict.fromkeys(item_ids):
            _stale(_row(rows, item_id), expected_states)
        for item_id in dict.fromkeys(item_ids):
            r = _row(rows, item_id)
            if r["decision"] is None:
                _record(wp_id, item_id, "rejected", None, False, actor)
    return view(wp_id)


def undo(wp_id: str, item_id: str, *, actor: str, expected_state: int | None = None) -> dict[str, Any]:
    """A decision is taken back; an accepted document stays in its package (a person removes it there if it should go)."""
    with decisions.one_at_a_time(ROUTING_KIND, wp_id), store.connect() as c:
        store.begin_immediate(c)
        decisions.check(c, ROUTING_KIND, _key(wp_id, item_id), expected_state)
        if c.execute("DELETE FROM email_routing_decisions WHERE workpackage_id=? AND item_id=?", (wp_id, item_id)).rowcount:
            work.record_event(c, wp_id, "routing_undo", actor, {"item_id": item_id})
            decisions.record(c, ROUTING_KIND, _key(wp_id, item_id), "undo", actor=actor, workpackage_id=wp_id)
    return view(wp_id)


# --- the offer on an email package's page (DECISIONS 170 K3: the email's intent proposes a logic pack, a person starts it)


def offer(wp: dict[str, Any]) -> dict[str, Any]:
    """A mailbox package's part of its page: how many of its documents came as an email's attachment, and the routing
    packages that route it; nothing for a package without attachments."""
    attachments = sum(1 for i in wp.get("items") or [] if i.get("parent_item_id"))
    if not attachments:
        return {}
    with store.connect() as c:
        rows = c.execute("SELECT s.workpackage_id, s.parts, w.name FROM workpackage_scopes s"
                         " JOIN workpackages w ON w.id = s.workpackage_id WHERE w.source_kind = ? ORDER BY s.set_at",
                         (KIND,)).fetchall()
    routings = [{"id": r["workpackage_id"], "name": r["name"]} for r in rows
                if wp["id"] in json.loads(r["parts"]).get(EMAILS, [])]
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
    c.execute("DELETE FROM email_routing_decisions WHERE workpackage_id=?", (wp_id,))  # 186: the scope is the shared one's


def _release_refusal() -> Exception:
    return explained(work.NotReady, "a routing package has no result to release: its documents are released in their packages")


LOGIC = logic_packs.LogicPack(
    kind=KIND, module=__name__,
    roles=(logic_packs.InputRole("emails", "linked_package", "the email packages whose attachments it routes"),
           logic_packs.InputRole("targets", "linked_package", "the open packages whose scope fits a document")),
    has_runs=False, add_refusal="a routing package has no documents of its own: it routes its email packages' attachments",
    release_refusal=_release_refusal, delete_guard=_delete_guard, page=_page, approved=_approved, next_step=_next,
    list_next=_next, list_mark=_list_mark, outputs=(), service="jav.domains.email.api_email_routing")


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
