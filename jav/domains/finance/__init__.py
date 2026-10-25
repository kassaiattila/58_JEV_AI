"""The finance domain's registrations (180, plan 170 E7): invoices, statements, the reconciliation, the utility cost.

Plain-language summary: what the shared code does with invoices and bank statements beyond reading them is registered
here, in one call (`register`, from `registrations.load_all`):
- the cross-document checks, in the order they run: a duplicate invoice (126), an own tax number as the supplier's
  (134), a statement booking the same days as another one (139); the two scans that open the same to-dos on the
  stored results; and (185) the saved stage's direction check of an uncertain detailed type (149; `jav/ai/checks.py`);
- the statement package and the reconciliation package as logic packs (`jav/app/logic_packs.py`; 186: their scopes, with
  the reference that keeps a party in use from being deleted, are in the shared scope store, `jav/app/package_scope.py`),
  and (181) as the statements and reconciliation steps of a workflow (`jav/app/workflow_steps.py`);
- (181) the package roles: incoming invoices, outgoing invoices and bank statements, and where an invoice or a
  statement belongs (its role, party and day; `jav/app/package_scope.py`);
- the finance parts of the downloads (`jav/app/outputs/parts.py`): the duplicate mark on a run's documents and its two
  columns, an invoice's direction, the utility cost's sheets, grand total and JSON section in the package's result,
  and the utility cost's own workbook;
- (185) its tables on the interface: a reconciliation's inputs, the utility cost's grid and sources
  (`jav/domains/finance/finance_datasets.py`);
- (185) its addresses of the local service beyond its logic packs' own: the own parties (`jav/domains/finance/api_parties.py`) and the
  bank files, a tabular export's accounts, the utility cost and the duplicate and statement decisions
  (`jav/domains/finance/api_finance.py`), named in `SERVICE`;
- (209, plan G-process-core R2c) its duplicate decisions and statement choices in "My work today" (until then read by
  `jav/app/activity.py` by name).

The check adapters below turn a document under check into the call of the module that does the work; the work itself
stays in the domain's own modules, in this folder (`duplicates.py`, `statement_months.py`, `report_utility.py`), and in
the shared `jav/app/parties.py`. 204: the reconciliation's golden sets in the shared measurement are described in
`jav/domains/finance/goldens.py` (208: until then `jav/reconcile_goldens.py`), named in `GOLDENS`. 208 (plan
G-process-core R2): the domain's modules are the ones in this folder (until then `MODULES` named them); the shared code
imports none of them (`tests/test_dependency_direction.py`).
"""

from __future__ import annotations

from typing import Any

from jav.app import item_kinds
from jav.ai import checks
from jav.core import activity_kinds, type_roles
from jav.app.outputs import parts

# 185 (plan G-full-move T1a): the modules of the domain's addresses of the local service beyond its logic packs' own
# (`LogicPack.service`); `jav.service.api.service_modules` adds them by name
SERVICE = ("jav.domains.finance.api_parties", "jav.domains.finance.api_finance")
# 202 (plan G-core-generalisation M3a): the module of the domain's commands (`register(sub)`); `jav.cli` adds it by name
COMMANDS = ("jav.domains.finance.finance_cli",)
# 204 (plan G-process-core R1h): the modules of the domain's golden sets (the reconciliation's), by name; the shared measurement
# command imports them (`jav.evals.goldens.logic_pack_goldens`), so the reconciliation imports no measurement code
GOLDENS = ("jav.domains.finance.goldens",)

# --- the cross-document checks: they read the store, so the check registry runs them in a worker run only, and a
# measurement's result never depends on what the store holds (175, plan 170 E3: `jav/ai/checks.py`) ---------------------


def duplicate_check(subject: checks.Subject) -> list[str] | checks.Traced:
    """126 (backlog F-duplicate, the owner's decisions of 2026-10-07): an invoice-like document that is the same
    invoice as an earlier one in the store gets a `duplicate:<kind>:<other>` to-do (`jav/domains/finance/duplicates.py`);
    218: with its decision's trace."""
    from jav.domains.finance import duplicates

    if subject.record is None or duplicates.family(subject.doc_type) is None:
        return []
    fields = subject.record.to_datapoints(tuple(duplicates.key_fields()))  # the stored form, as the earlier ones are
    return duplicates.traced(subject.doc_id, subject.doc_type, fields) or []


def own_tax_check(subject: checks.Subject) -> list[str] | checks.Traced:
    """134 (DECISIONS 134): an incoming invoice whose supplier tax number is an own party's, while the buyer's is
    another number or missing, gets a `parties:own_tax_as_supplier` to-do (`jav/app/parties.py`): the numbers are likely
    swapped, or it is an outgoing invoice."""
    if subject.record is None or not type_roles.has(subject.doc_type, "own_tax_check"):
        return []
    from jav.domains.finance import own_parties
    from jav.ai import typepack

    values = subject.record.to_datapoints(typepack.get(subject.doc_type).record_fields)  # the stored form
    return own_parties.traced(subject.doc_type, values) or []  # 218: with its decision's trace


