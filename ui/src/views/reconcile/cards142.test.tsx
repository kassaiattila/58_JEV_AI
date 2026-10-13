// 142 (DECISIONS 142): the pairing page as cards - a transfer with the invoices it pays on one card with every fact of
// both sides and each pair's days against the due date, the lists as chips, a possible double payment opening its
// documents by itself, and the hand-off to the two lists. Synthetic lines and invoices only; the service is spied on.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api, setActor, type ReconcileGroup, type ReconcileInvoice, type ReconcileLine, type ReconcileLocation, type ReconcileOverview,
  type ReconcileWorkspace,
} from "../../api";
import { setLanguage } from "../../i18n";
import { ReconcileCards } from "./ReconcileCards";

const WP = "wp-0000000000ee";
const STMT = "c".repeat(64);
const lineId = (n: number) => `${STMT.slice(0, 16)}:${String(n).padStart(12, "0")}:0`;
const invId = (n: number) => String(n).repeat(64).slice(0, 64);

const line = (n: number, over: Partial<ReconcileLine> = {}): ReconcileLine => ({
  id: lineId(n), statement_id: STMT, account: "111122233333444455556666", statement_type: "bank_account", currency: "HUF",
  booking_date: "2026-04-20", direction: "debit", amount: "300.00", counterparty_name: `Example Partner ${n}`,
  counterparty_account: "99998887-77776666-55554444", description: "Outgoing transfer", memo: `INV-010${n}`, state: "open",
  excluded_reason: null, allocated: "0", rest: "300.00", mark: null, allocations: [], candidates: [], rejected: [],
  statement_verified: true, file: "statement.json", value_date: "2026-04-21", running_balance: "1000.00", ...over,
});
const invoice = (n: number, over: Partial<ReconcileInvoice> = {}): ReconcileInvoice => ({
  id: invId(n), doc_type: "invoice_hu", number: `INV-010${n}`, supplier_name: "Example Supplier Kft.", amount: "100.00",
  currency: "HUF", issue_date: "2026-04-01", due_date: "2026-04-15", payment_method: "transfer", file: `inv-${n}.pdf`,
  state: "proposed", allocated: "0", rest: "100.00", allocations: [], candidates: [], source: "approved",
  supplier_tax_id: "12345678-2-41", payment_account: "99998887-77776666-55554444", net_total: "78.74", vat_total: "21.26",
  fulfillment_date: "2026-03-31", checked_until: "2026-06-30", ...over,
});
const proposal = (l: number, i: number, combined: number[] | null = null) => ({
  invoice_id: invId(i), line_id: lineId(l), proposed: true, amount_only: false, signals: ["invoice_number" as const],
  amount_relation: (combined ? "combined" : "equal") as "combined" | "equal", multiple_candidates: false,
  source_review_required: false, fx: null, combined: combined ? combined.map(invId) : null,
});
// 144: the documents' statement pane gets the statement as read with the line's place
const located = (id: string): ReconcileLocation => ({
  line_id: id, statement_id: STMT, open: null, image: null, pages: null, page: null, box: null, original: null,
  statement: { file: null, institution: null, account: "A", currency: "HUF", period_start: null, period_end: null,
    opening_balance: null, closing_balance: null, verified: true, lines: [] },
});
const facts = (over = {}) => ({ paid_on: null, days_from_due: null, overdue_days: null, checked_until: "2026-06-30", double_payment: null, ...over });

