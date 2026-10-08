// 129: a proposed invoice <-> statement line pair on the review page: the line and the invoice side by side, the
// details that tie them, and the two decisions (a rejection needs a reason). Expectations avoid Hungarian letters for
// the language guard.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type ItemResult, type ReconcilePair } from "../api";
import { setLanguage } from "../i18n";
import { reasonText } from "../labels";
import { ReconcilePanel } from "./ReconcilePanel";

const INVOICE = "a".repeat(64);
const STATEMENT = "b".repeat(64);
const LINE = `${STATEMENT.slice(0, 16)}:0a1b2c3d4e5f:0`;
const pair = (over: Partial<ReconcilePair> = {}): ReconcilePair => ({
  invoice_doc_id: INVOICE, statement_doc_id: STATEMENT, line_id: LINE, side: "statement",
  invoice: { number: "INV-0001", supplier: "Example Supplier Kft.", amount: "100.50", currency: "HUF", issue_date: "2026-04-01",
    due_date: "2026-04-15", file: "invoice.pdf" },
  line: { booking_date: "2026-04-10", direction: "debit", amount: "100.50", currency: "HUF", counterparty_name: "Example Supplier",
    counterparty_account: null, memo: "INV-0001", description: null, file: "statement.pdf", verified: true },
  signals: ["invoice_number", "supplier_name"], amount_relation: "equal", source_review_required: false,
  reason_id: 7, decision: null, decided_by: null, decided_at: null, note: null,
  other_doc_id: INVOICE, other_file: "invoice.pdf", other_run_id: "run-000000000001", other_item_id: INVOICE,
  other_workpackage_id: "wp-000000000001",
  ...over,
});
const result = (pairs: ReconcilePair[]): ItemResult => ({
  run_id: "run-000000000002", item_id: STATEMENT, extraction: null, effective: {}, open_reasons: [], earlier_open_reasons: [],
  provenance: {}, source: null, kinds: {}, reconcile: pairs,
  correction: { run_id: "run-000000000002", item_id: STATEMENT, revision: 0, fields: {}, actor: null, note: null, created_at: null },
} as unknown as ItemResult);

beforeEach(async () => { await setLanguage("hu"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

describe("proposed payments (129)", () => {
  it("names the to-do", () => {
    expect(reasonText(`reconcile:proposed:${INVOICE.slice(0, 16)}:${LINE}`)).toMatch(/Lehets.ges kifizet.s/);
  });

  it("shows the line and the invoice side by side, what ties them, and a link to the other document", () => {
    render(<ReconcilePanel result={result([pair()])} readOnly={false} onDecided={() => {}} />);
    expect(screen.getByText(/kifizethetett egy sz.ml.t/)).toBeTruthy();
    expect(screen.getByText(/azonos .sszeg, sz.mlasz.m a k.zlem.nyben, a sz.ll.t. neve/)).toBeTruthy();
    const table = screen.getByRole("table");
    const amount = within(table).getAllByRole("row").find((r) => r.textContent?.includes("100,50 HUF"));
    expect(amount?.className).toBe("");
    expect(screen.getByRole("link", { name: "invoice.pdf" }).getAttribute("href")).toBe(`#/workpackages/wp-000000000001/review/${INVOICE}`);
    expect(screen.queryByText(/egyenlegei nem egyeznek/)).toBeNull();
  });

  it("asks for a look at the source when the statement's balances do not check out", () => {
    render(<ReconcilePanel result={result([pair({ source_review_required: true })])} readOnly={false} onDecided={() => {}} />);
    expect(screen.getByText(/egyenlegei nem egyeznek/)).toBeTruthy();
  });

  it("confirms a pair", async () => {
    const decide = vi.spyOn(api, "decideReconcile").mockResolvedValue(result([]));
    const done = vi.fn();
    render(<ReconcilePanel result={result([pair()])} readOnly={false} onDecided={done} />);
    const buttons = within(screen.getByRole("group")).getAllByRole("button");
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[0]); // this line paid it
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(decide).toHaveBeenCalledWith("run-000000000002", STATEMENT, INVOICE, LINE, "paid_by", undefined);
  });

  it("rejects a pair only with a reason", async () => {
    const decide = vi.spyOn(api, "decideReconcile").mockResolvedValue(result([]));
    render(<ReconcilePanel result={result([pair()])} readOnly={false} onDecided={() => {}} />);
    fireEvent.click(within(screen.getByRole("group")).getAllByRole("button")[1]); // not this one
    const save = screen.getByRole("button", { name: /ment.se/ });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "paid in cash" } });
    fireEvent.click(save);
    await waitFor(() => expect(decide).toHaveBeenCalledWith("run-000000000002", STATEMENT, INVOICE, LINE, "not_this", "paid in cash"));
  });

  it("shows a decision, and no buttons on an approved run", () => {
    render(<ReconcilePanel result={result([pair({ decision: "not_this", note: "refund", decided_by: "Anna", reason_id: null })])} readOnly onDecided={() => {}} />);
    expect(screen.getByText(/Anna/).textContent).toMatch(/nem ez a p.r .* refund/);
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("shows nothing without a proposed pair", () => {
    const { container } = render(<ReconcilePanel result={result([])} readOnly={false} onDecided={() => {}} />);
    expect(container.textContent).toBe("");
  });
});
