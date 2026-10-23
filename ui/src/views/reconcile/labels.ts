// 132: the labels of the reconciliation package's pages, in the chosen language (English source text; the Hungarian
// is in i18n/hu-native.json). The codes come from the local service (jav/domains/finance/reconcile_package.py, configs/reconcile.json).
import type {
  ReconcileBlocker, ReconcileFlag, ReconcileFx, ReconcileGroupKind, ReconcileInvoiceResult, ReconcileLineResult, ReconcileLineState, ReconcileList,
  ReconcileRelation, ReconcileSignal, ReconcileWarning,
} from "../../api";
import { groupedBlockers } from "../../components/BlockerList";
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

/** 149: the invoice amount converted at the MNB rate, naming the day for a forint bank line (fulfilment or booking). */
export function fxText(fx: ReconcileFx, amount: string): string {
  if (fx.basis === "fulfillment") return t("{{amount}} at the MNB rate of the fulfilment day, {{day}}", { amount, day: fx.rate_day });
  if (fx.basis === "booking") return t("{{amount}} at the MNB rate of the booking day, {{day}}", { amount, day: fx.rate_day });
  return t("{{amount}} at the MNB rate of {{day}}", { amount, day: fx.rate_day });
}

/** Why the code left a line or an invoice out of the pairing (jav/domains/finance/reconcile.py `prepare`; the same labels as the run's
 *  reconciliation view, configs/datasets.json `reconcile_reason`). */
export const EXCLUDED: Record<string, string> = tmap({
  missing_amount: "No amount", non_positive_amount: "Zero or negative amount", invalid_amount: "Unreadable amount",
  unsupported_currency: "Currency not handled", missing_issue_date: "No issue date", outgoing_invoice: "Outgoing invoice",
  duplicate_copy: "Confirmed duplicate copy", duplicate_undecided: "Undecided duplicate", missing_booking_date: "No booking date",
  not_outgoing_payment: "Not an outgoing payment", own_account_transfer: "Transfer between own accounts",
  payment_kind_review: "Fee, interest, repayment or card settlement",
  left_out_by_person: "Left out of this package by a person", // 169
});

/** The invoice's state in the pairing (jav/domains/finance/reconcile.py STATUSES). */
export const INVOICE_STATE: Record<string, string> = tmap({
  confirmed: "Paid",
  credited: "Cancelled by a credit note",
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

/** 135: the kind of payment the AI read from a line's text (configs/callsites/reconcile_line.json `line_kind`; 158: and
 *  the kinds of incoming money, `credit_kind`). */
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
  salary: "Salary or wage",
  customer_payment: "Customer payment",
  income: "Salary or other income",
  interest: "Interest",
  refund: "Refund",
  owner_contribution: "Owner's contribution",
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
    case "combined": return t("with the other named invoices, the line's amount");
    default: return "";
  }
}

/** 153 (review): what a kind of blocker means, for a group of them ("{{n}} documents: …"). */
export function blockerGroupText(code: string, n: number): string {
  switch (code) {
    case "source_not_approved": return t("{{n}} documents come from a run not approved yet", { n });
    case "source_no_run": return t("{{n}} documents were processed on the command line, not in a work package", { n });
    case "decision_not_carried": return t("{{n}} decisions on replaced statements' lines have no same line on the valid statement", { n });
    case "allocation_no_longer_fits": return t("{{n}} pairings no longer fit the amounts of their line or invoice", { n });
    case "allocation_invoice_left_out": return t("{{n}} pairings whose invoice no longer takes part in the pairing", { n });
    case "decision_line_gone": return t("{{n}} decisions whose line is no longer on its statement", { n });
    default: return `${code}: ${n}`;
  }
}

/** 153 (review): the approval's blockers by reason, in the order each reason first occurs: a reason of several
 *  documents is one line with its count, its documents below it (195: the shared blocker list). */
export function blockerItems(blockers: ReconcileBlocker[]) {
  return groupedBlockers(blockers, (b) => b.code, (b) => ({ key: `${b.code}:${b.doc_id}`, content: blockerText(b) }), blockerGroupText);
}

