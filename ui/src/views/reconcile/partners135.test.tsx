// 135 (plan 134 P2): the partner of a statement line on the pairing page — the lines grouped by partner, the suggested
// needs-no-invoice reason (a person's earlier reason first, then the AI's kind of payment), the group marked and
// unmarked in one step, the lines whose invoice is expected but missing, and a candidate's strength and the engines
// that chose it. Synthetic lines and invoices only; the local service is replaced by spies.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api, setActor, type ReconcileAiProposal, type ReconcileInvoice, type ReconcileLine, type ReconcileWorkspace,
} from "../../api";
import { setLanguage } from "../../i18n";
import { invoiceMatches, lineMatches, NO_INVOICE_FILTERS, NO_LINE_FILTERS, NO_PARTY } from "./filters";
import { expectsInvoice, groupByPartner, suggestMark } from "./partners";
import { ReconcilePairing } from "./ReconcilePairing";

const WP = "wp-0000000000bb";
const STMT = "c".repeat(64);
const lineId = (n: number) => `${STMT.slice(0, 16)}:${String(n).padStart(12, "0")}:0`;
const invId = (n: number) => String(n).repeat(64).slice(0, 64);

const answer = (kind: string, over: Partial<ReconcileAiProposal> = {}): ReconcileAiProposal => ({
  pays: null, pays_probability: null, options: [], kind, kind_probability: 0.9, measured: true, error: null, created_at: "",
  suggested_mark: ({ retail_purchase: "private", bank_fee: "fee" } as Record<string, string>)[kind] ?? null,
  expects_invoice: ["subscription", "utility_or_telecom"].includes(kind), ...over,
});
const line = (n: number, partner: string, over: Partial<ReconcileLine> = {}): ReconcileLine => ({
  id: lineId(n), statement_id: STMT, account: "11112223333444455556666", statement_type: "credit_card", currency: "HUF",
  booking_date: `2026-04-${String(10 + n).padStart(2, "0")}`, direction: "debit", amount: "100.00",
  counterparty_name: `${partner.toUpperCase()}*${1000 + n}`, counterparty_account: null, description: "Purchase", memo: null,
  state: "open", excluded_reason: null, allocated: "0", rest: "100.00", mark: null, allocations: [], candidates: [], rejected: [],
  statement_verified: true, file: "statement.pdf", partner, earlier_marks: [], ...over,
});
const invoice = (n: number): ReconcileInvoice => ({
  id: invId(n), doc_type: "invoice_hu", number: `INV-000${n}`, supplier_name: `Example Supplier ${n}`, amount: "100.00", currency: "HUF",
  issue_date: "2026-04-01", due_date: "2026-04-15", payment_method: null, file: `invoice-${n}.pdf`, state: "no_payment_found",
  allocated: "0", rest: "100.00", allocations: [], candidates: [], source: "approved",
});
const workspace = (lines: ReconcileLine[], invoices: ReconcileInvoice[] = []): ReconcileWorkspace => ({
  workpackage_id: WP, lines, invoices, coverage: [], blockers: [], line_marks: ["private", "fee", "own_transfer", "tax", "cash", "salary", "other"],
  open: {}, counts: { lines: {}, invoices: {}, open_lines: lines.length }, learned_names: [], fx_tolerance: null, engine_version: "1.5.0",
  config_hash: "x", scope: { workpackage_id: WP, accounts: ["11112223333444455556666"], period_start: "2026-04-01", period_end: "2026-04-30", revision: 1, updated_at: "" },
});

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

function page(ws: ReconcileWorkspace) {
  render(<ReconcilePairing ws={ws} readOnly={false} onWorkspace={vi.fn()} reload={() => {}} />);
}

