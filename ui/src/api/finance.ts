// The finance domain: the reconciliation, statement packages, parties, duplicates and the utility cost.
import { enc, request } from "./client";
import type { ItemResult, OwnApproval, OwnVersion, StatementRef, WorkpackageView } from "./types";

/** 146: one kind of bank file and its reader (`configs/bank_files.json` with the reader's own configuration). A reader
 *  nobody described yet is listed from its configuration alone (`described` false). */
export interface BankFile {
  id: string; reader: { profile?: string; type?: string }; read_by: "code" | "ai"; bank: string | null;
  statement: string | null; formats: string[]; suffixes: string[]; kinds: string[]; version: string;
  header: string[]; reads: string[]; not_read: string[]; checks: string[]; notes: string[]; described: boolean;
}
/** 146: which bank files the system reads; the texts are English source strings, `labels` the facts' field labels. */
export interface BankFilesCatalogue {
  version: string; intro: string; read_by: Record<"code" | "ai", string>; checks: Record<string, string>;
  files: BankFile[]; not_read: string[]; labels: Record<string, string>;
}
/** 147: the quick review of a reconciliation package (jav/domains/finance/reconcile_review.py): the lines to decide in groups by what
 *  is known of them, each group accepted at once. */
export type QuickReviewGroupId = "sure_pairs" | "earlier" | "bank_category" | "salary_rule" | "ai_sure" | "ai_review"
  | "expects_invoice" | "rest";
export interface QuickReviewLine {
  id: string; statement_id: string; booking_date: string | null; amount: string | null; currency: string | null;
  direction: string | null; counterparty_name: string | null; memo: string | null; description: string | null;
  file?: string | null; partner?: string | null;
  /** the reason a mark group suggests */
  category?: string;
  /** the invoices a sure pair pays */
  invoices?: { id: string; number: string | null; supplier_name: string | null; partner_name?: string | null; amount: string | null; currency: string | null;
    issue_date: string | null }[];
  ai?: Partial<Record<"jev" | "gpt", { kind: string; probability: number | null }>>;
  earlier_lines?: number;
}
export interface QuickReviewGroup {
  id: QuickReviewGroupId; action: "pair" | "mark" | "none"; lines: QuickReviewLine[]; count: number; totals: Record<string, string>;
  /** 158: how many of the lines a person decides (the incoming money "an invoice is expected" shows is information only). */
  to_decide?: number;
}
export interface QuickReview {
  workpackage_id: string; threshold: number; groups: QuickReviewGroup[];
  excluded: Record<string, { count: number; totals: Record<string, string>; lines: QuickReviewLine[] }>;
  decided: Record<string, number>;
}
export interface UtilitySource {
  item_id: string; file: string; amount: string; page: number | null; field: string; corrected: boolean; open_reasons: number;
  settlement?: boolean;
}
export interface UtilityCell { status: "ok" | "missing" | "partial" | "overlap"; amount: string | null; consumption: string | null; settlement: boolean; sources: UtilitySource[] }
export interface UtilitySeries {
  address: string; utility: string; summary_only: boolean; suppliers: string[]; consumption_unit: string | null; total: string;
  bills: number; cells: Record<string, UtilityCell>;
}
export interface UtilityReport {
  run_id: string; months: string[]; series: UtilitySeries[]; grand_total: string;
  unplaced: { item_id: string; file: string; doc_type: string; reason: string }[];
  duplicates: { item_id: string; file: string; doc_type: string; same_as: string; same_as_file: string; status?: "suspected" | "copy" | "variant" }[];
}
/** 139: one statement of the same account and days as this one: it replaced this one (`replaced_by`), this one replaced
 *  it (`replaces`), or neither, and a person chooses (`conflict`); `how`: by the rule of ranks or by a person. */
export type StatementRelationKind = "replaced_by" | "replaces" | "conflict";
export interface StatementRelation {
  other_doc_id: string; other_file: string | null; relation: StatementRelationKind; how: "rule" | "person" | null;
  other_run_id: string | null; other_item_id: string | null; other_workpackage_id: string | null;
  period: [string | null, string | null]; other_period: [string | null, string | null];
  rank: string; other_rank: string; lines: number; other_lines: number;
  carried: number | null; left_over: number | null; reason_id: number | null;
  kept: string | null; decided_by: string | null; decided_at: string | null;
  /** 187: the choice's state, sent back with a change (`jav/core/decisions.py`). */
  decision_state?: number;
}
export type StatementKeep = "this" | "other" | "rule";
/** 126: the code's kind of a suspected duplicate and a person's decision on the pair. */
export type DuplicateKind = "copy" | "variant" | "undecidable";
export type DuplicateDecision = "copy" | "variant" | "different";
export interface DuplicatePair {
  other_doc_id: string; other_file: string | null; other_run_id: string | null; other_item_id: string | null;
  other_workpackage_id: string | null;
  kind: DuplicateKind; reason_id: number | null; repeat: boolean;
  fields: { field: string; value: unknown; other_value: unknown; differs: boolean; missing: boolean }[];
  decision: DuplicateDecision | null; decided_by: string | null; decided_at: string | null;
  /** 187: the decision's state, sent back with a change (`jav/core/decisions.py`). */
  decision_state?: number;
}
/** 131: the payment method (an invoice payable by cheque, a line through a cheque payment app) and a name learnt from an
 * earlier confirmed pair also tie a line to an invoice. */
