// 143 (DECISIONS 143): the finder of the pairing page's two lists — the selected line pinned with how much the ticked
// invoices cover, the invoices that fit it, the rest by amount only, the bound or settled ones closed, and per row
// whether the name, the number and the account match. Synthetic lines and invoices only; the local service is replaced
// by spies. Expectations use the English interface.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api, setActor, type ReconcileCandidate, type ReconcileInvoice, type ReconcileLine, type ReconcileMatch, type ReconcileWorkspace,
} from "../../api";
import { setLanguage } from "../../i18n";
import { bindingOf, criteria, daysFromDue, finderSections } from "./finder";
import { ReconcilePairing } from "./ReconcilePairing";

const WP = "wp-0000000000ee";
const STMT = "c".repeat(64);
const lineId = (n: number) => `${STMT.slice(0, 16)}:${String(n).padStart(12, "0")}:0`;
const invId = (n: number) => String(n).repeat(64).slice(0, 64);

const line = (n: number, over: Partial<ReconcileLine> = {}): ReconcileLine => ({
  id: lineId(n), statement_id: STMT, account: "111122233333444455556666", statement_type: "bank_account", currency: "HUF",
  booking_date: `2026-04-${String(10 + n).padStart(2, "0")}`, direction: "debit", amount: "1000.00", counterparty_name: "Example Federation",
  counterparty_account: "99998887-77776666-55554444", description: "Transfer", memo: `FED-000${n}`, state: "open", excluded_reason: null,
  allocated: "0", rest: "1000.00", mark: null, allocations: [], candidates: [], rejected: [], statement_verified: true,
  file: "statement.json", ...over,
});
const invoice = (n: number, over: Partial<ReconcileInvoice> = {}): ReconcileInvoice => ({
  id: invId(n), doc_type: "invoice_hu", number: `FED-000${n}`, supplier_name: "Example Federation", amount: "1000.00", currency: "HUF",
  issue_date: "2026-04-01", due_date: "2026-04-15", payment_method: null, file: `invoice-${n}.pdf`, state: "no_payment_found",
  allocated: "0", rest: "1000.00", allocations: [], candidates: [], source: "approved", own: true, ...over,
});
const match = (n: number, over: Partial<ReconcileMatch> = {}): ReconcileMatch => ({
  invoice_id: invId(n), fit: null, signals: [], amount_relation: "different", fx: null, difference: { amount: "0.00", currency: "HUF" },
  account_differs: false, in_window: true, strength: 0, by_due: true, days_after_issue: 10, days_from_due: -4, ...over,
});
const candidate = (l: number, i: number, over: Partial<ReconcileCandidate> = {}): ReconcileCandidate => ({
  invoice_id: invId(i), line_id: lineId(l), proposed: true, amount_only: false, signals: ["invoice_number"], amount_relation: "equal",
  multiple_candidates: false, source_review_required: false, fx: null, ...over,
});
const workspace = (lines: ReconcileLine[], invoices: ReconcileInvoice[]): ReconcileWorkspace => ({
  workpackage_id: WP, lines, invoices, coverage: [], blockers: [], line_marks: ["private", "fee", "other"], open: {},
  counts: { lines: {}, invoices: {}, open_lines: lines.length }, learned_names: [], fx_tolerance: null, engine_version: "1.10.0",
  config_hash: "x", scope: { workpackage_id: WP, accounts: ["111122233333444455556666"], period_start: "2026-04-01", period_end: "2026-04-30", revision: 1, updated_at: "" },
});

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

function page(ws: ReconcileWorkspace) {
  render(<ReconcilePairing ws={ws} readOnly={false} onWorkspace={vi.fn()} reload={() => {}} />);
}

// --- the groups and the columns, computed on the page ----------------------------------------------------------------------

describe("the finder's groups", () => {
  it("before the comparison: the engine's candidates fit, the rest by the nearest amount, the bound ones apart", () => {
    const l = line(1, { candidates: [candidate(1, 4, { proposed: false, amount_relation: "different" })], rejected: [invId(5)] });
    const elsewhere = invoice(3, { candidates: [candidate(2, 3)] }); // proposed for line 2
    const paid = invoice(6, { rest: "0.00", allocated: "1000.00", allocations: [{ invoice_id: invId(6), line_id: lineId(2), line_amount: "1000.00", invoice_amount: "1000.00", allocation_id: 1, workpackage_id: WP }] });
    const s = finderSections(l, [invoice(1, { amount: "900.00", rest: "900.00" }), invoice(2, { amount: "1500.00", rest: "1500.00" }), elsewhere,
      invoice(4, { amount: "50.00", rest: "50.00" }), invoice(5), paid], null);
    expect(s.fits.map((e) => e.invoice.id)).toEqual([invId(4)]);
    expect(s.byAmount.map((e) => e.invoice.id)).toEqual([invId(1), invId(2)]); // 100 off before 500 off
    expect(s.bound.map((e) => e.binding.kind).sort()).toEqual(["paid", "proposed_elsewhere", "rejected"]);
  });

  it("after the comparison: the service's order, and an invoice it says fits joins the fitting ones", () => {
    const l = line(1);
    const matches = new Map([match(2, { fit: "named" }), match(1)].map((m) => [m.invoice_id, m]));
    const s = finderSections(l, [invoice(1), invoice(2)], matches);
    expect(s.fits.map((e) => e.invoice.id)).toEqual([invId(2)]);
    expect(s.byAmount.map((e) => e.invoice.id)).toEqual([invId(1)]);
  });

  it("tells a matching, a loose, a missing and a contradicting fact apart", () => {
    const l = line(1);
    expect(criteria(l, invoice(1), match(1, { signals: ["supplier_name", "invoice_number", "supplier_account"], amount_relation: "equal" })))
      .toEqual({ name: "yes", number: "yes", account: "yes", amount: "yes" });
    expect(criteria(l, invoice(1), match(1, { signals: ["supplier_name_fuzzy"], account_differs: true })))
      .toEqual({ name: "loose", number: "no", account: "differs", amount: "no" });
    expect(criteria(line(1, { memo: null, description: null, counterparty_name: null }), invoice(1), match(1, { amount_relation: null })))
      .toEqual({ name: "unknown", number: "unknown", account: "unknown", amount: "unknown" });
  });

  it("knows an invoice this line paid, and counts the days against the due date", () => {
    const share = { invoice_id: invId(1), line_id: lineId(1), line_amount: "400.00", invoice_amount: "400.00", allocation_id: 3, workpackage_id: WP };
    expect(bindingOf(invoice(1, { allocated: "400.00", rest: "600.00", allocations: [share] }), line(1, { allocations: [share] })).kind).toBe("this_line");
    expect(bindingOf(invoice(1, { allocated: "400.00", rest: "600.00" }), line(2)).kind).toBe("partly_paid");
    expect([daysFromDue(line(1), invoice(1)), daysFromDue(line(9), invoice(1)), daysFromDue(line(1), invoice(1, { due_date: null }))]).toEqual([-4, 4, null]);
  });
});