def statement_overlap_check(subject: checks.Subject) -> list[str]:
    """139 (DECISIONS 139): a statement that books the same days of an account as another one in the store, when
    neither replaces the other by the rule and no person has chosen, gets a `statement:overlap:<other>` to-do
    (`jav/domains/finance/statement_months.py`)."""
    if subject.record is None or not subject.doc_id or not type_roles.has(subject.doc_type, "statement"):
        return []
    from jav.ai import typepack
    from jav.domains.finance import statement_months

    values = subject.record.to_datapoints(typepack.get(subject.doc_type).record_fields)  # the stored form
    current = statement_months.current(subject.doc_id, subject.doc_type, values, subject.validation)
    return statement_months.review_reasons(current)


# --- 185 (plan G-full-move T1d): the finance decisions a run's reviewed version is made of (`jav/core/activity_kinds.py`),
# each after the part it follows, as they always nested; until 185 in `jav/app/corrections.py` -----------------------------


def duplicate_rows(run_id: str, items: list[str], c: Any) -> list[Any]:
    """126: the duplicate decisions on pairs that include one of the run's documents."""
    from jav.domains.finance import duplicates

    return [[d["pair_key"], d["doc_id"], d["decision"], d["decided_at"]] for d in duplicates.decisions_for(items, c)]


def reconcile_rows(run_id: str, items: list[str], c: Any) -> list[Any]:
    """129: the reconciliation decisions on pairs one of the run's documents is a side of."""
    from jav.domains.finance import reconcile_store

    return [[d["pair_key"], d["decision"], d["decided_at"]] for d in reconcile_store.decisions_for(items, c)]


def statement_rows(run_id: str, items: list[str], c: Any) -> list[Any]:
    """139: the choices between two statements of the same days that include one of the run's documents."""
    from jav.domains.finance import statement_months

    return [[d["pair_key"], d["keep_doc_id"], d["decided_at"]] for d in statement_months.choices_for(items, c)]


def duplicate_scan(*, write: bool = False) -> dict[str, Any]:
    from jav.domains.finance import duplicates

    return duplicates.scan(write=write)


def own_tax_scan(*, write: bool = False) -> dict[str, Any]:
    from jav.domains.finance import party_views  # 185: the scan is the finance domain's (`parties` keeps the check)

    return party_views.scan_own_tax(write=write)


def direction_check(state: Any) -> None:
    """149 (185: the saved stage): the own parties' direction settles an uncertain detailed type (`jav/domains/finance/own_parties.py`)."""
    from jav.domains.finance import own_parties

    own_parties.confirm_detail_by_direction(state)


CHECKS = (
    checks.Check("duplicate", "cross_document", duplicate_check, reads_store=True),
    checks.Check("own_tax", "cross_document", own_tax_check, reads_store=True),
    checks.Check("statement_overlap", "cross_document", statement_overlap_check, reads_store=True),
    checks.Check("duplicate_scan", "after_save", duplicate_scan, producer="duplicates", opens="duplicate"),
    checks.Check("own_tax_scan", "after_save", own_tax_scan, producer="parties", opens="own_tax"),
    # 185 (plan G-full-move T1f): as before, in every flow (until then the extraction flow's own code)
    checks.Check("detail_direction", "saved", direction_check),
)


# --- 181 (plan 170 L5): the package roles the finance domain adds (`jav/app/package_scope.py`): what a package collects, the
# documents that fit it (by their type and direction, `jav/app/parties.py` `direction`) and the packages that can hold it ---

# the plain processing packages a person adds documents to (not a mailbox's)
DOCUMENT_PACKAGES = ("folder", "manual", "watch", "upload")


def _incoming(doc_type: str | None, direction: str | None) -> bool:
    return type_roles.has(doc_type, "incoming_invoice") and direction == "incoming"


def _outgoing(doc_type: str | None, direction: str | None) -> bool:
    invoice = type_roles.has(doc_type, "incoming_invoice") or type_roles.has(doc_type, "outgoing_invoice")
    return invoice and direction == "outgoing"


def _statement(doc_type: str | None, direction: str | None) -> bool:
    return type_roles.has(doc_type, "statement")


def _day(raw: Any) -> str | None:
    """A stored date as an ISO day (a stored value is ISO; another form is read when it is sure)."""
    from datetime import date

    from jav.core import dates

    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw)[:10]).isoformat()
    except ValueError:
        found = dates.read_date(raw)
        return found.value.isoformat() if found.value and not found.ambiguous else None