export type ReconcileSignal = "invoice_number" | "reference" | "supplier_account" | "supplier_name" | "supplier_name_fuzzy"
  | "payment_channel" | "learned_name";
/** 130: how the amounts of a pair relate; the fx ones are a card line against an invoice of another currency. */
/** 141: combined - one of the invoices a line's memo names, whose amounts together are the line's */
export type ReconcileRelation = "equal" | "different" | "fx_within" | "fx_outside" | "no_rate" | "combined";
/** 130: a card pair's conversion at the MNB rate of the invoice's issue date (deviation: the line's, as a fraction). */
export interface ReconcileFx { rate: string; rate_day: string; source: string; converted: string; deviation: string;
  /** 149: a forint bank line's rate day: the invoice's fulfilment day or the line's booking day (none: a card line). */
  basis?: "fulfillment" | "booking" }

/** An own account or card the store has statements of (the scope is chosen from these). */
export interface ReconcileAccount {
  key: string; account: string | null; statement_types: string[]; currencies: string[]; statements: number;
  first: string | null; last: string | null;
  party?: PartyRef | null; // 133: the own party the account belongs to
  registered?: (AccountDetails & { label: string }) | null; // 138: registered with its party (statements may be 0)
}
export interface ReconcileScope {
  workpackage_id: string; accounts: string[]; period_start: string; period_end: string; revision: number; updated_at: string;
  party_id?: string | null; party?: PartyRef | null; // 133: the package's own party; none: every invoice is its own
}
/** A line's state: proposed / amount_only / partly_allocated / open still need a person; allocated, marked (needs no
 *  invoice) and excluded (no usable amount) do not. */
export type ReconcileLineState = "proposed" | "amount_only" | "partly_allocated" | "open" | "allocated" | "marked" | "excluded";
export const OPEN_LINE_STATES: ReconcileLineState[] = ["proposed", "amount_only", "partly_allocated", "open"];
export interface ReconcileCandidate {
  invoice_id: string; line_id: string; proposed: boolean; amount_only: boolean; signals: ReconcileSignal[];
  amount_relation: ReconcileRelation | null; multiple_candidates: boolean; source_review_required: boolean; fx: ReconcileFx | null;
  /** 134: how strongly it is tied (0-100), the days from the issue date to the booking, booked by the due date */
  strength?: number; days_after_issue?: number | null; by_due?: boolean;
  /** 137: compared on the card purchase's original amount, as the bank printed it */
  original?: { amount: string; currency: string } | null;
  /** 141: a combined payment's invoices, in the order of issue */
  combined?: string[] | null;
  /** 151: a forint bank line paying invoices of another currency together: their sum converted, the line's deviation */
  combined_fx?: { basis: "fulfillment" | "booking"; converted: string; deviation: string } | null;
}
/** An allocation of a line's amount to an invoice; `allocation_id` null: a confirmation from the review page (129). */
export interface ReconcileShare {
  invoice_id: string; line_id: string; line_amount: string; invoice_amount: string; allocation_id: number | null;
  workpackage_id: string | null;
}
export interface ReconcileLineMark { id: number; line_id: string; statement_id: string; category: string; note: string | null; workpackage_id: string | null }
export interface ReconcileLine extends ReconcileLineDetails {  // 144: with the facts beyond the money
  id: string; statement_id: string; account: string; statement_type: string | null; currency: string | null;
  booking_date: string | null; direction: string | null; amount: string | null; counterparty_name: string | null;
  counterparty_account: string | null; description: string | null; memo: string | null;
  /** 137: a card purchase's original amount and currency (the Erste PDF statement) */
  original_amount?: string | null; original_currency?: string | null;
  /** 142: the value day and the balance after the line, as the statement prints them (shown on the card) */
  value_date?: string | null; running_balance?: string | null;
  state: ReconcileLineState; excluded_reason: string | null; allocated: string; rest: string | null;
  mark: ReconcileLineMark | null; allocations: ReconcileShare[]; candidates: ReconcileCandidate[]; rejected: string[];
  statement_verified: boolean; file: string | null;
  other_candidates?: { invoice_id: string; party: string | null }[]; // 133: candidates among another party's invoices
  ai?: Partial<Record<ReconcileAiEngine, ReconcileAiProposal>>; // 134: the AI's stored answers about the line
  /** 135: the counterparty name without its reference numbers (null: no name), and the needs-no-invoice reasons a
   *  person gave the partner's other lines, the most frequent first (none through a payment app) */
  partner?: string | null; earlier_marks?: { category: string; lines: number }[];
  /** 140: the needs-no-invoice reason the line's own category suggests (configs/reconcile.json category_marks) */
  category_mark?: string | null;
  /** 153: it went to an account a stored statement prints but no own party holds: a transfer between own accounts? */
  own_account_unregistered?: boolean;
  /** 145: the approved statement (package and version) that locks the line; null: none */
  locked?: { workpackage_id: string; version: number } | null;
}

