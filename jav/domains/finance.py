"""The finance domain's registrations (180, plan 170 E7): invoices, statements, the reconciliation, the utility cost.

Plain-language summary: what the shared code does with invoices and bank statements beyond reading them is registered
here, in one call (`register`, from `registrations.load_all`):
- the cross-document checks, in the order they run: a duplicate invoice (126), an own tax number as the supplier's
  (134), a statement booking the same days as another one (139); and the two scans that open the same to-dos on the
  stored results (`jav/checks.py`);
- the statement package and the reconciliation package as logic packs, each with the reference that keeps a party in
  use from being deleted (`jav/logic_packs.py`, `jav/parties.py`), and (181) as the statements and reconciliation steps
  of a workflow (`jav/workflow_steps.py`);
- (181) the package roles: incoming invoices, outgoing invoices and bank statements (`jav/package_scope.py`);
- the finance parts of the downloads (`jav/outputs/parts.py`): the duplicate mark on a run's documents and its two
  columns, an invoice's direction, the utility cost's sheets, grand total and JSON section in the package's result,
  and the utility cost's own workbook.

The check adapters below turn a document under check into the call of the module that does the work; the work itself
stays in `jav/duplicates.py`, `jav/parties.py`, `jav/statement_months.py` and `jav/report_utility.py`.
"""

from __future__ import annotations

from typing import Any

from jav import checks, type_roles
from jav.outputs import parts

# --- the cross-document checks: they read the store, so the check registry runs them in a worker run only, and a
# measurement's result never depends on what the store holds (175, plan 170 E3: `jav/checks.py`) ---------------------


def duplicate_check(subject: checks.Subject) -> list[str]:
    """126 (backlog F-duplicate, the owner's decisions of 2026-10-07): an invoice-like document that is the same
    invoice as an earlier one in the store gets a `duplicate:<kind>:<other>` to-do (`jav/duplicates.py`)."""
    from jav import duplicates

    if subject.record is None or duplicates.family(subject.doc_type) is None:
        return []
    fields = subject.record.to_datapoints(tuple(duplicates.key_fields()))  # the stored form, as the earlier ones are
    return duplicates.review_reasons(subject.doc_id, subject.doc_type, fields)


def own_tax_check(subject: checks.Subject) -> list[str]:
    """134 (DECISIONS 134): an incoming invoice whose supplier tax number is an own party's, while the buyer's is
    another number or missing, gets a `parties:own_tax_as_supplier` to-do (`jav/parties.py`): the numbers are likely
    swapped, or it is an outgoing invoice."""
    if subject.record is None or not type_roles.has(subject.doc_type, "own_tax_check"):
        return []
    from jav import parties, typepack

    values = subject.record.to_datapoints(typepack.get(subject.doc_type).record_fields)  # the stored form
    return parties.review_reasons(subject.doc_type, values)


def statement_overlap_check(subject: checks.Subject) -> list[str]:
    """139 (DECISIONS 139): a statement that books the same days of an account as another one in the store, when
    neither replaces the other by the rule and no person has chosen, gets a `statement:overlap:<other>` to-do
    (`jav/statement_months.py`)."""
    if subject.record is None or not subject.doc_id or not type_roles.has(subject.doc_type, "statement"):
        return []
    from jav import statement_months, typepack

    values = subject.record.to_datapoints(typepack.get(subject.doc_type).record_fields)  # the stored form
    current = statement_months.current(subject.doc_id, subject.doc_type, values, subject.validation)
    return statement_months.review_reasons(current)


def duplicate_scan(*, write: bool = False) -> dict[str, Any]:
    from jav import duplicates

    return duplicates.scan(write=write)


def own_tax_scan(*, write: bool = False) -> dict[str, Any]:
    from jav import parties

    return parties.scan_own_tax(write=write)


CHECKS = (
    checks.Check("duplicate", "cross_document", duplicate_check, reads_store=True),
    checks.Check("own_tax", "cross_document", own_tax_check, reads_store=True),
    checks.Check("statement_overlap", "cross_document", statement_overlap_check, reads_store=True),
    checks.Check("duplicate_scan", "after_save", duplicate_scan, producer="duplicates", opens="duplicate"),
    checks.Check("own_tax_scan", "after_save", own_tax_scan, producer="parties", opens="own_tax"),
)


