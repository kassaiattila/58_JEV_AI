// 132 (backlog F-reconciliation E2): the reconciliation package's two-list pairing page, its preparation stage and its
// rules computed before sending (pairing.ts, money.ts). Synthetic lines and invoices only; the local service is
// replaced by spies. Expectations use the English interface (the language guard counts Hungarian letters in tests);
// a separate test checks that every new label has a Hungarian translation.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api, setActor, type ReconcileInvoice, type ReconcileLine, type ReconcileWorkspace, type WorkpackageView,
} from "../../api";
import hungarian from "../../i18n/hu-native.json";
import { setLanguage } from "../../i18n";
import { stepLabel } from "../../labels";
import { WorkpackageDetail } from "../WorkpackageDetail";
import { canonical, display, parseCanonical, parseInput } from "./money";
import { check, planPairing, toRequest } from "./pairing";
import { ReconcilePairing } from "./ReconcilePairing";

const WP = "wp-0000000000aa";
const STMT = "b".repeat(64);
const lineId = (n: number) => `${STMT.slice(0, 16)}:${String(n).padStart(12, "0")}:0`;
const invId = (n: number) => String(n).repeat(64).slice(0, 64);

const line = (n: number, over: Partial<ReconcileLine> = {}): ReconcileLine => ({
  id: lineId(n), statement_id: STMT, account: "11112223333444455556666", statement_type: "bank_account", currency: "HUF",
  booking_date: `2026-04-${String(10 + n).padStart(2, "0")}`, direction: "debit", amount: "100.00", counterparty_name: `Example Supplier ${n}`,
  counterparty_account: null, description: "Transfer", memo: `INV-000${n}`, state: "open", excluded_reason: null, allocated: "0",
  rest: "100.00", mark: null, allocations: [], candidates: [], rejected: [], statement_verified: true, file: "statement.pdf", ...over,
});
const invoice = (n: number, over: Partial<ReconcileInvoice> = {}): ReconcileInvoice => ({
  id: invId(n), doc_type: "invoice_hu", number: `INV-000${n}`, supplier_name: `Example Supplier ${n}`, amount: "100.00", currency: "HUF",
  issue_date: "2026-04-01", due_date: "2026-04-15", payment_method: null, file: `invoice-${n}.pdf`, state: "no_payment_found",
  allocated: "0", rest: "100.00", allocations: [], candidates: [], source: "approved", ...over,
});
const candidate = (l: number, i: number, over = {}) => ({
  invoice_id: invId(i), line_id: lineId(l), proposed: true, amount_only: false, signals: ["invoice_number" as const],
  amount_relation: "equal" as const, multiple_candidates: false, source_review_required: false, fx: null, ...over,
});
const workspace = (lines: ReconcileLine[], invoices: ReconcileInvoice[]): ReconcileWorkspace => ({
  workpackage_id: WP, lines, invoices, coverage: [], blockers: [], line_marks: ["private", "fee", "own_transfer", "tax", "cash", "salary", "other"],
  open: {}, counts: { lines: {}, invoices: {}, open_lines: lines.length }, learned_names: [], fx_tolerance: null, engine_version: "1.4.0",
  config_hash: "x", scope: { workpackage_id: WP, accounts: ["11112223333444455556666"], period_start: "2026-04-01", period_end: "2026-04-30", revision: 1, updated_at: "" },
});

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

function page(ws: ReconcileWorkspace) {
  const onWorkspace = vi.fn();
  render(<ReconcilePairing ws={ws} readOnly={false} onWorkspace={onWorkspace} reload={() => {}} />);
  return onWorkspace;
}

// --- exact money and the rules of a pairing -------------------------------------------------------------------------------

describe("money and the pairing rules computed before sending", () => {
  it("adds canonical amounts exactly and reads what a person types in the chosen language", async () => {
    expect(canonical(parseCanonical("0.10")! + parseCanonical("0.20")!)).toBe("0.30");
    expect(parseCanonical("1,5")).toBeNull(); // a guessed separator is never accepted
    expect(canonical(parseInput("12,345.67")!)).toBe("12345.67");
    await setLanguage("hu");
    expect(canonical(parseInput("12 345,67")!)).toBe("12345.67");
    expect(display(parseCanonical("-1234.5"), "HUF")).toBe("\u22121\u00a0234,50\u00a0HUF");
  });

  it("settles instalments without a reason and asks for one when a rest is left", () => {
    const plan = planPairing([line(1, { amount: "40.00", rest: "40.00" }), line(2, { amount: "60.00", rest: "60.00" })], [invoice(1)]);
    expect(plan.ok && !plan.needsReason && plan.pairs.map((p) => canonical(p.amount!))).toEqual(["40.00", "60.00"]);
    const split = planPairing([line(1, { amount: "40.00", rest: "40.00" })], [invoice(1)]);
    expect(split.ok && split.needsReason).toBe(true);
    expect(planPairing([line(1), line(2)], [invoice(1), invoice(2)])).toEqual({ ok: false, why: "many_to_many" });
    expect(planPairing([line(1, { state: "marked" })], [invoice(1)])).toEqual({ ok: false, why: "line_marked" });
  });

  it("pairs another currency only one to one, in whole, when the card's conversion relates them", () => {
    const card = line(1, { amount: "6700.00", rest: "6700.00", candidates: [candidate(1, 1, { amount_relation: "fx_outside" })] });
    const usd = invoice(1, { currency: "USD", amount: "20.00", rest: "20.00" });
    const plan = planPairing([card], [usd]);
    expect(plan.ok && plan.converted && plan.needsReason).toBe(true);
    expect(plan.ok && toRequest(plan.pairs)).toEqual([{ invoice_doc_id: usd.id, line_id: card.id }]);
    expect(planPairing([line(2)], [usd])).toEqual({ ok: false, why: "currency" });
  });

  it("refuses amounts over what a side has left", () => {
    expect(check([{ line: line(1), invoice: invoice(1), amount: parseCanonical("120.00") }])).toEqual({ ok: false, why: "line_settled" });
  });
});