export type ReconcileVersionMeta = OwnVersion;
export type ReconcileApproval = OwnApproval;
export type ReconcileInvoiceResult = "paid" | "partly_paid" | "credited" | "undecided" | "no_payment_found" | "not_covered";
export type ReconcileLineResult = "paired" | "partly_paired" | "needs_no_invoice" | "left_out" | "open";
export interface ReconcileStatementInvoice {
  id: string; number: string | null; supplier_name: string | null; supplier_tax_id: string | null; issue_date: string | null;
  fulfillment_date: string | null; due_date: string | null; amount: string | null; currency: string | null;
  payment_method: string | null; file: string | null; result: ReconcileInvoiceResult; engine_state: string | null;
  allocated: string; rest: string | null; paid_on: string | null; days_from_due: number | null; overdue_days: number | null;
  double_payment: boolean; credited_by: string | null; other_party: string | null; source: string | null;
  paid_by: { line_id: string; line_amount: string; invoice_amount: string; booking_date: string | null; account: string | null; in_scope: boolean }[];
}
export interface ReconcileStatementRow {
  id: string; account: string; currency: string | null; booking_date: string | null; value_date: string | null;
  direction: string | null; amount: string | null; counterparty_name: string | null; counterparty_account: string | null;
  memo: string | null; description: string | null; file: string | null; statement_verified: boolean;
  result: ReconcileLineResult; engine_state: string; reason: string | null; note: string | null; allocated: string; rest: string | null;
  pays: { invoice_id: string; number: string | null; supplier_name: string | null; line_amount: string; invoice_amount: string }[];
}
export interface ReconcileWarning { code: string; doc_id?: string; file?: string | null; account?: string; month?: string }
export interface ReconcileStatement {
  format: number; package: { id: string; name: string }; party: string | null; period: [string, string]; accounts: string[];
  invoices: ReconcileStatementInvoice[]; lines: ReconcileStatementRow[]; warnings: ReconcileWarning[];
  counts: { invoices: Record<string, number>; lines: Record<string, number>; open_lines: number };
}
export interface ReconcileStatementCurrent {
  statement: ReconcileStatement; fingerprint: string; blockers: ReconcileBlocker[]; warnings: ReconcileWarning[];
  approval: ReconcileApproval;
  /** 227: what changed since the approved version - its content (a warning) or only its rules (a note); null while
   *  nothing is approved (missing on an older service) */
  since_approval?: { content_changed: boolean; rules_changed: boolean } | null;
}
export interface ReconcileStatementVersion extends ReconcileVersionMeta { statement: ReconcileStatement }
/** 140: a statement the surveyed files hold: its account's last four characters, month, checks and source rank, whose
 *  account it is, and what it would replace or be replaced by; `chosen` is the proposed tick. No line or balance. */