describe("the suggested reason and the expected invoice", () => {
  it("prefers a person's earlier reason for the partner to the AI's", () => {
    const shop = line(1, "exampleshop", { ai: { jev: answer("bank_fee"), gpt: answer("bank_fee") }, earlier_marks: [{ category: "private", lines: 3 }] });
    expect(suggestMark([shop])).toEqual({ category: "private", source: "earlier", lines: 3 });
  });

  it("suggests the AI's reason only when every line and both engines agree", () => {
    const both = (n: number, kind: string, gpt = kind) => line(n, "exampleshop", { ai: { jev: answer(kind), gpt: answer(gpt) } });
    expect(suggestMark([both(1, "retail_purchase"), both(2, "retail_purchase")])).toEqual({ category: "private", source: "ai_both", engines: ["jev", "gpt"] });
    expect(suggestMark([both(1, "retail_purchase", "subscription")])).toBeNull(); // the engines disagree
    expect(suggestMark([both(1, "retail_purchase"), both(2, "bank_fee")])).toBeNull(); // the lines disagree
    expect(suggestMark([line(1, "exampleshop", { ai: { jev: answer("retail_purchase") } })])).toEqual({ category: "private", source: "ai_one", engines: ["jev"] });
    expect(suggestMark([line(1, "exampleshop")])).toBeNull(); // no answer
  });

  it("says an invoice is expected only for a line still to decide without a candidate", () => {
    const sub = { ai: { jev: answer("subscription") } };
    expect(expectsInvoice(line(1, "examplestream", sub))).toBe(true);
    expect(expectsInvoice(line(1, "examplestream", { ...sub, state: "marked" }))).toBe(false);
    const candidate = { invoice_id: invId(1), line_id: lineId(1), proposed: false, amount_only: true, signals: [], amount_relation: "equal" as const,
      multiple_candidates: false, source_review_required: false, fx: null };
    expect(expectsInvoice(line(1, "examplestream", { ...sub, state: "amount_only", candidates: [candidate] }))).toBe(false);
  });

  it("filters the lines and the invoices by what a person sets", () => {
    const cafe = line(1, "examplecafe", { amount: "30.00", ai: { gpt: answer("retail_purchase") } });
    expect(lineMatches({ ...NO_LINE_FILTERS, partner: "examplecafe", kind: "retail_purchase", min: "20", max: "30" }, cafe)).toBe(true);
    expect(lineMatches({ ...NO_LINE_FILTERS, kind: "subscription" }, cafe)).toBe(false);
    expect(lineMatches({ ...NO_LINE_FILTERS, direction: "credit" }, cafe)).toBe(false);
    expect(lineMatches({ ...NO_LINE_FILTERS, min: "30.01" }, cafe)).toBe(false);
    const inv = { ...invoice(1), supplier_name: "Exâmple Shop Kft.", issue_date: "2026-04-05", party: null };
    expect(invoiceMatches({ ...NO_INVOICE_FILTERS, supplier: "example shop kft.", party: NO_PARTY, from: "2026-04-01", to: "2026-04-30" }, inv, null)).toBe(true);
    expect(invoiceMatches({ ...NO_INVOICE_FILTERS, to: "2026-04-04" }, inv, null)).toBe(false);
    expect(invoiceMatches({ ...NO_INVOICE_FILTERS, withCandidates: true }, inv, null)).toBe(false);
    const target = line(2, "exampleshop", { amount: "95.00", rest: "95.00" });
    expect(invoiceMatches({ ...NO_INVOICE_FILTERS, near: true, nearPct: "5" }, inv, target)).toBe(false); // 100 is 5.3% off
    expect(invoiceMatches({ ...NO_INVOICE_FILTERS, near: true, nearPct: "6" }, inv, target)).toBe(true);
    expect(invoiceMatches({ ...NO_INVOICE_FILTERS, near: true }, { ...inv, currency: "EUR" }, target)).toBe(false);
  });

  it("groups the lines by partner, the largest group first", () => {
    const groups = groupByPartner([line(1, "examplecafe"), line(2, "exampleshop"), line(3, "exampleshop"), line(4, "exampleshop", { partner: null })]);
    expect(groups.map((g) => [g.key.startsWith("line:") ? "own" : g.key, g.lines.length])).toEqual([["exampleshop", 2], ["examplecafe", 1], ["own", 1]]);
  });
});