def place_document(doc_type: str | None, values: dict[str, Any], cache: dict[str, Any]) -> Any:
    """181: where a document belongs for the email routing (`package_scope.place`): a bank statement by its account's
    own party, on its period's last day; an invoice by its two sides (`own_parties.direction`: incoming to the buyer,
    outgoing from the supplier), on its fulfilment day, else its issue day. None for another kind of document."""
    from jav.app import package_scope, parties
    from jav.domains.finance import own_parties
    from jav.core import cfg
    from jav.domains.finance import statement_package
    from jav.ai.models import account_key

    if "finance:resolver" not in cache:  # the identities as they stand, read once per routing view
        cache["finance:resolver"] = parties.resolver()
    res = cache["finance:resolver"]
    if type_roles.has(doc_type, "statement"):
        key = account_key(values.get("account_iban") or values.get("account_no"))
        party = res.account(key) if key else None
        return package_scope.Placement(statement_package.ROLE, party, _day(values.get("period_end")) or _day(values.get("period_start")),
                                       None, None if party else "unknown_party")
    if not (type_roles.has(doc_type, "incoming_invoice") or type_roles.has(doc_type, "outgoing_invoice")):
        return None
    direction, party = own_parties.direction(res, doc_type, values)
    role = next((r.name for r in _roles() if r.name != statement_package.ROLE and r.fits(doc_type, direction)), None)
    problem = {"internal": "internal", "not_own": "not_own", "unclear": "unclear_direction"}.get(direction)
    fields = cfg.load("reconcile")["invoice_fields"]
    day = _day(values.get(fields["fulfillment_date"])) or _day(values.get(fields["issue_date"]))
    return package_scope.Placement(role, party, day, direction, problem)


def _roles() -> tuple[Any, ...]:
    from jav.app import package_scope
    from jav.domains.finance import statement_package

    return (package_scope.Role("incoming_invoices", __name__, "Incoming invoices", _incoming, DOCUMENT_PACKAGES),
            package_scope.Role("outgoing_invoices", __name__, "Outgoing invoices", _outgoing, DOCUMENT_PACKAGES),
            package_scope.Role(statement_package.ROLE, __name__, "Bank statements", _statement, (statement_package.KIND,)))


def duplicate_pairs(item_id: str, reasons: list[dict[str, Any]]) -> Any:
    """126: the duplicate suspicions and decisions of the document, with the other document side by side."""
    from jav.domains.finance import duplicates

    return duplicates.item_pairs(item_id, reasons)


def statement_replacements(item_id: str, reasons: list[dict[str, Any]]) -> Any:
    """139: the statement that replaced this one, the ones it replaced, and the undecided ones of the same days."""
    from jav.domains.finance import statement_months

    return statement_months.item_view(item_id, reasons)


# 185 (plan G-full-move T1e): the finance parts of a record item's result, in the order the review page always had them
RECORD_PARTS = (item_kinds.RecordPart("duplicates", __name__, duplicate_pairs),
                item_kinds.RecordPart("statements", __name__, statement_replacements))

# 209 (plan G-process-core R2c): the sources of "My work today" that read the domain's tables, right before the
# workflows' (where `jav/app/activity.py` had them; 175, the owner's decision of 2026-10-19)
SOURCES = (
    activity_kinds.Source("duplicate_decision", "SELECT decided_at at, actor, NULL workpackage_id, run_id, decision detail"
                                                " FROM duplicate_decisions WHERE decided_at >= ? AND decided_at < ?", flow_run=False),
    activity_kinds.Source("statement_choice", "SELECT decided_at at, actor, NULL workpackage_id, run_id, NULL detail"
                                              " FROM statement_choices WHERE decided_at >= ? AND decided_at < ?", flow_run=False),
)

DECISIONS = (
    (activity_kinds.DecisionKind("duplicates", duplicate_rows, wraps="result"), "native"),
    (activity_kinds.DecisionKind("reconcile", reconcile_rows, wraps="reviewed"), "duplicates"),
    (activity_kinds.DecisionKind("statements", statement_rows, wraps="checked"), "reconcile"),
)


# the documents table's finance columns after its general ones (126: the duplicate mark; 147: an invoice's direction),
# with the built-in header and the data view's kind and label set
DUPLICATE_COLUMNS = (parts.Column("duplicate", "Duplicate", "enum", "duplicate"), parts.Column("duplicate_of", "Duplicate of"))
DIRECTION_COLUMNS = (parts.Column("direction", "Direction", "enum", "direction"),)