export interface StatementSurveyRow {
  id: string; institution: string; file: string; companion: string | null; title: string; account: string | null;
  currency: string | null; period_start: string | null; period_end: string | null; lines: number; checks_ok: boolean;
  balance_checked: boolean; rank: string; in_period: boolean; in_store: boolean;
  owner: "package" | "none" | "other"; owner_party: { id: string; name: string } | null;
  replaces: StatementRef[]; replaced_by: StatementRef | null; conflicts: StatementRef[]; chosen: boolean;
  in_package?: boolean; // 160-C S2: the package's own survey: the package already holds it
}
/** 140: a PDF of the surveyed files that no export uses: processed with type recognition and AI extraction. */
export interface StatementSurveyPdf {
  path: string; file: string; sha256: string; in_store: boolean; statement: StatementRef | null; chosen: boolean;
  in_package?: boolean; // 160-C S2
}
export interface StatementPackageSurvey {
  party: { id: string; name: string }; period_start: string; period_end: string;
  statements: StatementSurveyRow[]; pdfs: StatementSurveyPdf[]; skipped: { file: string; reason: string }[];
}
export type StatementItemState = "valid" | "replaced" | "conflict" | "pending";
/** 140: a statement package item's statement: valid, replaced, in a conflict a person decides, or pending. */
export interface StatementPackageItem {
  item_id: string; kind: string; file: string; state: StatementItemState; account?: string | null; currency?: string | null;
  period_start?: string | null; period_end?: string | null; rank?: string; work_run?: string | null;
  replaced_by?: string | null; replaces?: string[]; conflicts?: string[];
}
export interface StatementPackageView {
  scope: { workpackage_id: string; party_id: string; party: { id: string; name: string }; period_start: string; period_end: string; revision: number };
  statements: StatementPackageItem[];
}
export interface StatementPackageSources { paths: string[]; party_id: string; period_start: string; period_end: string }
/** 134: JEV's or GPT's raw answer about a statement line (jav/domains/finance/reconcile_ai.py); a person decides. */
export type ReconcileAiEngine = "jev" | "gpt";
export interface ReconcileAiProposal {
  pays: string | null; pays_probability: number | null; options: string[]; kind: string | null; kind_probability: number | null;
  suggested_mark: string | null; expects_invoice: boolean | null; measured: boolean; error: string | null; created_at: string;
  /** 136: the partner's line that was asked, when this line took the kind of payment over from it (no call) */
  asked_line_id?: string | null;
}
export interface ReconcileInvoice {
  id: string; doc_type: string; number: string | null; supplier_name: string | null; amount: string | null; currency: string | null;
  /** 148: an own party's outgoing invoice, and the partner it is shown by (the buyer of an outgoing invoice) */
  outgoing?: boolean; partner_name?: string | null;
  issue_date: string | null; due_date: string | null; payment_method: string | null; file: string | null; state: string | null;
  allocated: string; rest: string | null; allocations: ReconcileShare[]; candidates: ReconcileCandidate[];
  source: "approved" | "not_approved" | "no_run";
  party?: (PartyRef & { how: PartyHow }) | null; // 133: the buyer's own party; none: no party claims it
  own?: boolean; // 133: the package's party's or no party's (listed by default); false: another party's
  credited_by?: { id: string; number: string | null } | null; // 141: the credit note that cancels it
  /** 142: every fact the card shows, and the last day its statements cover it without a gap from its issue date */
  supplier_tax_id?: string | null; payment_account?: string | null; references?: string[]; buyer_name?: string | null;
  fulfillment_date?: string | null; net_total?: string | null; vat_total?: string | null; duplicate?: string | null;
  checked_until?: string | null;
}
/** 142 (jav/domains/finance/reconcile_overview.py): the related lines and invoices as groups, with their pairs, kind, flags and lists. */
export type ReconcileGroupKind = "proposed" | "paired" | "line_only" | "invoice_only" | "credited" | "marked" | "excluded";
export type ReconcileList = "to_decide" | "line_without_invoice" | "invoice_without_payment" | "overdue" | "late" | "double_payment"
  | "clarify" | "paired" | "marked" | "credited" | "excluded";
export type ReconcileFlag = "late" | "overdue" | "double_payment" | "several_candidates" | "amount_differs" | "statement_unverified"
  | "rest_left" | "no_due_date" | "paid_elsewhere";
export interface ReconcileGroupPair {
  line_id: string; invoice_id: string; state: "allocated" | "proposed" | "repeat";
  /** the days from the invoice's due date to the line's booking day (positive: late); null without a due date */
  days_from_due: number | null; several?: boolean; relation?: ReconcileRelation | null;
  line_amount?: string; invoice_amount?: string; allocation_id?: number | null;
}
export interface ReconcileGroup {
  id: string; kind: ReconcileGroupKind; date: string; lines: string[]; invoices: string[]; pairs: ReconcileGroupPair[];
  flags: ReconcileFlag[]; lists: ReconcileList[];
}
export interface ReconcileInvoiceFacts {
  paid_on: string | null; days_from_due: number | null; overdue_days: number | null; checked_until: string | null;
  double_payment: { line_ids: string[]; paid_by: string[] } | null;
}
export interface ReconcileOverview {
  groups: ReconcileGroup[]; invoices: Record<string, ReconcileInvoiceFacts>; counts: Record<ReconcileList | "all", number>;
}
/** Where a document's image opens: the package, run and item of its work run (none for a command-line evaluation). */
export interface ReconcileOpen { workpackage_id: string; run_id: string; item_id: string; pages: number | null }
export interface ReconcileCoverage { account: string; month: string; statements: number; verified: number }
export interface ReconcileBlocker { code: string; doc_id: string; file: string | null; kind: "statement" | "invoice" }
export interface ReconcileCounts {
  lines: Record<string, number>; invoices: Record<string, number>; open_lines: number; other_invoices?: number;
  /** 169: the inputs by kind (the item list's tally) */
  statements?: number; own_invoices?: number; left_out?: number;
}
/** 169: a statement of the scope as one of the package's inputs. */
export interface ReconcileScopeStatement {
  id: string; file: string | null; account: string | null; account_key: string; statement_type: string | null;
  currency: string | null; period_start: string | null; period_end: string | null; verified: boolean; source: string;
  lines: number; open_lines: number; decided: number;
}
/** 169: a document left out of the package, with who left it out, when and why. */
export interface ReconcileLeftOutRow {
  id: string; kind: "statement" | "invoice"; file: string | null; reason: string; actor: string; left_out_at: string;
  source: string | null; number?: string | null; partner_name?: string | null; account?: string | null;
}
/** 169: a package a file for the reconciliation can be added to (it is processed there). */
export interface ReconcileTarget {
  id: string; name: string; source_kind: string; items: number; inputs: number; updated_at: string | null;
  party?: { id: string; name: string }; period_start?: string; period_end?: string;
}
export interface ReconcileTargets { documents: ReconcileTarget[]; statements: ReconcileTarget[] }
/** 139: a decision made on a line of a replaced statement that has no same line on the statement replacing it. */
export interface ReconcileLeftOver {
  kind: "allocation" | "mark" | "decision"; ref: string; line_id: string; statement_id: string; replaced_by: string;
  invoice_id: string | null; category: string | null; decision: string | null; workpackage_id: string | null;
  currency: string | null; booking_date: string | null; amount: string | null; direction: string | null;
  counterparty_name: string | null; file: string | null; replaced_by_file: string | null; invoice_file: string | null;
}
/** 153 (review A3): an allocation that no longer fits its line or invoice (an amount changed since it was made). */
/** 153: a pairing that no longer fits the amounts; 160 (review M-1): also one whose invoice left the pairing, and a
 *  pairing or a mark whose line is no longer on its statement (`reason`). */
