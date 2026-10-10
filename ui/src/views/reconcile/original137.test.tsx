// 137 (DECISIONS 137): a card purchase whose bank printed its original amount (the Erste PDF statement) shows it next to
// the forint line, and a candidate compared on it says so. Synthetic lines and invoices only.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setActor, type ReconcileInvoice, type ReconcileLine, type ReconcileWorkspace } from "../../api";
import { setLanguage } from "../../i18n";
import { ReconcilePairing } from "./ReconcilePairing";

const WP = "wp-0000000000cc";
const STMT = "d".repeat(64);
const LINE = `${STMT.slice(0, 16)}:000000000001:0`;
const INV = "e".repeat(64);

const line: ReconcileLine = {
  id: LINE, statement_id: STMT, account: "111122233333444455556666", statement_type: "bank_account", currency: "HUF",
  booking_date: "2026-06-02", direction: "debit", amount: "7291.00", counterparty_name: "EXAMPLE CLOUD INC",
  counterparty_account: null, description: "Card use", memo: null, original_amount: "20.00", original_currency: "USD",
  state: "proposed", excluded_reason: null, allocated: "0", rest: "7291.00", mark: null, allocations: [], rejected: [],
  candidates: [{ invoice_id: INV, line_id: LINE, proposed: true, amount_only: false, signals: ["supplier_name"],
    amount_relation: "equal", multiple_candidates: false, source_review_required: false, fx: null, strength: 80,
    original: { amount: "20.00", currency: "USD" } }],
  statement_verified: true, file: "statement.json", partner: "example cloud inc", earlier_marks: [],
};
const invoice: ReconcileInvoice = {
  id: INV, doc_type: "invoice_foreign", number: "EC-0601", supplier_name: "Example Cloud Inc.", amount: "20.00", currency: "USD",
  issue_date: "2026-06-01", due_date: null, payment_method: null, file: "invoice.pdf", state: "proposed",
  allocated: "0", rest: "20.00", allocations: [], candidates: [], source: "approved",
};
const ws: ReconcileWorkspace = {
  workpackage_id: WP, lines: [line], invoices: [invoice], coverage: [], blockers: [], line_marks: ["private", "fee", "other"],
  open: {}, counts: { lines: {}, invoices: {}, open_lines: 1 }, learned_names: [], fx_tolerance: null, engine_version: "1.6.0",
  config_hash: "x", scope: { workpackage_id: WP, accounts: ["111122233333444455556666"], period_start: "2026-06-01",
    period_end: "2026-06-30", revision: 1, updated_at: "" },
};

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

describe("a card purchase's original amount (137)", () => {
  it("is shown next to the line and on its candidate", () => {
    render(<ReconcilePairing ws={ws} readOnly={false} onWorkspace={vi.fn()} reload={() => {}} />);
    expect(screen.getAllByText(/originally 20[.,]00/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/on the card purchase's original 20[.,]00/).length).toBeGreaterThan(0);
  });
});