// the combined card: line 1 pays invoices 1-3; invoice 4 has no payment; lines 5 and 6 pay invoice 5 twice
const lines = [
  line(1, { state: "proposed", candidates: [1, 2, 3].map((i) => proposal(1, i, [1, 2, 3])) }),
  line(5, { amount: "80.00", rest: "0", allocated: "80.00", state: "allocated", booking_date: "2026-05-10",
    allocations: [{ invoice_id: invId(5), line_id: lineId(5), line_amount: "80.00", invoice_amount: "80.00", allocation_id: 7, workpackage_id: WP }] }),
  line(6, { amount: "80.00", rest: "80.00", booking_date: "2026-05-20" }),
];
const invoices = [
  invoice(1, { due_date: "2026-04-15" }), invoice(2, { amount: "150.00", rest: "150.00", due_date: "2026-04-20" }),
  invoice(3, { amount: "50.00", rest: "50.00", due_date: "2026-04-23" }),
  invoice(4, { state: "no_payment_found", issue_date: "2026-04-05" }),
  invoice(5, { amount: "80.00", rest: "0", allocated: "80.00", state: "confirmed", due_date: "2026-05-15" }),
];
const groups: ReconcileGroup[] = [
  { id: "line:a", kind: "proposed", date: "2026-04-20", lines: [lineId(1)], invoices: [invId(1), invId(2), invId(3)],
    pairs: [[1, 5], [2, 0], [3, -3]].map(([i, d]) => ({ line_id: lineId(1), invoice_id: invId(i), state: "proposed" as const, days_from_due: d, relation: "combined" as const })),
    flags: ["late"], lists: ["to_decide", "late"] },
  { id: "invoice:b", kind: "invoice_only", date: "2026-04-15", lines: [], invoices: [invId(4)], pairs: [], flags: ["overdue"],
    lists: ["invoice_without_payment", "overdue"] },
  { id: "line:c", kind: "paired", date: "2026-05-10", lines: [lineId(5), lineId(6)], invoices: [invId(5)],
    pairs: [{ line_id: lineId(5), invoice_id: invId(5), state: "allocated", days_from_due: -5, line_amount: "80.00", allocation_id: 7 },
      { line_id: lineId(6), invoice_id: invId(5), state: "repeat", days_from_due: null }],
    flags: ["double_payment"], lists: ["to_decide", "double_payment", "clarify", "paired"] },
];
const overview: ReconcileOverview = {
  groups,
  invoices: { [invId(1)]: facts({ paid_on: "2026-04-20", days_from_due: 5 }), [invId(2)]: facts({ paid_on: "2026-04-20", days_from_due: 0 }),
    [invId(3)]: facts({ paid_on: "2026-04-20", days_from_due: -3 }), [invId(4)]: facts({ overdue_days: 76 }),
    [invId(5)]: facts({ paid_on: "2026-05-10", days_from_due: -5, double_payment: { line_ids: [lineId(5), lineId(6)], paid_by: [lineId(5)] } }) },
  counts: { to_decide: 2, line_without_invoice: 0, invoice_without_payment: 1, overdue: 1, late: 1, double_payment: 1, clarify: 1,
    paired: 1, marked: 0, credited: 0, excluded: 0, all: 3 },
};
const ws: ReconcileWorkspace = {
  workpackage_id: WP, lines, invoices, coverage: [], blockers: [], line_marks: ["private", "fee", "other"], open: {},
  counts: { lines: {}, invoices: {}, open_lines: 2 }, learned_names: [], fx_tolerance: null, engine_version: "1.10.0", config_hash: "x",
  scope: { workpackage_id: WP, accounts: ["111122233333444455556666"], period_start: "2026-04-01", period_end: "2026-06-30", revision: 1, updated_at: "" },
  overview,
};

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

function cards(onManual = vi.fn()) {
  const onWorkspace = vi.fn();
  render(<ReconcileCards ws={ws} readOnly={false} onWorkspace={onWorkspace} reload={() => {}} onManual={onManual} />);
  return { onWorkspace, onManual };
}

describe("the cards of the pairing page (142)", () => {
  it("shows a transfer with the three invoices it pays, every fact, and each pair's days against the due date", () => {
    vi.spyOn(api, "reconcileLocate").mockResolvedValue(located(lineId(1)));
    cards();
    const card = screen.getByRole("article", { name: /Proposal to decide: Example Partner 1/ });
    expect(within(card).getByText("Invoices (3)")).toBeTruthy();
    for (const text of ["5 days late", "on the due date", "3 days before the due date", "12345678-2-41", "2026-04-21", "INV-0101"]) {
      expect(within(card).getAllByText(new RegExp(text)).length).toBeGreaterThan(0);
    }
    expect(within(card).getAllByText("paid late").length).toBe(1);
  });

  it("accepts the card's proposal with one share per invoice", async () => {
    vi.spyOn(api, "reconcileLocate").mockResolvedValue(located(lineId(1)));
    const allocate = vi.spyOn(api, "reconcileAllocate").mockResolvedValue(ws);
    const { onWorkspace } = cards();
    const card = screen.getByRole("article", { name: /Proposal to decide/ });
    fireEvent.click(within(card).getByRole("button", { name: /^Accept/ }));
    await waitFor(() => expect(onWorkspace).toHaveBeenCalled());
    expect(allocate).toHaveBeenCalledWith(WP, [
      { invoice_doc_id: invId(1), line_id: lineId(1), line_amount: "100.00" },
      { invoice_doc_id: invId(2), line_id: lineId(1), line_amount: "150.00" },
      { invoice_doc_id: invId(3), line_id: lineId(1), line_amount: "50.00" },
    ]);
  });

  it("lists the overdue invoice and the possible double payment under their chips", async () => {
    const locate = vi.spyOn(api, "reconcileLocate").mockResolvedValue(located(lineId(5)));
    cards();
    fireEvent.click(screen.getByRole("button", { name: "Overdue, no payment found (1 card(s))" }));
    const overdue = screen.getByRole("article", { name: /Invoice without a payment/ });
    expect(within(overdue).getByText(/Overdue, no payment found: 76 days after the due date, by 2026-06-30/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Possible double payment (1 card(s))" }));
    const double = screen.getByRole("article", { name: /Paired/ });
    expect(within(double).getByText("May repeat the payment")).toBeTruthy();
    expect(within(double).getByText(/Transferred 80.00 HUF more than invoiced/)).toBeTruthy(); // 160 for an invoice of 80
    // the card asks for a look, so its documents open by themselves
    await waitFor(() => expect(locate).toHaveBeenCalledWith(WP, lineId(5)));
    expect(within(double).getByRole("figure", { name: "Statement" })).toBeTruthy();
  });

  it("sends a card's open line to the two lists to be paired by hand", () => {
    const { onManual } = cards();
    fireEvent.click(screen.getByRole("button", { name: "Possible double payment (1 card(s))" }));
    fireEvent.click(within(screen.getByRole("article", { name: /Paired/ })).getByRole("button", { name: "Pair by hand" }));
    expect(onManual).toHaveBeenCalledWith(lineId(6));
  });
});