export interface ReconcileUnfit {
  kind: "allocation" | "mark"; ref: string; reason: "amounts" | "invoice_left_out" | "line_gone"; line_id: string;
  invoice_id: string | null; invoice_reason: string | null; category: string | null; statement_id: string | null;
  workpackage_id: string | null; line_amount: string | null; invoice_amount: string | null; line_total: string | null;
  invoice_total: string | null; currency: string | null; booking_date: string | null; direction: string | null;
  counterparty_name: string | null; invoice_file: string | null; file: string | null;
}
export interface ReconcileWorkspace {
  workpackage_id: string; scope: ReconcileScope; lines: ReconcileLine[]; invoices: ReconcileInvoice[];
  /** 187: the state of the package's decisions in the decision journal (`jav/core/decisions.py`), sent back with a change. */
  journal_state?: number;
  left_over?: ReconcileLeftOver[];
  unfit?: ReconcileUnfit[];
  /** 145: what warns without blocking the approval (a statement whose balances do not check out), and the approval */
  warnings?: ReconcileBlocker[]; approval?: ReconcileApproval;
  coverage: ReconcileCoverage[]; blockers: ReconcileBlocker[]; line_marks: string[]; open: Record<string, ReconcileOpen>;
  statements?: ReconcileScopeStatement[]; left_out?: ReconcileLeftOutRow[]; // 169: the package's inputs
  counts: ReconcileCounts; learned_names: unknown; fx_tolerance: unknown; engine_version: string; config_hash: string;
  overview?: ReconcileOverview; // 142: the cards of the pairing page
  decision_state?: unknown; // what the decisions read (145: the result reloads when it changes)
}
/** 132: where a line stands on its statement page (box: 0–1 fractions of the page, x0 y0 x1 y1). */
/** 144: a statement line as the statement prints it (the documents' statement pane, jav/domains/finance/reconcile_package.py `locate`). */
export type ReconcileStatementLine = {
  id?: string; booking_date: string | null; value_date?: string | null; direction: string | null; amount: string | null;
  original_amount?: string | null; original_currency?: string | null; counterparty_name: string | null;
  counterparty_account: string | null; memo: string | null; description: string | null; running_balance?: string | null;
} & ReconcileLineDetails;
/** 144: a statement line's facts beyond the money, as a code reader keeps them (only the ones its statement prints; a
 *  card number masked to its first six and last four digits). */
export interface ReconcileLineDetails {
  bank_reference?: string; order_id?: string; end_to_end_id?: string; card_number?: string; purchase_date?: string;
  transaction_time?: string; terminal?: string; authorisation_code?: string; exchange_rate?: string; fee?: string;
}
/** 144: the statement of a line as read: its heading facts and every line in its order. */
export interface ReconcileStatementView {
  file: string | null; institution: string | null; account: string; currency: string | null; period_start: string | null;
  period_end: string | null; opening_balance: string | null; closing_balance: string | null; verified: boolean;
  lines: (ReconcileStatementLine & { id: string })[];
}
/** 144: the bank's PDF behind a statement read by code — found, missing (moved or changed since the reading), or none
 *  (a table or XML export). */
export interface ReconcileOriginal { file: string | null; state: "found" | "missing" | "export" }
export interface ReconcileLocation {
  line_id: string; statement_id: string; open: ReconcileOpen | null;
  /** 144: the page image to show: the statement's own document, the bank's PDF behind a statement read by code, none */
  image: "item" | "original" | null; pages: number | null;
  page: number | null; box: [number, number, number, number] | null;
  original: ReconcileOriginal | null; statement: ReconcileStatementView;
}
export interface ReconcileAllocationPair { invoice_doc_id: string; line_id: string; line_amount?: string; invoice_amount?: string }
/** 143 (jav/domains/finance/reconcile_package.py `matches`): how an invoice fits a line — proposed or listed by the engine for it, its
 *  number or reference in the line's text, tied by a signal in its payment window, or of the same amount there. */
