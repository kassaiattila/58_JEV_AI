// 132: the labels of the reconciliation package's pages, in the chosen language (English source text; the Hungarian
// is in i18n/hu-native.json). The codes come from the local service (jav/reconcile_package.py, configs/reconcile.json).
import type { ReconcileBlocker, ReconcileLineState, ReconcileRelation, ReconcileSignal } from "../../api";
import { t } from "../../i18n";
import { tmap } from "../../labels";

export const LINE_STATE: Record<ReconcileLineState, string> = tmap({
  proposed: "Proposed pair",
  amount_only: "Same amount only",
  partly_allocated: "Partly paired",
  open: "No candidate",
  allocated: "Paired",
  marked: "Needs no invoice",
  excluded: "Left out",
}) as Record<ReconcileLineState, string>;

/** Why the code left a line or an invoice out of the pairing (jav/reconcile.py `prepare`; the same labels as the run's
 *  reconciliation view, configs/datasets.json `reconcile_reason`). */
export const EXCLUDED: Record<string, string> = tmap({
  missing_amount: "No amount", non_positive_amount: "Zero or negative amount", invalid_amount: "Unreadable amount",
  unsupported_currency: "Currency not handled", missing_issue_date: "No issue date", outgoing_invoice: "Outgoing invoice",
  duplicate_copy: "Confirmed duplicate copy", duplicate_undecided: "Undecided duplicate", missing_booking_date: "No booking date",
  not_outgoing_payment: "Not an outgoing payment", own_account_transfer: "Transfer between own accounts",
  payment_kind_review: "Fee, interest, repayment or card settlement",
});

/** The invoice's state in the pairing (jav/reconcile.py STATUSES). */
export const INVOICE_STATE: Record<string, string> = tmap({
  confirmed: "Paid",
  proposed: "Proposed pair",
  amount_only: "Same amount only",
  partly_paid: "Partly paid",
  amount_differs: "Related line, different amount",
  rate_missing: "No exchange rate yet",
  no_payment_found: "No payment found",
  partly_covered: "Statements cover part of its period",
  not_covered: "No statement for its period",
  excluded: "Left out",
});

export const SIGNAL: Record<ReconcileSignal, string> = tmap({
  invoice_number: "invoice number",
  reference: "reference number",
  supplier_account: "supplier's account",
  supplier_name: "supplier's name",
  supplier_name_fuzzy: "supplier's name (loose match)",
  payment_channel: "payment method",
  learned_name: "learnt name",
}) as Record<ReconcileSignal, string>;

/** Why a line needs no invoice (configs/reconcile.json `line_marks`). */
export const MARK: Record<string, string> = tmap({
  private: "Private expense",
  fee: "Bank fee or interest",
  own_transfer: "Transfer between own accounts",
  tax: "Tax or contribution",
  cash: "Cash withdrawal",
  salary: "Salary",
  other: "Other (with a note)",
});

export function relationText(relation: ReconcileRelation | null): string {
  switch (relation) {
    case "equal": return t("same amount");
    case "fx_within": return t("converted amount within the card band");
    case "fx_outside": return t("converted amount outside the card band");
    case "no_rate": return t("no exchange rate for the issue date");
    case "different": return t("different amount");
    default: return "";
  }
}

export function blockerText(b: ReconcileBlocker): string {
  const name = b.file ?? b.doc_id.slice(0, 12);
  switch (b.code) {
    case "source_not_approved": return t("Its run is not approved yet: {{name}}", { name });
    case "source_no_run": return t("Processed on the command line, not in a work package: {{name}}", { name });
    case "statement_unverified": return t("The statement's balances do not check out: {{name}}", { name });
    default: return `${b.code}: ${name}`;
  }
}

export const STATEMENT_TYPE: Record<string, string> = tmap({ bank_account: "bank account", credit_card: "card" });
