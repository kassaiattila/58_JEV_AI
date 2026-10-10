// 132: the labels of the reconciliation package's pages, in the chosen language (English source text; the Hungarian
// is in i18n/hu-native.json). The codes come from the local service (jav/reconcile_package.py, configs/reconcile.json).
import type { ReconcileBlocker, ReconcileLineState, ReconcileRelation, ReconcileSignal } from "../../api";
import { getLocale, t } from "../../i18n";
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

/** 135: the kind of payment the AI read from a line's text (configs/callsites/reconcile_line.json `line_kind`). */
export const KIND: Record<string, string> = tmap({
  utility_or_telecom: "Utility or telecom bill",
  subscription: "Subscription",
  insurance: "Insurance",
  online_order: "Online order",
  retail_purchase: "Retail purchase",
  institution_fee: "Fee to an institution",
  person_transfer: "Transfer to a person",
  own_transfer: "Own transfer or top-up",
  bank_fee: "Bank fee",
  tax_or_duty: "Tax or duty",
  cash: "Cash",
  other: "Other",
});

export const ENGINE: Record<string, string> = { jev: "JEV", gpt: "GPT" };

/** A probability (0–1) as a decimal in the chosen language: 0.87 → "0,87". */
export function probability(p: number | null | undefined): string {
  if (p === null || p === undefined) return "–";
  const text = p.toFixed(2);
  return getLocale() === "hu-HU" ? text.replace(".", ",") : text;
}

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