export type ReconcileFit = "proposed" | "candidate" | "named" | "tied" | "same_amount";
/** 143: one invoice compared with the selected line in code (jav/domains/finance/reconcile.py `compare`), on what is left of both. */
export interface ReconcileMatch {
  invoice_id: string; fit: ReconcileFit | null; signals: ReconcileSignal[]; amount_relation: ReconcileRelation | null;
  fx: ReconcileFx | null;
  /** the invoice's amount less the line's, in the invoice's currency (null: the currencies do not meet) */
  difference: { amount: string; currency: string } | null;
  /** the line went to another account than the one the invoice names */
  account_differs: boolean; in_window: boolean; strength: number; by_due: boolean; days_after_issue: number | null;
  /** the days from the invoice's due date to the line's booking day (positive: late) */
  days_from_due: number | null;
}
/** 143: every invoice of the page against one line: the engine's proposals first, the other fitting ones by strength,
 *  then the rest by the nearest amount. */
export interface ReconcileMatches { line_id: string; matches: ReconcileMatch[] }

/** How an invoice was tied to its party: its buyer's tax number, a known name variant, or a name holding one variant. */
export type PartyHow = "tax" | "name" | "similar" | "ambiguous" | null;
export interface PartyRef { id: string; name: string }
export type PartyIdentityKind = "tax" | "name" | "account";
/** A tax number, a buyer name variant or an account, with how many invoices (statements for an account) carry it. */
export interface PartyIdentity { kind: PartyIdentityKind; key: string; label: string; invoices: number }
export interface PartyAccount {
  key: string; label: string; statements: number; first: string | null; last: string | null; statement_types: string[]; currencies: string[];
  registered?: AccountDetails | null; // 138: the details a person registered (kind, bank, currencies, the days it was open)
}
/** 138: an own account or card as a person registered it; it is known even before any statement of it. */
export type AccountKind = "account" | "card";
export interface AccountDetails {
  kind: AccountKind; bank: string | null; currencies: string[]; valid_from: string | null; valid_to: string | null;
  actor?: string; updated_at?: string;
}
export interface AccountDetailsInput {
  kind: AccountKind; currencies: string[]; bank: string | null; valid_from: string | null; valid_to: string | null;
}
/** 138: a month of an account: missing / partial / unverified (balances do not check out) / unapproved / ok, or none
 *  (not expected); overlap: two statements book the same days; break: the opening balance does not continue the last. */
export type MonthState = "ok" | "unapproved" | "unverified" | "partial" | "missing" | "none";
export interface MonthCell {
  month: string; state: MonthState; statements: number; flags: ("overlap" | "break")[];
  replaced?: string[]; // 139: the statements of the month another one replaced (left out of the reconciliation)
}
export interface MonthColumn {
  key: string; currency: string; label: string; kind: AccountKind; bank: string | null; registered: boolean;
  opened: string | null; closed: string | null; statements: number; months: MonthCell[];
}
export interface MonthInvoices { month: string; total: number; approved: number; not_approved: number; no_run: number }
export interface PartyMonths {
  party: PartyRef; start: string; end: string; months: string[]; today: string; columns: MonthColumn[]; invoices: MonthInvoices[];
  summary: Record<Exclude<MonthState, "none"> | "overlap" | "break", number>;
}
export interface OwnParty {
  id: string; name: string; invoices: number; first: string | null; last: string | null; statements_first: string | null;
  statements_last: string | null; accounts: PartyAccount[]; identities: PartyIdentity[]; updated_at: string;
}
/** A new party (`party_id` null) or what an existing one gains, as the data proposes it now. */
export interface PartySuggestion { id: string; party_id: string | null; name: string; invoices: number; identities: PartyIdentity[] }
export interface PartiesOverview {
  parties: OwnParty[]; suggestions: PartySuggestion[]; unassigned: PartyIdentity[]; dismissed: PartyIdentity[]; invoices: number;
  unclaimed_invoices: number; ambiguous_invoices: number; buyer_is_supplier: number; no_buyer: number; config_hash: string;
}
const identityBody = (i: PartyIdentity) => ({ kind: i.kind, key: i.key, label: i.label });

/** 187: each reconciliation package's journal state (`journal_state`) as this page last read it. Every decision of the
 *  package sends it back, so the service refuses a decision made on a page that is stale by now (409; the shared
 *  decision handler, `jav/core/decisions.py`). Another browser tab keeps its own. */
const reconcileSeen = new Map<string, number>();