// --- the page ---------------------------------------------------------------------------------------------------------------

describe("the finder on the pairing page", () => {
  it("shows what matches per invoice, how much is left to cover, and keeps the bound ones closed", async () => {
    const spy = vi.spyOn(api, "reconcileMatches").mockResolvedValue({ line_id: lineId(1), matches: [
      match(2, { fit: "named", signals: ["invoice_number", "supplier_name"], amount_relation: "different", difference: { amount: "-400.00", currency: "HUF" } }),
      match(1, { difference: { amount: "-100.00", currency: "HUF" }, account_differs: true }),
      match(3, { fit: "tied", signals: ["supplier_name"] }),
    ] });
    page(workspace([line(1), line(2)], [invoice(1, { amount: "900.00", rest: "900.00", supplier_name: "Other Vendor" }),
      invoice(2, { amount: "600.00", rest: "600.00" }), invoice(3, { candidates: [candidate(2, 3)] })]));
    expect(screen.getByText("Finding the invoice for")).toBeTruthy();
    expect(screen.getByText("Still to cover: 1,000.00 HUF")).toBeTruthy();
    const fits = await screen.findByRole("list", { name: "Invoices that fit" });
    await waitFor(() => expect(within(fits).getByText(/FED-0002/)).toBeTruthy());
    expect(spy).toHaveBeenCalledWith(WP, lineId(1));
    expect(within(fits).getByRole("img", { name: "The memo names the invoice" })).toBeTruthy();
    expect(within(fits).getByText("400.00 HUF less than the line")).toBeTruthy();
    const rest = screen.getByRole("list", { name: "By amount only, nearest first" });
    expect(within(rest).getByRole("img", { name: "Paid to another account than the one on the invoice" })).toBeTruthy();
    expect(within(rest).getByRole("img", { name: "The name does not match" })).toBeTruthy();
    // the invoice proposed for line 2 stands closed among the bound ones, with the line it is proposed for
    expect(screen.queryByText(/FED-0003/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Bound to another line or settled \(1\)/ }));
    expect(screen.getByText("proposed for another line: 2026-04-12, −1,000.00 HUF")).toBeTruthy();
    // ticking invoices fills the bar
    fireEvent.click(screen.getByRole("checkbox", { name: /Select the invoice Example Federation · FED-0002/ }));
    expect(screen.getByText("Still to cover: 400.00 HUF")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: /Select the invoice Other Vendor · FED-0001/ }));
    expect(screen.getByText("More than the line: 500.00 HUF")).toBeTruthy();
  });

  it("says when no invoice fits and offers the needs-no-invoice mark", async () => {
    vi.spyOn(api, "reconcileMatches").mockResolvedValue({ line_id: lineId(1), matches: [match(1, { difference: { amount: "-700.00", currency: "HUF" } })] });
    page(workspace([line(1)], [invoice(1, { amount: "300.00", rest: "300.00" })]));
    expect(await screen.findByText(/No invoice fits/)).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: /^Needs no invoice/ })[0]);
    expect(screen.getByRole("form", { name: "Needs no invoice" })).toBeTruthy();
  });

  it("picks a fitting invoice the service found with the key 1", async () => {
    vi.spyOn(api, "reconcileMatches").mockResolvedValue({ line_id: lineId(1), matches: [match(2, { fit: "named", signals: ["invoice_number"] }), match(1)] });
    page(workspace([line(1)], [invoice(1, { amount: "300.00", rest: "300.00" }), invoice(2)]));
    await screen.findByRole("img", { name: "The memo names the invoice" });
    act(() => { fireEvent.keyDown(window, { key: "1" }); });
    expect((screen.getByRole("checkbox", { name: /FED-0002/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("Covered exactly")).toBeTruthy();
  });

  it("works without the comparison: the engine's candidates still fit", async () => {
    vi.spyOn(api, "reconcileMatches").mockRejectedValue(new Error("offline"));
    page(workspace([line(1, { state: "proposed", candidates: [candidate(1, 2)] })], [invoice(1), invoice(2)]));
    expect(within(screen.getByRole("list", { name: "Invoices that fit" })).getByText(/FED-0002/)).toBeTruthy();
    expect(await screen.findByText("The comparison is not available: offline")).toBeTruthy();
  });
});