# --- 181 (plan 170 L5): the package roles the finance domain adds (`jav/package_scope.py`): what a package collects, the
# documents that fit it (by their type and direction, `jav/parties.py` `direction`) and the packages that can hold it ---

# the plain processing packages a person adds documents to (not a mailbox's)
DOCUMENT_PACKAGES = ("folder", "manual", "watch", "upload")


def _incoming(doc_type: str | None, direction: str | None) -> bool:
    return type_roles.has(doc_type, "incoming_invoice") and direction == "incoming"


def _outgoing(doc_type: str | None, direction: str | None) -> bool:
    invoice = type_roles.has(doc_type, "incoming_invoice") or type_roles.has(doc_type, "outgoing_invoice")
    return invoice and direction == "outgoing"


def _statement(doc_type: str | None, direction: str | None) -> bool:
    return type_roles.has(doc_type, "statement")


def _roles() -> tuple[Any, ...]:
    from jav import package_scope, statement_package

    return (package_scope.Role("incoming_invoices", __name__, "Incoming invoices", _incoming, DOCUMENT_PACKAGES),
            package_scope.Role("outgoing_invoices", __name__, "Outgoing invoices", _outgoing, DOCUMENT_PACKAGES),
            package_scope.Role(statement_package.ROLE, __name__, "Bank statements", _statement, (statement_package.KIND,)))


# the documents table's finance columns after its general ones (126: the duplicate mark; 147: an invoice's direction),
# with the built-in header and the data view's kind and label set
DUPLICATE_COLUMNS = (parts.Column("duplicate", "Duplicate", "enum", "duplicate"), parts.Column("duplicate_of", "Duplicate of"))
DIRECTION_COLUMNS = (parts.Column("direction", "Direction", "enum", "direction"),)


def register() -> None:
    """Every registration of the finance domain, in the order the shared code lists them (`registrations.load_all`)."""
    from jav import (duplicates, logic_packs, package_scope, parties, reconcile_package, report_utility, statement_package,
                     workflow_steps)

    for check in CHECKS:
        checks.register(check)
    logic_packs.register(statement_package.LOGIC)
    parties.register_reference("statement_package", count=statement_package.count_party, repoint=statement_package.repoint_party)
    logic_packs.register(reconcile_package.LOGIC)
    parties.register_reference("reconcile_package", count=reconcile_package.count_party, repoint=reconcile_package.repoint_party)
    workflow_steps.register(statement_package.STEP)  # 181: a workflow's statements and reconciliation steps
    workflow_steps.register(reconcile_package.STEP)
    for role in _roles():  # 181: what a package collects
        package_scope.register_role(role)
    parts.register_record_mark(parts.RecordMark("duplicate", __name__, duplicates.mark_records))
    parts.register_document_columns(parts.DocumentColumns("duplicate", __name__, DUPLICATE_COLUMNS, duplicates.column_values))
    parts.register_document_columns(parts.DocumentColumns("direction", __name__, DIRECTION_COLUMNS, parties.direction_values))
    parts.register_result_part(parts.ResultPart("utility_cost", __name__, report_utility.result_part, "utility_cost",
                                                 report_utility.build, heads=report_utility.HEADS,
                                                 value_labels=report_utility.RESULT_VALUE_LABELS))
    parts.register_own_output(parts.OwnOutput("utility_cost", __name__, "utility_cost.xlsx", "utility-cost",
                                              report_utility.output_data, report_utility.has_rows, heads=report_utility.HEADS,
                                              value_labels=report_utility.OUTPUT_VALUE_LABELS))


__all__ = ["CHECKS", "DIRECTION_COLUMNS", "DUPLICATE_COLUMNS", "duplicate_check", "duplicate_scan", "own_tax_check",
           "own_tax_scan", "register", "statement_overlap_check"]