// --- the two lists ---------------------------------------------------------------------------------------------------------

describe("the two-list pairing page", () => {
  it("puts the selected line's candidates at the top of the invoice list with what ties them", () => {
    page(workspace([line(1, { state: "proposed", candidates: [candidate(1, 2)] })], [invoice(1), invoice(2)]));
    const candidates = screen.getByText("Candidates of the selected line").nextElementSibling as HTMLElement;
    expect(within(candidates).getByText(/Example Supplier 2/)).toBeTruthy();
    expect(within(candidates).getByText("invoice number")).toBeTruthy();
    expect(within(candidates).queryByText(/Example Supplier 1 ·/)).toBeNull();
  });

  it("pairs an exact selection at once, without asking for amounts or a reason", async () => {
    const allocate = vi.spyOn(api, "reconcileAllocate").mockResolvedValue(workspace([], []));
    const done = page(workspace([line(1, { state: "proposed", candidates: [candidate(1, 1)] })], [invoice(1)]));
    fireEvent.click(screen.getByRole("checkbox", { name: /Select the invoice Example Supplier 1/ }));
    expect(screen.getByText(/Difference/).textContent).toContain("0.00");
    fireEvent.click(screen.getByRole("button", { name: /^Pair/ }));
    await waitFor(() => expect(allocate).toHaveBeenCalledWith(WP, [{ invoice_doc_id: invId(1), line_id: lineId(1), line_amount: "100.00" }]));
    expect(done).toHaveBeenCalled();
  });

  it("asks for a reason when the pairing leaves a rest, and sends the amount", async () => {
    const allocate = vi.spyOn(api, "reconcileAllocate").mockResolvedValue(workspace([], []));
    page(workspace([line(1, { amount: "40.00", rest: "40.00" })], [invoice(1)]));
    fireEvent.click(screen.getByRole("checkbox", { name: /Select the invoice Example Supplier 1/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Pair/ }));
    const save = screen.getByRole("button", { name: "Save the pairing" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: /Reason/ }), { target: { value: "first instalment" } });
    fireEvent.click(save);
    await waitFor(() => expect(allocate).toHaveBeenCalledWith(WP, [{ invoice_doc_id: invId(1), line_id: lineId(1), line_amount: "40.00" }], "first instalment"));
  });

  it("marks several selected lines as needing no invoice in one step", async () => {
    const mark = vi.spyOn(api, "reconcileMark").mockResolvedValue(workspace([], []));
    page(workspace([line(1), line(2), line(3)], []));
    fireEvent.click(screen.getByRole("checkbox", { name: /Select the line Example Supplier 2/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Needs no invoice/ }));
    fireEvent.click(screen.getByRole("radio", { name: "Bank fee or interest" }));
    fireEvent.click(screen.getByRole("button", { name: "Save for 2 lines" }));
    await waitFor(() => expect(mark).toHaveBeenCalledWith(WP, [lineId(1), lineId(2)], "fee", undefined));
  });

  it("rejects a candidate with a reason", async () => {
    const reject = vi.spyOn(api, "reconcileReject").mockResolvedValue(workspace([], []));
    page(workspace([line(1, { state: "proposed", candidates: [candidate(1, 1)] })], [invoice(1)]));
    fireEvent.click(screen.getByRole("checkbox", { name: /Select the invoice Example Supplier 1/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Not this one/ }));
    fireEvent.change(screen.getByRole("textbox", { name: /Why is this invoice not paid/ }), { target: { value: "paid in cash" } });
    fireEvent.click(screen.getByRole("button", { name: "Save the rejection" }));
    await waitFor(() => expect(reject).toHaveBeenCalledWith(WP, invId(1), lineId(1), "paid in cash"));
  });

  it("undoes an allocation and a confirmation from the review page from the line's details", async () => {
    const revoke = vi.spyOn(api, "reconcileRevoke").mockResolvedValue(workspace([], []));
    const share = (allocation_id: number | null, n: number) => ({ invoice_id: invId(n), line_id: lineId(1), line_amount: "50.00", invoice_amount: "50.00", allocation_id, workpackage_id: WP });
    page(workspace([line(1, { state: "allocated", allocated: "100.00", rest: "0.00", allocations: [share(7, 1), share(null, 2)] })], [invoice(1), invoice(2)]));
    fireEvent.click(screen.getByRole("button", { name: /All/ }));
    const undo = screen.getAllByRole("button", { name: "Undo" });
    fireEvent.click(undo[0]);
    await waitFor(() => expect(revoke).toHaveBeenCalledWith(WP, "allocation", "7"));
    fireEvent.click(screen.getAllByRole("button", { name: "Undo" })[1]);
    await waitFor(() => expect(revoke).toHaveBeenCalledWith(WP, "decision", `${invId(2)}|${lineId(1)}`));
  });

  it("works from the keyboard: the arrows move, a digit picks a candidate, Enter pairs", async () => {
    const allocate = vi.spyOn(api, "reconcileAllocate").mockResolvedValue(workspace([], []));
    page(workspace([line(1), line(2, { state: "proposed", candidates: [candidate(2, 2)] })], [invoice(1), invoice(2)]));
    act(() => { fireEvent.keyDown(window, { key: "ArrowDown" }); });
    act(() => { fireEvent.keyDown(window, { key: "1" }); });
    act(() => { fireEvent.keyDown(window, { key: "Enter" }); });
    await waitFor(() => expect(allocate).toHaveBeenCalledWith(WP, [{ invoice_doc_id: invId(2), line_id: lineId(2), line_amount: "100.00" }]));
  });

  it("keeps the selection and reloads when someone decided meanwhile", async () => {
    const { ApiError } = await import("../../api");
    vi.spyOn(api, "reconcileAllocate").mockRejectedValue(new ApiError(409, "revision_conflict", "conflict"));
    const reload = vi.fn();
    render(<ReconcilePairing ws={workspace([line(1, { state: "proposed", candidates: [candidate(1, 1)] })], [invoice(1)])} readOnly={false} onWorkspace={() => {}} reload={reload} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /Select the invoice Example Supplier 1/ }));
    fireEvent.click(screen.getByRole("button", { name: /^Pair/ }));
    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(screen.getByRole("alert").textContent).toMatch(/Someone decided meanwhile/);
    expect((screen.getByRole("checkbox", { name: /Select the invoice Example Supplier 1/ }) as HTMLInputElement).checked).toBe(true);
  });
});

