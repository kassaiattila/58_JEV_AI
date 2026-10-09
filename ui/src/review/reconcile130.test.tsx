// 130: a forint card line and a dollar invoice on the review page: the amount converted at the MNB rate of the issue
// date, the rate and the line's deviation from it; outside the band the row is marked, without a stored rate a note
// says why the amounts could not be compared. Expectations avoid Hungarian letters for the language guard.
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { setActor, type ItemResult, type ReconcilePair } from "../api";
import { setLanguage } from "../i18n";
import { ReconcilePanel } from "./ReconcilePanel";

const INVOICE = "a".repeat(64);
const STATEMENT = "b".repeat(64);
const LINE = `${STATEMENT.slice(0, 16)}:0a1b2c3d4e5f:0`;
const pair = (over: Partial<ReconcilePair> = {}): ReconcilePair => ({
  invoice_doc_id: INVOICE, statement_doc_id: STATEMENT, line_id: LINE, side: "statement",
  invoice: { number: "EC-1001", supplier: "Example Cloud Inc.", amount: "20.00", currency: "USD", issue_date: "2026-04-01",
    due_date: null, file: "invoice.pdf" },
  line: { booking_date: "2026-04-03", direction: "debit", amount: "6700.00", currency: "HUF", counterparty_name: "EXAMPLE CLOUD",
    counterparty_account: null, memo: null, description: "EXAMPLE CLOUD SUBSCRIPTION", file: "card.pdf", verified: true },
  signals: ["supplier_name"], amount_relation: "fx_within",
  fx: { rate: "326.18", rate_day: "2026-04-01", source: "mnb", converted: "6523.60", deviation: "0.0270" },
  source_review_required: false, reason_id: 7, decision: null, decided_by: null, decided_at: null, note: null,
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

function convertedRow(): HTMLElement | undefined {
  return within(screen.getByRole("table")).getAllByRole("row").find((r) => r.textContent?.includes("MNB"));
}

describe("card payments through the MNB rate (130)", () => {
  it("shows the converted amount, the rate and the deviation", () => {
    render(<ReconcilePanel result={result([pair()])} readOnly={false} onDecided={() => {}} />);
    expect(screen.getByText(/sz.m.tott .sszeg, a sz.ll.t. neve/)).toBeTruthy();
    const row = convertedRow();
    expect(row?.textContent).toContain("+2,7%");
    expect(row?.textContent).toContain("6523,60 HUF");
    expect(row?.textContent).toContain("326,18 Ft/USD, 2026-04-01");
    expect(row?.className).toBe("");
  });

  it("marks a line outside the band", () => {
    render(<ReconcilePanel result={result([pair({ amount_relation: "fx_outside", fx: { rate: "326.18", rate_day: "2026-04-01",
      source: "mnb", converted: "6523.60", deviation: "0.0730" } })])} readOnly={false} onDecided={() => {}} />);
    expect(convertedRow()?.className).toBe("differs");
    expect(convertedRow()?.textContent).toContain("+7,3%");
    expect(screen.queryByText(/sz.m.tott .sszeg,/)).toBeNull();
  });

  it("says when no rate is stored for the issue date", () => {
    render(<ReconcilePanel result={result([pair({ amount_relation: "no_rate", fx: null })])} readOnly={false} onDecided={() => {}} />);
    expect(screen.getByText(/MNB-.rfolyam, ez.rt az .sszegek nem hasonl.that.k/)).toBeTruthy();
    expect(convertedRow()).toBeUndefined();
  });
});
