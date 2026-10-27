"""Proposal runs: the rules proposed from a condition document, kept for a person to decide (231, stage D, D-c7e).

Plain-language summary: a person asks for the rules of a condition document's file, naming the document version they
cite. A run is queued, and the worker reads the file page by page (never a page its marking keeps out), proposes rules
with the chosen proposer (GPT under the run's budget, or the stand-in, free), checks each in code and, when asked and
the installation uses JEV, has JEV judge each one code found nothing blocking in. Every proposal is kept with what was
answered, the rule it stands for or why none, the code's findings, where each of its numbers stands and JEV's mark. A
person then decides each one: accept it (only when nothing blocks it and they confirm every number the document does
not print or text recognition read), correct it (the corrected rule is checked again the same way), or reject it with
a reason. An accepted or corrected one becomes a draft rule of the registry in the same transaction, its origin naming
the proposal; it is made active as usual, by its own checks and a person. Each decision is in the decision journal, and
one made on a page that shows an older state is refused.

- `start(document_ref, path, catalogue=, product=, proposer=, limits=, verify=, actor=, enqueue=)`: a queued run (the
  command line runs it at once: `process`); `process_job`, `abandon` (the worker's job, named by
  `jav/runtime/app_jobs.py`).
- `runs(document_ref=None)`, `run(run_id)`: the views.
- `accept(id, actor=, expected_state=, confirmed=, ident=)`, `correct(id, rule, ...)`, `reject(id, reason, ...)`.

Layer: application operation over the queue, the call log, the registry and the decision journal.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from jav.app import app_settings, facts, product_rules, product_sets, rule_checks, rule_proposals, rule_support
from jav.app.product_rules import ConditionDocument, Rule
from jav.core import calls, cfg, decisions, identity, store, versions
from jav.core.clock import utc_stamp as _now
from jav.core.user_messages import Said, explained, said, said_back, said_fields
from jav.documents import page_text

__all__ = ["JOB_KIND", "KIND", "ProposalError", "ProposalRefused", "abandon", "accept", "correct", "naming", "process",
           "process_job", "recheck", "reject", "run", "runs", "start"]

JOB_KIND = "rule_propose"
KIND = "rule_proposal"  # the decision kind: a person's accept, correction or rejection of one proposal
STATES = ("queued", "running", "done", "failed")
DECIDED = ("accepted", "corrected", "rejected")
GPT = "gpt"
STAND_IN = "stand_in"
UNCONFIRMED = ("not_found", "ocr")  # where a number stands that a person confirms

decisions.register(decisions.Kind(KIND, ("accept", "correct", "reject"), __name__))

store.register_schema("rule_proposals", """
-- 231 (stage D, D-c7e): a run of rule proposals from a condition document's file
CREATE TABLE IF NOT EXISTS rule_proposal_runs (
    run_id        TEXT PRIMARY KEY,
    document_ref  TEXT NOT NULL,      -- the document version the proposals cite (<id>@<n>)
    path          TEXT NOT NULL,      -- the file read (local)
    file_sha256   TEXT NOT NULL,
    catalogue     TEXT NOT NULL,
    product       TEXT,               -- the product whose cover modules the proposer is told (its active version)
    proposer      TEXT NOT NULL,      -- gpt | stand_in:<product set>
    verify        INTEGER NOT NULL DEFAULT 0,
    state         TEXT NOT NULL,      -- queued, running, done, failed
    limits        TEXT,               -- JSON: provider -> the budget in USD
    scope         TEXT,
    usage         TEXT,               -- JSON: the budget's use
    pages         TEXT,               -- JSON: page -> its text as read (to check a correction again)
    page_count    INTEGER,
    skipped       TEXT,               -- JSON: page -> the marking that kept it out
    text_source   TEXT,
    ocr_pages     TEXT,               -- JSON: the pages read by text recognition
    config_hash   TEXT,
    error         TEXT,
    requested_by  TEXT, requested_by_id TEXT, requested_at TEXT, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS rule_proposals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES rule_proposal_runs(run_id),
    n             INTEGER NOT NULL,   -- its place in the run
    pages         TEXT NOT NULL,      -- JSON: the pages it was proposed from
    record        TEXT NOT NULL,      -- JSON: the record as answered
    rule          TEXT,               -- JSON: the rule it stands for (NULL: none)
    problem       TEXT,               -- JSON: why it is no rule (a sentence)
    findings      TEXT,               -- JSON: the code's findings (sentences, with their code and severity)
    numbers       TEXT,               -- JSON: where each number stands
    support       TEXT,               -- JSON: JEV's mark (NULL: not asked for)
    state         TEXT NOT NULL DEFAULT 'proposed',  -- proposed, accepted, corrected, rejected
    correction    TEXT,               -- JSON: the person's rule
    confirmed     TEXT,               -- JSON: the numbers the person confirmed
    reason        TEXT,               -- a rejection's reason
    rule_ref      TEXT,               -- the draft rule it became (<id>@<n>)
    decided_by    TEXT, decided_by_id TEXT, decided_at TEXT
);
CREATE INDEX IF NOT EXISTS rule_proposals_run ON rule_proposals(run_id, n);
""")


class ProposalError(ValueError):
    """A proposal run or decision that cannot be: an unknown file, proposer or document, a decided proposal."""


class ProposalRefused(ValueError):
    """A proposal (or a correction) that cannot become a draft rule: every problem (`problems`, sentences)."""

    def __init__(self, problems: list[Said]) -> None:
        super().__init__("the proposal cannot become a draft rule: " + "; ".join(problems))
        self.problems = problems


def _run_id() -> str:
    return f"rpr-{secrets.token_hex(5)}"


def _hash() -> str:
    return cfg.config_hash("rule_proposals", f"gpt_{rule_proposals.SITE}", f"callsite:{rule_support.REQUEST_ID}")


def _stand_in_set(proposer: str) -> str | None:
    if proposer == GPT:
        return None
    kind, _, name = proposer.partition(":")
    if kind != STAND_IN or not name:
        raise explained(ProposalError, "no proposer {{proposer}}: gpt, or stand_in:<product set>", proposer=proposer)
    return name


def start(document_ref: str, path: str | Path, *, catalogue: str, actor: identity.Who, product: str | None = None,
          proposer: str = GPT, limits: dict[str, Decimal] | None = None, verify: bool = False,
          enqueue: bool = True) -> dict[str, Any]:
    """A queued run of proposals from the file at `path`, citing `document_ref` (`<id>@<n>`). With `gpt`, the run asks
    GPT (and with `verify`, JEV) within `limits`; `stand_in:<set>` answers from a product set, free."""
    from jav.core import queue

    if versions.split(document_ref)[1] is None:
        raise explained(ProposalError, "a proposal cites an exact document version, not {{document}}", document=document_ref)
    file = Path(path)
    if not file.is_file():
        raise explained(ProposalError, "no file at {{path}}", path=str(path))
    name = _stand_in_set(proposer)
    if name is not None:
        product_sets.load(name)  # an unknown set fails here, not in the worker
    facts.catalogue(catalogue)  # an unknown catalogue fails here, not in the worker
    run_id = _run_id()
    with store.connect() as c:
        store.begin_immediate(c)
        c.execute("INSERT INTO rule_proposal_runs(run_id, document_ref, path, file_sha256, catalogue, product, proposer, verify,"
                  " state, limits, config_hash, requested_by, requested_by_id, requested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, document_ref, str(file), hashlib.sha256(file.read_bytes()).hexdigest(), catalogue, product, proposer,
                   int(verify), "queued", json.dumps({k: str(v) for k, v in (limits or {}).items()}), _hash(),
                   identity.name_of(actor), identity.id_of(actor), _now()))
    if enqueue:
        queue.enqueue(JOB_KIND, run_id=None, payload={"run_id": run_id})
    return run(run_id)


def markers(file_sha256: str | None) -> list[str]:
    """The markings that keep a page from a model (`skip_page_markers`), none for a file the owner allowed whole by its
    fingerprint (`marked_allowed`; 231 U-A, the owner's decision of 2026-10-27: two documents marked internal may be read
    whole)."""
    rules = cfg.load("rule_proposals")
    allowed = {entry["sha256"] for entry in rules.get("marked_allowed", [])}
    return [] if file_sha256 in allowed else list(rules["skip_page_markers"])


def _document(ref: str) -> ConditionDocument | None:
    try:
        return ConditionDocument.model_validate(product_rules.resolve("document", ref)["content"])
    except (versions.VersionNotFound, KeyError):
        return None


def _modules(product: str | None) -> dict[str, str]:
    if not product:
        return {}
    try:
        content = product_rules.resolve("product", product)["content"]
    except versions.VersionNotFound:
        return {}
    return {m["code"]: m["name"] for m in content["modules"]}


def _check_json(check: rule_checks.RuleCheck | None) -> tuple[str | None, str | None]:
    if check is None:
        return None, None
    findings = [{"code": f.code, "severity": f.severity, "text": said_fields(f.text)} for f in check.findings]
    numbers = [asdict(n) for n in check.numbers]
    return json.dumps(findings, ensure_ascii=False), json.dumps(numbers, ensure_ascii=False)


def process_job(job: Any) -> str:
    """The worker's job: the run carried through (`process`); the job always completes, a failure shows on the run."""
    from jav.core import queue

    process(job.payload["run_id"])
    return queue.complete(job.id)