def _build_statement_table(mod: Any, b: Any) -> Any:
    # 136: an account's statement from a tabular export, code only (229: the domain's flow entry; until then the shared
    # flow registry's)
    if b.item is None:
        raise ValueError("A statement table requires the frozen item identity")
    return mod.build_app(run_id=b.app_id, item_id=b.item["item_id"], source_path=b.source_path,
                         read_path=b.read_path or b.source_path, expected_sha256=b.item["sha256"], persister=b.persister)


def _lint_statement_table(mod: Any) -> Any:
    return mod.build_app(run_id="lint-statement-table", item_id="0" * 64, source_path="lint.json",
                         read_path="lint.json", expected_sha256="0" * 64)


def register() -> None:
    """Every registration of the finance domain, in the order the shared code lists them (`registrations.load_all`)."""
    from jav import flows
    from jav.app import datasets, logic_packs, package_scope, partners, scopes, workflow_steps
    from jav.domains.finance import own_parties, party_views  # its two decision points too
    from jav.domains.finance import duplicates, finance_datasets, reconcile_package, report_utility, statement_package

    # 229 (MD1): its bank table flow; importing `duplicates` registers its decision point
    flows.register(flows.FlowSpec("statement_table", "jav.domains.finance.flow_statement_table", _build_statement_table,
                                  _lint_statement_table))

    for check in CHECKS:
        checks.register(check)
    # 231 (B1): the invoices' suppliers and buyers as the partner register's proposals
    partners.register_suggestions(partners.SuggestionSource("invoices", __name__, party_views.partner_suggestions))
    for kind, after in DECISIONS:  # 185: the reviewed version's finance parts
        activity_kinds.register_decision(kind, after=after)
    for source in SOURCES:  # 209: its parts of "My work today"
        activity_kinds.register_source(source, before="workflow")
    for part in RECORD_PARTS:  # 185: the finance parts of a document's result on the review page
        item_kinds.register_record_part(part)
    from jav.domains.finance import reconcile_statement  # 185: its package log events (until then the activity registry's own) and labels
    logic_packs.register(statement_package.LOGIC)  # 186: their scopes' party reference is the shared scope's
    logic_packs.register(reconcile_package.LOGIC)
    workflow_steps.register(statement_package.STEP)  # 181: a workflow's statements and reconciliation steps
    workflow_steps.register(reconcile_package.STEP)
    from jav.domains.finance import capabilities

    # 231 (C2b): the pairing of two lists as a general capability's step (the monthly reconciliation's pack names it, C2d);
    # (C2d) the accounts a case reconciles as a scope part, by default its party's; (C2e) the party its accounts imply
    capabilities.register()
    scopes.register(reconcile_package.ACCOUNTS_PART)
    scopes.imply(scopes.PARTY, reconcile_package.__name__, reconcile_package.party_of_accounts)
    from jav.domains.finance import pairing_proposal
    from jav.runtime import job_kinds

    job_kinds.register(pairing_proposal.JOB)  # 231 (C2c): the worker's AI proposal of a pairing case
    for role in _roles():  # 181: what a package collects, and where an emailed document belongs
        package_scope.register_role(role)
    package_scope.register_reader("finance", place_document)
    parts.register_record_mark(parts.RecordMark("duplicate", __name__, duplicates.mark_records))
    parts.register_document_columns(parts.DocumentColumns("duplicate", __name__, DUPLICATE_COLUMNS, duplicates.column_values))
    parts.register_document_columns(parts.DocumentColumns("direction", __name__, DIRECTION_COLUMNS, own_parties.direction_values))
    parts.register_result_part(parts.ResultPart("utility_cost", __name__, report_utility.result_part, "utility_cost",
                                                 report_utility.build, heads=report_utility.HEADS,
                                                 value_labels=report_utility.RESULT_VALUE_LABELS,
                                                 view="utility", shown=report_utility.has_utility))  # 185: its result view
    parts.register_sample_type("invoice_hu")  # 229 (MD2): a template preview's made-up rows, by default the invoice's
    parts.register_output_labels(parts.OutputLabels("reconcile_statement", __name__, reconcile_statement.sample_heads,
                                                    reconcile_statement.sample_values))  # 185: for a template's preview
    for dataset, after in finance_datasets.DATASETS:  # 185: its tables on the interface
        datasets.register(dataset, after=after, module=__name__)
    parts.register_own_output(parts.OwnOutput("utility_cost", __name__, "utility_cost.xlsx", "utility-cost",
                                              report_utility.output_data, report_utility.has_rows, heads=report_utility.HEADS,
                                              value_labels=report_utility.OUTPUT_VALUE_LABELS))


__all__ = ["CHECKS", "DIRECTION_COLUMNS", "DUPLICATE_COLUMNS", "SOURCES", "duplicate_check", "duplicate_scan", "own_tax_check",
           "own_tax_scan", "register", "statement_overlap_check"]