function seen<T>(wpId: string, answer: Promise<T>): Promise<T> {
  return answer.then((v) => {
    const got = v as { journal_state?: unknown; workspace?: { journal_state?: unknown } } | null;
    const state = typeof got?.journal_state === "number" ? got.journal_state : got?.workspace?.journal_state;
    if (typeof state === "number") reconcileSeen.set(wpId, state);
    return v;
  });
}

function withState(wpId: string, body: Record<string, unknown>): Record<string, unknown> {
  const state = reconcileSeen.get(wpId);
  return state === undefined ? body : { ...body, expected_state: state };
}


export const financeApi = {
  bankFiles: () => request<BankFilesCatalogue>("GET", "/bank-files"),
  /** 146: the new work wizard's templates and the workflows (the work packages of one job, chained). */
  decideDuplicate: (runId: string, itemId: string, otherDocId: string, decision: DuplicateDecision, expectedState?: number) =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/duplicates/${enc(otherDocId)}/decision`,
      { decision, ...(expectedState !== undefined ? { expected_state: expectedState } : {}) }),
  /** 139: which of two statements of the same days stays valid (this one, the other one, or the rule of ranks). */
  chooseStatement: (runId: string, itemId: string, otherDocId: string, keep: StatementKeep, expectedState?: number) =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/statements/${enc(otherDocId)}/choice`,
      { keep, ...(expectedState !== undefined ? { expected_state: expectedState } : {}) }),
  // 131–132: the reconciliation package; every decision returns the recomputed workspace
  reconcileAccounts: () => request<{ accounts: ReconcileAccount[] }>("GET", "/reconcile/accounts"),
  /** 136: the accounts of a bank's tabular statement export (no lines or balances); a package of the chosen ones. */
  // 140: the statement package: a survey of the files for a party and a period, then the package of the ticked ones
  statementPackageSurvey: (body: StatementPackageSources) => request<StatementPackageSurvey>("POST", "/statement-packages/survey", body),
  createStatementPackage: (body: StatementPackageSources & { name: string; statements: string[]; pdfs: string[] }) =>
    request<WorkpackageView>("POST", "/statement-packages", body),
  createReconcilePackage: (body: { name: string; accounts: string[]; period_start: string; period_end: string; party_id?: string | null }) =>
    request<WorkpackageView>("POST", "/reconcile/packages", body),
  reconcileWorkspace: (wpId: string) => seen(wpId, request<ReconcileWorkspace>("GET", `/workpackages/${enc(wpId)}/reconcile`)),
  setReconcileScope: (wpId: string, body: { accounts: string[]; period_start: string; period_end: string; expected_revision: number; party_id?: string | null }) =>
    seen(wpId, request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/scope`, body)),
  reconcileRefresh: (wpId: string) => seen(wpId, request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/refresh`, {})),
  // 187: every decision of the package sends back its journal state as this page last read it (`withState`)
  reconcileAllocate: (wpId: string, pairs: ReconcileAllocationPair[], note?: string) =>
    seen(wpId, request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/allocate`,
      withState(wpId, { pairs, ...(note ? { note } : {}) }))),
  reconcileAcceptProposed: (wpId: string) =>
    seen(wpId, request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/accept-proposed`, withState(wpId, {}))),
  reconcileQuickReview: (wpId: string) => request<QuickReview>("GET", `/workpackages/${enc(wpId)}/reconcile/quick-review`),
  reconcileQuickAccept: (wpId: string, group: QuickReviewGroupId, lineIds: string[]) =>
    seen(wpId, request<{ accepted: number; review: QuickReview; workspace: ReconcileWorkspace }>("POST",
      `/workpackages/${enc(wpId)}/reconcile/quick-review/accept`, withState(wpId, { group, line_ids: lineIds }))),
  reconcileReject: (wpId: string, invoiceDocId: string, lineId: string, note: string) =>
    seen(wpId, request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/reject`,
      withState(wpId, { invoice_doc_id: invoiceDocId, line_id: lineId, note }))),
  reconcileMark: (wpId: string, lineIds: string[], category: string, note?: string) =>
    seen(wpId, request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/mark`,
      withState(wpId, { line_ids: lineIds, category, ...(note ? { note } : {}) }))),
  reconcileUnmark: (wpId: string, lineIds: string[]) =>
    seen(wpId, request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/unmark`, withState(wpId, { line_ids: lineIds }))),
  reconcileRevoke: (wpId: string, kind: "allocation" | "mark" | "decision", ref: string, note?: string) =>
    seen(wpId, request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/revoke`,
      withState(wpId, { kind, ref, ...(note ? { note } : {}) }))),
  // 169: the package's inputs - leaving documents out of this package only, restoring them, where files are added
  reconcileLeaveOut: (wpId: string, docIds: string[], reason: string) =>
    seen(wpId, request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/leave-out`,
      withState(wpId, { doc_ids: docIds, reason }))),
  reconcileRestoreLeftOut: (wpId: string, docIds: string[]) =>
    seen(wpId, request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/restore-left-out`,
      withState(wpId, { doc_ids: docIds }))),
  reconcileTargets: (wpId: string) => request<ReconcileTargets>("GET", `/workpackages/${enc(wpId)}/reconcile/targets`),
  reconcileLocate: (wpId: string, lineId: string) =>
    request<ReconcileLocation>("GET", `/workpackages/${enc(wpId)}/reconcile/locate?line_id=${enc(lineId)}`),
  reconcileMatches: (wpId: string, lineId: string) =>
    request<ReconcileMatches>("GET", `/workpackages/${enc(wpId)}/reconcile/matches?line_id=${enc(lineId)}`),
  // 145: the result - the statement, its approval as a version that locks its lines, reopening, accepted sources
  reconcileStatement: (wpId: string) =>
    seen(wpId, request<ReconcileStatementCurrent>("GET", `/workpackages/${enc(wpId)}/reconcile/statement`)),
  reconcileStatementVersion: (wpId: string, version: number) =>
    request<ReconcileStatementVersion>("GET", `/workpackages/${enc(wpId)}/reconcile/statement?version=${version}`),
  reconcileAcceptSources: (wpId: string, docIds: string[]) =>
    seen(wpId, request<ReconcileStatementCurrent>("POST", `/workpackages/${enc(wpId)}/reconcile/accept-sources`,
      withState(wpId, { doc_ids: docIds }))),
  reconcileApprove: (wpId: string, fingerprint: string) =>
    request<ReconcileStatementCurrent>("POST", `/workpackages/${enc(wpId)}/reconcile/approve`, { fingerprint }),
  reconcileReopen: (wpId: string, note: string) =>
    request<ReconcileStatementCurrent>("POST", `/workpackages/${enc(wpId)}/reconcile/reopen`, { note }),
  reconcileStatementXlsxUrl: (wpId: string, version?: number) =>
    `/api/workpackages/${enc(wpId)}/reconcile/statement.xlsx${version ? `?version=${version}` : ""}`,
  // 133: the own parties; every change answers with the whole overview
  parties: () => request<PartiesOverview>("GET", "/parties"),
  acceptPartySuggestions: (ids: string[], names: Record<string, string> = {}) =>
    request<PartiesOverview>("POST", "/parties/accept", { ids, names }),
  createParty: (name: string, identities: PartyIdentity[]) =>
    request<PartiesOverview>("POST", "/parties", { name, identities: identities.map(identityBody) }),
  setPartyIdentity: (identity: PartyIdentity, action: "assign" | "dismiss" | "release", partyId?: string) =>
    request<PartiesOverview>("POST", "/parties/identities", { ...identityBody(identity), action, ...(partyId ? { party_id: partyId } : {}) }),
  renameParty: (id: string, name: string) => request<PartiesOverview>("POST", `/parties/${enc(id)}/rename`, { name }),
  mergeParty: (id: string, into: string) => request<PartiesOverview>("POST", `/parties/${enc(id)}/merge`, { into }),
  deleteParty: (id: string) => request<PartiesOverview>("POST", `/parties/${enc(id)}/delete`, {}),
  // 138: accounts and cards registered with their details, and a party's data month by month
  registerPartyAccount: (id: string, number: string, details: AccountDetailsInput) =>
    request<PartiesOverview>("POST", `/parties/${enc(id)}/accounts`, { number, ...details }),
  setPartyAccount: (key: string, details: AccountDetailsInput) =>
    request<PartiesOverview>("POST", "/parties/accounts/details", { key, ...details }),
  partyMonths: (id: string, start?: string, end?: string) =>
    request<PartyMonths>("GET", `/parties/${enc(id)}/months${start && end ? `?start=${enc(start)}&end=${enc(end)}` : ""}`),
  /** 062: the accepted task marked as done by hand (or unmarked). */
  packageStatementSurvey: (id: string, paths: string[], recursive = false) =>
    request<StatementPackageSurvey>("POST", `/workpackages/${enc(id)}/statements/survey`, { paths, recursive }),
  addPackageStatements: (id: string, body: { paths: string[]; statements: string[]; pdfs: string[]; expected_revision: number; recursive?: boolean }) =>
    request<WorkpackageView>("POST", `/workpackages/${enc(id)}/statements/add`, body),
  packageUtilityCost: (wpId: string) => request<UtilityReport>("GET", `/workpackages/${enc(wpId)}/result/utility-cost`),
  /** 178: the utility cost of the package's current result as a workbook, with the package's chosen template */
  packageUtilityCostXlsxUrl: (wpId: string) => `/api/workpackages/${enc(wpId)}/result/utility-cost.xlsx`,
  /** 191 (plan F-quote-package B3): the requests a quote can start from (searched by the service), and a quote package */
  utilityCost: (runId: string) => request<UtilityReport>("GET", `/runs/${enc(runId)}/reports/utility-cost`),
};
