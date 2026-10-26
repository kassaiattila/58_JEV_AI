// 141 (DECISIONS 141): one transfer whose memo names three invoices that add up to it is proposed with all three, and
// choosing one of them chooses the group; an invoice its credit note cancels says so. Synthetic lines and invoices only.
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setActor } from "../../../api";
import type { ReconcileCandidate, ReconcileInvoice, ReconcileLine, ReconcileWorkspace } from "../api";
import { setLanguage } from "../../../i18n";
import { ReconcilePairing } from "./ReconcilePairing";

const WP = "wp-0000000000dd";
const STMT = "a".repeat(64);
const LINE = `${STMT.slice(0, 16)}:000000000001:0`;
const IDS = ["1", "2", "3"].map((n) => n.repeat(64));
const CREDITED = "4".repeat(64);

const candidate = (id: string): ReconcileCandidate => ({
  invoice_id: id, line_id: LINE, proposed: true, amount_only: false, signals: ["invoice_number", "supplier_account"],
  amount_relation: "combined", multiple_candidates: false, source_review_required: false, fx: null, strength: 95, combined: IDS,
});
const line: ReconcileLine = {
  id: LINE, statement_id: STMT, account: "111122233333444455556666", statement_type: "bank_account", currency: "HUF",
  booking_date: "2026-07-03", direction: "debit", amount: "300.00", counterparty_name: "EXAMPLE FEDERATION",
  counterparty_account: "99998887-77776666-55554444", description: "Outgoing transfer", memo: "INV-0101, INV-0102, INV-0103",
  original_amount: null, original_currency: null, state: "proposed", excluded_reason: null, allocated: "0", rest: "300.00",
  mark: null, allocations: [], rejected: [], candidates: IDS.map(candidate), statement_verified: true, file: "statement.json",
  partner: "example federation", earlier_marks: [],
};
const invoice = (id: string, number: string, amount: string, extra: Partial<ReconcileInvoice> = {}): ReconcileInvoice => ({
  id, doc_type: "invoice_hu", number, supplier_name: "Example Federation", amount, currency: "HUF", issue_date: "2026-06-25",
  due_date: null, payment_method: null, file: `${number}.pdf`, state: "proposed", allocated: "0", rest: amount, allocations: [],
  candidates: [], source: "approved", ...extra,
});
const ws: ReconcileWorkspace = {
  workpackage_id: WP, lines: [line],
  invoices: [invoice(IDS[0], "INV-0101", "100.00"), invoice(IDS[1], "INV-0102", "150.00"), invoice(IDS[2], "INV-0103", "50.00"),
    invoice(CREDITED, "INV-0201", "169.00", { state: "credited", credited_by: { id: "5".repeat(64), number: "CN-0202" } })],
  coverage: [], blockers: [], line_marks: ["private", "fee", "other"], open: {}, counts: { lines: {}, invoices: {}, open_lines: 1 },
  learned_names: [], fx_tolerance: null, engine_version: "1.9.0", config_hash: "x",
  scope: { workpackage_id: WP, accounts: ["111122233333444455556666"], period_start: "2026-07-01", period_end: "2026-07-31",
    revision: 1, updated_at: "" },
};

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

describe("a combined payment and a credit note (141)", () => {
  it("proposes the named invoices together and chooses the group at once", () => {
    const { container } = render(<ReconcilePairing ws={ws} readOnly={false} onWorkspace={vi.fn()} reload={() => {}} />);
    expect(screen.getAllByText("with the other named invoices, the line's amount").length).toBe(3);
    fireEvent.click(screen.getAllByRole("checkbox", { name: /INV-0102/ })[0]);
    expect(container.querySelectorAll(".rc-frow.proposed.is-selected").length).toBe(3);
  });

  it("says which credit note cancels an invoice", () => {
    render(<ReconcilePairing ws={ws} readOnly={false} onWorkspace={vi.fn()} reload={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Bound to another line or settled \(1\)/ })); // 143: settled ones stand closed
    expect(screen.getAllByText("Cancelled by a credit note").length).toBeGreaterThan(0);
    expect(screen.getAllByText("credit note: CN-0202").length).toBeGreaterThan(0);
  });
});