export function blockerText(b: ReconcileBlocker): string {
  const name = b.file ?? b.doc_id.slice(0, 12);
  switch (b.code) {
    case "source_not_approved": return t("Its run is not approved yet: {{name}}", { name });
    case "source_no_run": return t("Processed on the command line, not in a work package: {{name}}", { name });
    case "statement_unverified": return t("The statement's balances do not check out: {{name}}", { name });
    case "decision_not_carried": return t("A decision on a replaced statement's line has no same line on the valid statement: {{name}}", { name });
    case "allocation_no_longer_fits": return t("A pairing no longer fits the amounts of its line or invoice: {{name}}", { name });
    case "allocation_invoice_left_out": return t("A pairing's invoice no longer takes part in the pairing: {{name}}", { name });
    case "decision_line_gone": return t("A decision's line is no longer on its statement: {{name}}", { name });
    default: return `${b.code}: ${name}`;
  }
}

export const STATEMENT_TYPE: Record<string, string> = tmap({ bank_account: "bank account", credit_card: "card" });

/** 142: the kind of a card on the pairing page (jav/domains/finance/reconcile_overview.py `KINDS`). */
export const GROUP_KIND: Record<ReconcileGroupKind, string> = tmap({
  proposed: "Proposal to decide",
  paired: "Paired",
  line_only: "Transfer without an invoice",
  invoice_only: "Invoice without a payment",
  credited: "Cancelled by a credit note",
  marked: "Needs no invoice",
  excluded: "Left out",
}) as Record<ReconcileGroupKind, string>;

/** 142: the lists of the cards, as chips (jav/domains/finance/reconcile_overview.py `LISTS`). */
export const CARD_LIST: Record<ReconcileList | "all", string> = tmap({
  to_decide: "To decide",
  line_without_invoice: "Transfers without an invoice",
  invoice_without_payment: "Invoices without a payment",
  overdue: "Overdue, no payment found",
  late: "Paid late",
  double_payment: "Possible double payment",
  clarify: "To clarify",
  paired: "Paired",
  marked: "Needs no invoice",
  credited: "Cancelled by a credit note",
  excluded: "Left out",
  all: "All",
}) as Record<ReconcileList | "all", string>;

/** 142: what a card's flag says. */
export const FLAG: Record<ReconcileFlag, string> = tmap({
  late: "paid late",
  overdue: "overdue, no payment found",
  double_payment: "possible double payment",
  several_candidates: "several candidates",
  amount_differs: "different amount",
  statement_unverified: "statement balances do not check out",
  rest_left: "an amount is left",
  no_due_date: "no due date on the invoice",
  paid_elsewhere: "paid by a line outside this package",
}) as Record<ReconcileFlag, string>;

/** 142: a pair's booking day against the invoice's due date: every day after it is a delay (DECISIONS 142). */
export function dueText(days: number | null | undefined): string {
  if (days === null || days === undefined) return t("no due date");
  if (days > 0) return t("{{n}} days late", { n: days });
  if (days === 0) return t("on the due date");
  return t("{{n}} days before the due date", { n: -days });
}

/** 145: an invoice's result in the reconciliation statement (jav/domains/finance/reconcile_statement.py `INVOICE_RESULTS`). */
export const INVOICE_RESULT: Record<ReconcileInvoiceResult, string> = tmap({
  paid: "Paid",
  partly_paid: "Partly paid",
  credited: "Settled by a credit note",
  undecided: "Proposal to decide",
  no_payment_found: "No payment in the covered period",
  not_covered: "Statements do not cover it",
}) as Record<ReconcileInvoiceResult, string>;

/** 145: a statement line's result in the reconciliation statement (jav/domains/finance/reconcile_statement.py `LINE_RESULTS`). */
export const LINE_RESULT: Record<ReconcileLineResult, string> = tmap({
  paired: "Paired",
  partly_paired: "Partly paired",
  needs_no_invoice: "Needs no invoice",
  left_out: "Left out",
  open: "Open",
}) as Record<ReconcileLineResult, string>;

/** 145: what the statement warns about without blocking its approval (DECISIONS 132, 137). */
export function warningText(w: ReconcileWarning): string {
  switch (w.code) {
    case "statement_unverified": return t("The statement's balances do not check out: {{name}}", { name: w.file ?? w.doc_id?.slice(0, 12) ?? "" });
    case "month_without_statement": return t("No statement for {{month}}: {{account}}", { month: w.month ?? "", account: w.account ?? "" });
    default: return w.code;
  }
}