def process(run_id: str) -> dict[str, Any]:
    """The file read, the rules proposed, checked and (when asked) judged; a failure is kept on the run."""
    with store.connect() as c:
        row = c.execute("SELECT * FROM rule_proposal_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    if row["state"] not in ("queued", "running"):
        return run(run_id)
    with store.connect() as c:
        c.execute("UPDATE rule_proposal_runs SET state='running' WHERE run_id=?", (run_id,))
    try:
        pages = page_text.read_pages(row["path"], markers(row["file_sha256"]))
        if pages.sha256 != row["file_sha256"]:
            raise explained(ProposalError, "the file changed since the run was asked: {{path}}", path=row["path"])
        limits = {k: Decimal(v) for k, v in json.loads(row["limits"] or "{}").items()}
        name = _stand_in_set(row["proposer"])
        scope = f"rule-proposal-{run_id}"
        with calls.outside_run(scope, limits) as scope:
            proposer = rule_proposals.gpt_proposer(scope) if name is None else rule_proposals.set_proposer(product_sets.load(name))
            asks_jev = bool(row["verify"]) and app_settings.engine_default() == "jev"
            verifier = (lambda rule, pages: rule_support.support(rule, pages, run_id=scope)) if asks_jev else None
            proposed = rule_proposals.propose(row["document_ref"], pages, row["catalogue"], proposer=proposer,
                                              modules=_modules(row["product"]), document=_document(row["document_ref"]),
                                              verifier=verifier)
        with store.connect() as c:
            store.begin_immediate(c)
            for n, p in enumerate(proposed, 1):
                findings, numbers = _check_json(p.check)
                c.execute("INSERT INTO rule_proposals(run_id, n, pages, record, rule, problem, findings, numbers, support)"
                          " VALUES (?,?,?,?,?,?,?,?,?)",
                          (run_id, n, json.dumps(list(p.pages)), json.dumps(p.record.model_dump(mode="json"), ensure_ascii=False),
                           json.dumps(p.rule.model_dump(mode="json"), ensure_ascii=False) if p.rule else None,
                           json.dumps(said_fields(p.problem), ensure_ascii=False) if p.problem else None, findings, numbers,
                           json.dumps(asdict(p.support), ensure_ascii=False) if p.support else None))
            c.execute("UPDATE rule_proposal_runs SET state='done', scope=?, usage=?, pages=?, page_count=?, skipped=?,"
                      " text_source=?, ocr_pages=?, finished_at=? WHERE run_id=?",
                      (scope, json.dumps(calls.budget_usage(scope), default=str), json.dumps(pages.pages, ensure_ascii=False),
                       pages.page_count, json.dumps(pages.skipped, ensure_ascii=False), pages.source,
                       json.dumps(sorted(pages.ocr_pages)), _now(), run_id))
    except Exception as exc:  # noqa: BLE001 - the run shows why it failed; the worker goes on
        abandon(run_id, f"{type(exc).__name__}: {exc}")
    return run(run_id)


def _stored_pages(row: Any) -> page_text.DocumentPages:
    """U-A3: a run's pages as it read them (kept with the run, never read from the file again)."""
    return page_text.DocumentPages({int(k): v for k, v in json.loads(row["pages"] or "{}").items()}, int(row["page_count"] or 0),
                                   row["text_source"], frozenset(int(n) for n in json.loads(row["ocr_pages"] or "[]")),
                                   {int(k): v for k, v in json.loads(row["skipped"] or "{}").items()}, row["file_sha256"])


def recheck(run_id: str, *, document_ref: str | None = None, jev_budget: Decimal | None = None) -> dict[str, Any]:
    """231 (stage U, U-A3): a finished run's undecided proposals checked again with the code as it is now, from the
    answers it keeps (no model is asked again): each record turned into a rule, its clause found on its page, the code's
    check on the pages the run read. `document_ref` names a newer version of the same document (its clauses read again
    from the same file) the rules cite from now on. With a JEV budget, JEV judges the proposals that code no longer
    blocks and that it has not judged."""
    with store.connect() as c:
        row = c.execute("SELECT * FROM rule_proposal_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    if row["state"] != "done":
        raise explained(ProposalError, "only a finished run is checked again, not one {{state}}", state=row["state"])
    ref = document_ref or row["document_ref"]
    if versions.split(ref)[0] != versions.split(row["document_ref"])[0] or versions.split(ref)[1] is None:
        raise explained(ProposalError, "a run is checked again against a version of its own document, not {{document}}", document=ref)
    pages, document, modules = _stored_pages(row), _document(ref), _modules(row["product"])
    with store.connect() as c:
        rows = c.execute("SELECT * FROM rule_proposals WHERE run_id=? AND state='proposed' ORDER BY n", (run_id,)).fetchall()
    updates = []
    scope = f"rule-proposal-recheck-{run_id}"
    with calls.outside_run(scope, {"jev": jev_budget} if jev_budget else {}) as scope:
        for p in rows:
            record = rule_proposals.ProposedRule.model_validate(json.loads(p["record"]))
            rule, problem = rule_proposals.to_rule(record, row["catalogue"], ref, modules=tuple(modules))
            rule = rule_proposals.on_its_page(rule, document, pages.pages.get(rule.source.page)) if rule is not None else None
            check = rule_checks.check(rule, pages, document_ref=ref, document=document) if rule is not None else None
            support = p["support"]
            if support is None and jev_budget and rule is not None and check is not None and not check.blocking:
                support = json.dumps(asdict(rule_support.support(rule, pages, run_id=scope)), ensure_ascii=False)
            findings, numbers = _check_json(check)
            updates.append((json.dumps(rule.model_dump(mode="json"), ensure_ascii=False) if rule else None,
                            json.dumps(said_fields(problem), ensure_ascii=False) if problem else None, findings, numbers,
                            support, p["id"]))
    with store.connect() as c:
        store.begin_immediate(c)
        c.executemany("UPDATE rule_proposals SET rule=?, problem=?, findings=?, numbers=?, support=? WHERE id=? AND state='proposed'",
                      updates)
        c.execute("UPDATE rule_proposal_runs SET document_ref=? WHERE run_id=?", (ref, run_id))
    return run(run_id)


def abandon(run_id: str, error: str) -> None:
    with store.connect() as c:
        c.execute("UPDATE rule_proposal_runs SET state='failed', error=?, finished_at=? WHERE run_id=?", (error[:500], _now(), run_id))


# --- the views -----------------------------------------------------------------------------------------------------------


def _loads(text: str | None) -> Any:
    return json.loads(text) if text else None


def _readiness(row: Any) -> str:
    """Where a proposal stands for a person: blocked (it cannot be accepted as it is), to confirm (numbers a person
    confirms), ready."""
    if row["rule"] is None or any(f["severity"] == "blocking" for f in _loads(row["findings"]) or []):
        return "blocked"
    if any(n["where"] in UNCONFIRMED for n in _loads(row["numbers"]) or []):
        return "confirm"
    return "ready"


def _proposal_view(c: Any, row: Any) -> dict[str, Any]:
    record = json.loads(row["record"])
    return {"id": row["id"], "run_id": row["run_id"], "n": row["n"], "pages": json.loads(row["pages"]), "record": record,
            "title": record["title"], "kind": record["kind"], "page": record["page"], "clause": record["clause"],
            "rule": _loads(row["rule"]), "problem": _loads(row["problem"]), "findings": _loads(row["findings"]) or [],
            "numbers": _loads(row["numbers"]) or [], "support": _loads(row["support"]), "readiness": _readiness(row),
            "state": row["state"], "correction": _loads(row["correction"]), "confirmed": _loads(row["confirmed"]) or [],
            "reason": row["reason"], "rule_ref": row["rule_ref"], "decided_by": row["decided_by"],
            "decided_at": row["decided_at"], "decision_state": decisions.state(c, KIND, str(row["id"]))}


def _run_view(c: Any, row: Any, *, proposals: bool) -> dict[str, Any]:
    out = {k: row[k] for k in ("run_id", "document_ref", "file_sha256", "catalogue", "product", "proposer", "state",
                               "page_count", "text_source", "error", "requested_by", "requested_at", "finished_at")}
    out |= {"file": Path(row["path"]).name, "verify": bool(row["verify"]), "stand_in": row["proposer"] != GPT,
            "limits": _loads(row["limits"]) or {}, "usage": _loads(row["usage"]),
            "skipped": {int(k): v for k, v in (_loads(row["skipped"]) or {}).items()}, "ocr_pages": _loads(row["ocr_pages"]) or []}
    counts = c.execute("SELECT state, COUNT(*) n FROM rule_proposals WHERE run_id=? GROUP BY state", (row["run_id"],)).fetchall()
    out["counts"] = {r["state"]: r["n"] for r in counts}
    if proposals:
        rows = c.execute("SELECT * FROM rule_proposals WHERE run_id=? ORDER BY n", (row["run_id"],)).fetchall()
        out["proposals"] = [_proposal_view(c, r) for r in rows]
    return out


def runs(document_ref: str | None = None) -> list[dict[str, Any]]:
    """Every run, newest first (of one document version when named), without its proposals."""
    with store.connect() as c:
        rows = c.execute("SELECT * FROM rule_proposal_runs WHERE ? IS NULL OR document_ref=? ORDER BY requested_at DESC, run_id",
                         (document_ref, document_ref)).fetchall()
        return [_run_view(c, r, proposals=False) for r in rows]


def naming(documents: set[str], products: set[str]) -> list[str]:
    """231 (stage U, U0): the runs that cite a version of one of `documents` or name one of `products` (by id)."""
    with store.connect() as c:
        rows = c.execute("SELECT run_id, document_ref, product FROM rule_proposal_runs ORDER BY requested_at, run_id").fetchall()
    return [r["run_id"] for r in rows if versions.split(r["document_ref"])[0] in documents
            or (r["product"] and versions.split(r["product"])[0] in products)]


def run(run_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM rule_proposal_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return _run_view(c, row, proposals=True)


# --- a person's decision -------------------------------------------------------------------------------------------------


def _ident(rule: Rule) -> str:
    """The draft rule's identifier: the document, the clause and the kind (`<doc>.<clause>.<kind>`)."""
    doc = versions.split(rule.source.document)[0]
    clause = rule.source.clause or f"p{rule.source.page or 0}"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", f"{doc}.{clause}.{rule.kind}")[:120]


def _open(c: Any, proposal_id: int, expected_state: int | None) -> tuple[Any, Any]:
    row = c.execute("SELECT * FROM rule_proposals WHERE id=?", (proposal_id,)).fetchone()
    if row is None:
        raise KeyError(proposal_id)
    decisions.check(c, KIND, str(proposal_id), expected_state)
    if row["state"] in DECIDED:
        raise explained(ProposalError, "the proposal is decided already ({{state}})", state=row["state"])
    return row, c.execute("SELECT * FROM rule_proposal_runs WHERE run_id=?", (row["run_id"],)).fetchone()


def _unconfirmed(numbers: list[dict[str, Any]], confirmed: list[str]) -> list[str]:
    return [n["value"] for n in numbers if n["where"] in UNCONFIRMED and n["value"] not in confirmed]


def _draft(c: Any, rule: Rule, *, run_row: Any, proposal_id: int, corrected: bool, confirmed: list[str],
           ident: str | None, actor: identity.Who) -> str:
    origin = {"kind": "proposal", "run": run_row["run_id"], "proposal": proposal_id, "proposer": run_row["proposer"],
              "corrected": corrected, "confirmed": confirmed}
    content = rule.model_dump(mode="json") | {"origin": origin}
    key = ident or _ident(rule)
    return versions.ref(key, product_rules.add_in(c, "rule", key, content, actor=actor))


def accept(proposal_id: int, *, actor: identity.Who, expected_state: int | None, confirmed: list[str] | None = None,
           ident: str | None = None) -> dict[str, Any]:
    """The proposal as a draft rule of the registry, when nothing blocks it and every number the document does not
    print (or text recognition read) is in `confirmed`."""
    confirmed = list(confirmed or [])
    with store.connect() as c:
        store.begin_immediate(c)
        row, run_row = _open(c, proposal_id, expected_state)
        if row["rule"] is None:
            raise ProposalRefused([said("the proposal is no rule: correct it or reject it")])
        blocking = [f for f in json.loads(row["findings"] or "[]") if f["severity"] == "blocking"]
        if blocking:
            raise ProposalRefused([said_back(f["text"]) for f in blocking])
        if missing := _unconfirmed(json.loads(row["numbers"] or "[]"), confirmed):
            raise ProposalRefused([said("confirm the numbers first: {{values}}", values=", ".join(missing))])
        rule = Rule.model_validate(json.loads(row["rule"]))
        ref = _draft(c, rule, run_row=run_row, proposal_id=proposal_id, corrected=False, confirmed=confirmed, ident=ident, actor=actor)
        c.execute("UPDATE rule_proposals SET state='accepted', confirmed=?, rule_ref=?, decided_by=?, decided_by_id=?, decided_at=?"
                  " WHERE id=?", (json.dumps(confirmed, ensure_ascii=False), ref, identity.name_of(actor), identity.id_of(actor),
                                  _now(), proposal_id))
        decisions.record(c, KIND, str(proposal_id), "accept", actor=actor, value={"rule_ref": ref, "confirmed": confirmed})
        return _proposal_view(c, c.execute("SELECT * FROM rule_proposals WHERE id=?", (proposal_id,)).fetchone())


def correct(proposal_id: int, rule: dict[str, Any], *, actor: identity.Who, expected_state: int | None,
            confirmed: list[str] | None = None, ident: str | None = None) -> dict[str, Any]:
    """The person's corrected rule as a draft rule, checked again in code on the pages the run read."""
    confirmed = list(confirmed or [])
    try:
        corrected = Rule.model_validate(rule)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ProposalRefused([said("the corrected rule is no rule: {{where}}: {{reason}}",
                                    where=".".join(str(p) for p in first["loc"]) or "–", reason=first["msg"])]) from None
    with store.connect() as c:
        store.begin_immediate(c)
        row, run_row = _open(c, proposal_id, expected_state)
        pages = page_text.DocumentPages({int(k): v for k, v in json.loads(run_row["pages"] or "{}").items()},
                                        run_row["page_count"] or 0, run_row["text_source"],
                                        frozenset(json.loads(run_row["ocr_pages"] or "[]")),
                                        {int(k): v for k, v in json.loads(run_row["skipped"] or "{}").items()})
        check = rule_checks.check(corrected, pages, document_ref=run_row["document_ref"], document=_document(run_row["document_ref"]))
        if check.blocking:
            raise ProposalRefused([f.text for f in check.findings if f.severity == "blocking"])
        if missing := _unconfirmed([asdict(n) for n in check.numbers], confirmed):
            raise ProposalRefused([said("confirm the numbers first: {{values}}", values=", ".join(missing))])
        ref = _draft(c, corrected, run_row=run_row, proposal_id=proposal_id, corrected=True, confirmed=confirmed, ident=ident, actor=actor)
        c.execute("UPDATE rule_proposals SET state='corrected', correction=?, confirmed=?, rule_ref=?, decided_by=?, decided_by_id=?,"
                  " decided_at=? WHERE id=?", (json.dumps(corrected.model_dump(mode="json"), ensure_ascii=False),
                                               json.dumps(confirmed, ensure_ascii=False), ref, identity.name_of(actor),
                                               identity.id_of(actor), _now(), proposal_id))
        decisions.record(c, KIND, str(proposal_id), "correct", actor=actor, value={"rule_ref": ref, "confirmed": confirmed})
        return _proposal_view(c, c.execute("SELECT * FROM rule_proposals WHERE id=?", (proposal_id,)).fetchone())


def reject(proposal_id: int, reason: str, *, actor: identity.Who, expected_state: int | None) -> dict[str, Any]:
    """The proposal set aside, with the person's reason (a reason is needed)."""
    if not reason.strip():
        raise explained(ProposalError, "a rejection needs a reason")
    with store.connect() as c:
        store.begin_immediate(c)
        _open(c, proposal_id, expected_state)
        c.execute("UPDATE rule_proposals SET state='rejected', reason=?, decided_by=?, decided_by_id=?, decided_at=? WHERE id=?",
                  (reason.strip(), identity.name_of(actor), identity.id_of(actor), _now(), proposal_id))
        decisions.record(c, KIND, str(proposal_id), "reject", actor=actor, note=reason.strip())
        return _proposal_view(c, c.execute("SELECT * FROM rule_proposals WHERE id=?", (proposal_id,)).fetchone())