// --- the package page ------------------------------------------------------------------------------------------------------

describe("a reconciliation package's page", () => {
  it("shows its own stages and opens at the pairing", async () => {
    const view = {
      workpackage: { id: WP, name: "April", source_kind: "reconcile", source_ref: "2026-04-01..2026-04-30", revision: 1, status: "active",
        created_at: "", updated_at: "", items: [], assignment: null, owner: null },
      readiness: { workpackage_id: WP, ready: true, blockers: [], warnings: [], counts: { items: 0 }, budget: {}, assignment_revision: 0, input_hash: "" },
      next: { code: "reconcile_pair", label: "Pairing: 1 open lines", stage: "review", params: { n: 1 } }, last_run: null, runs: 0,
      reconcile: { scope: workspace([], []).scope, counts: { lines: { open: 1 }, invoices: {}, open_lines: 1 }, coverage: [] },
    } as unknown as WorkpackageView;
    vi.spyOn(api, "workpackage").mockResolvedValue(view);
    vi.spyOn(api, "users").mockResolvedValue({ users: [] });
    vi.spyOn(api, "reconcileWorkspace").mockResolvedValue(workspace([line(1)], [invoice(1)]));
    render(<WorkpackageDetail route={{ view: "workpackages", wpId: WP }} wpId={WP} />);
    expect(await screen.findByRole("tab", { name: /Preparation/ })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Pairing/ }).getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByRole("region", { name: "Statement lines" })).toBeTruthy();
    expect(stepLabel("reconcile_pair", { n: 3 }, "")).toBe("Pairing: 3 open lines");
  });
});

// --- every new label has a Hungarian translation ----------------------------------------------------------------------------

describe("the Hungarian interface", () => {
  it("has a translation for every English label of the reconciliation pages", () => {
    const sources = import.meta.glob<string>(["./*.tsx", "./*.ts", "!./*.test.tsx"], { eager: true, query: "?raw", import: "default" });
    const keys = new Set<string>();
    for (const src of Object.values(sources)) {
      for (const m of src.matchAll(/\bt\(\s*"((?:[^"\\]|\\.)*)"/g)) keys.add(JSON.parse(`"${m[1]}"`));
      for (const block of src.matchAll(/tmap\(\{([\s\S]*?)\}\)/g)) for (const m of block[1].matchAll(/:\s*"((?:[^"\\]|\\.)*)"/g)) keys.add(JSON.parse(`"${m[1]}"`));
    }
    const missing = [...keys].filter((k) => !(k in (hungarian as Record<string, string>)));
    expect(keys.size).toBeGreaterThan(100);
    expect(missing).toEqual([]);
  });
});