describe("the partners on the pairing page", () => {
  const shop = (n: number) => line(n, "exampleshop", { ai: { jev: answer("retail_purchase"), gpt: answer("retail_purchase") } });

  it("marks a partner's lines in one step with the suggested reason chosen", async () => {
    const mark = vi.spyOn(api, "reconcileMark").mockResolvedValue(workspace([]));
    page(workspace([shop(1), line(2, "examplecafe"), shop(3)]));
    fireEvent.click(screen.getByRole("checkbox", { name: "By partner" }));
    const head = screen.getByRole("listitem", { name: "Partner EXAMPLESHOP*1001" });
    expect(within(head).getByText("AI suggests: Private expense (JEV and GPT agree)")).toBeTruthy();
    fireEvent.click(within(head).getByRole("button", { name: "Needs no invoice (2)" }));
    expect((screen.getByRole("radio", { name: "Private expense" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Save for 2 lines" }));
    await waitFor(() => expect(mark).toHaveBeenCalledWith(WP, [lineId(1), lineId(3)], "private", undefined));
  });

  it("undoes the marks of a partner's lines in one step", async () => {
    const unmark = vi.spyOn(api, "reconcileUnmark").mockResolvedValue(workspace([]));
    const marked = (n: number) => line(n, "exampleshop", { state: "marked",
      mark: { id: n, line_id: lineId(n), statement_id: STMT, category: "private", note: null, workpackage_id: WP } });
    page(workspace([marked(1), marked(2)]));
    fireEvent.click(screen.getByRole("button", { name: /^Needs no invoice \(2\)/ })); // the state filter
    fireEvent.click(screen.getByRole("checkbox", { name: "By partner" }));
    fireEvent.click(screen.getByRole("button", { name: "Undo the marks (2)" }));
    await waitFor(() => expect(unmark).toHaveBeenCalledWith(WP, [lineId(1), lineId(2)]));
  });

  it("lists the lines whose invoice is expected but missing, per partner", () => {
    const sub = (n: number) => line(n, "examplestream", { ai: { jev: answer("subscription"), gpt: answer("subscription") } });
    page(workspace([sub(1), shop(2), sub(3)]));
    fireEvent.click(screen.getByRole("button", { name: "Invoice expected (2)" }));
    const lines = screen.getByRole("list", { name: "Statement lines" });
    expect(within(lines).getByRole("listitem", { name: "Partner EXAMPLESTREAM*1001" })).toBeTruthy();
    expect(within(lines).getByText("invoice expected: 2")).toBeTruthy();
    expect(within(lines).queryByText(/EXAMPLESHOP/)).toBeNull();
  });

  it("shows a candidate's strength and the engines that chose it, and the AI's own choice among the candidates", () => {
    const candidate = { invoice_id: invId(1), line_id: lineId(1), proposed: true, amount_only: false, signals: ["supplier_name" as const],
      amount_relation: "equal" as const, multiple_candidates: false, source_review_required: false, fx: null, strength: 55, by_due: true };
    page(workspace([line(1, "exampleshop", { state: "proposed", candidates: [candidate],
      ai: { jev: answer("online_order", { pays: invId(1), pays_probability: 0.87 }), gpt: answer("online_order", { pays: invId(2), pays_probability: 0.95 }) } })],
    [invoice(1), invoice(2)]));
    const list = screen.getByText("Candidates of the selected line").nextElementSibling as HTMLElement;
    expect(within(list).getByText("strength 55")).toBeTruthy();
    expect(within(list).getByText("JEV 0.87")).toBeTruthy();
    expect(within(list).getByText("GPT 0.95")).toBeTruthy();
    expect(within(list).getByText("AI only: code found nothing that ties them")).toBeTruthy();
    expect(within(list).getByText(/Example Supplier 2/)).toBeTruthy();
  });

  it("narrows the lines by partner and the other invoices by supplier and nearness to the line's amount", () => {
    const near = { ...invoice(2), supplier_name: "Example Shop Kft.", amount: "105.00", rest: "105.00" };
    const far = { ...invoice(3), supplier_name: "Example Shop Kft.", amount: "300.00", rest: "300.00" };
    page(workspace([shop(1), line(2, "examplecafe"), shop(3)], [invoice(1), near, far]));
    const linesPane = screen.getByRole("region", { name: "Statement lines" });
    fireEvent.click(within(linesPane).getByRole("button", { name: "Filters" }));
    fireEvent.click(within(linesPane).getByRole("button", { name: /^Partner of the line/ }));
    fireEvent.click(screen.getByRole("option", { name: /EXAMPLECAFE/ }));
    expect(within(linesPane).queryByRole("checkbox", { name: /EXAMPLESHOP/ })).toBeNull();
    expect(within(linesPane).getByRole("button", { name: "Filters (1)" })).toBeTruthy();
    const invoicesPane = screen.getByRole("region", { name: "Invoices" });
    fireEvent.click(within(invoicesPane).getByRole("button", { name: "Filters" }));
    fireEvent.click(within(invoicesPane).getByRole("button", { name: /^Supplier/ }));
    fireEvent.click(screen.getByRole("option", { name: /Example Shop Kft/ }));
    expect(within(invoicesPane).queryByText(/Example Supplier 1/)).toBeNull();
    expect(within(invoicesPane).getByText(/INV-0002/) && within(invoicesPane).getByText(/INV-0003/)).toBeTruthy();
    fireEvent.click(within(invoicesPane).getByRole("checkbox", { name: "Near the selected line's amount" })); // ±10% of 100.00
    expect(within(invoicesPane).getByText(/INV-0002/)).toBeTruthy();
    expect(within(invoicesPane).queryByText(/INV-0003/)).toBeNull();
  });

  it("selects the partner's lines with p", () => {
    page(workspace([shop(1), line(2, "examplecafe"), shop(3)]));
    act(() => { fireEvent.keyDown(window, { key: "p" }); });
    expect(screen.getByText(/^Lines: 2/)).toBeTruthy();
    expect((screen.getByRole("checkbox", { name: /Select the line EXAMPLESHOP\*1003/ }) as HTMLInputElement).checked).toBe(true);
  });
});
