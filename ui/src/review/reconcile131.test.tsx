// 131: a line with exactly the invoice's amount but nothing else tying them stands on the review page for a person to
// decide, with a note; the payment method and a name learnt from an earlier confirmed pair are named as what ties a
// pair. Expectations avoid Hungarian letters for the language guard.
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { setActor, type ItemResult, type ReconcilePair } from "../api";
import { setLanguage } from "../i18n";
import { reasonText } from "../labels";
import { ReconcilePanel } from "./ReconcilePanel";

const INVOICE = "a".repeat(64);
const STATEMENT = "b".repeat(64);
const LINE = `${STATEMENT.slice(0, 16)}:0a1b2c3d4e5f:0`;
const pair = (over: Partial<ReconcilePair> = {}): ReconcilePair => ({
  invoice_doc_id: INVOICE, statement_doc_id: STATEMENT, line_id: LINE, side: "invoice",
  invoice: { number: "TEL-04", supplier: "Example Telecom Nyrt.", amount: "100.00", currency: "HUF", issue_date: "2026-04-01",
    due_date: "2026-04-15", file: "invoice.pdf" },
  line: { booking_date: "2026-04-10", direction: "debit", amount: "100.00", currency: "HUF", counterparty_name: "EXAMPLETEL*111 BUDAPEST",
    counterparty_account: null, memo: null, description: "VASARLAS", file: "card.pdf", verified: true },
  signals: [], amount_relation: "equal", fx: null, amount_only: true,
  source_review_required: false, reason_id: 7, decision: null, decided_by: null, decided_at: null, note: null,
  other_doc_id: STATEMENT, other_file: "card.pdf", other_run_id: "run-000000000001", other_item_id: STATEMENT,
  other_workpackage_id: "wp-000000000001",
  ...over,
});
const result = (pairs: ReconcilePair[]): ItemResult => ({
  run_id: "run-000000000002", item_id: INVOICE, extraction: null, effective: {}, open_reasons: [], earlier_open_reasons: [],
  provenance: {}, source: null, kinds: {}, reconcile: pairs,
  correction: { run_id: "run-000000000002", item_id: INVOICE, revision: 0, fields: {}, actor: null, note: null, created_at: null },
} as unknown as ItemResult);

beforeEach(async () => { await setLanguage("hu"); setActor("Synthetic reviewer"); });

describe("pairs tied by the amount alone, the payment method or a learnt name (131)", () => {
  it("asks a person to decide a pair that only the amount ties", () => {
    render(<ReconcilePanel result={result([pair()])} readOnly={false} onDecided={() => {}} />);
    expect(screen.getByText(/Csak az .sszeg .s a d.tumok illenek/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ez fizette" })).toBeTruthy();
  });

  it("names the payment method and the learnt name as what ties a pair", () => {
    render(<ReconcilePanel result={result([pair({ amount_only: false, signals: ["payment_channel", "learned_name"] })])}
      readOnly={false} onDecided={() => {}} />);
    expect(screen.getByText(/a fizet.si m.d \(csekkes sz.mla/)).toBeTruthy();
    expect(screen.getByText(/egy kor.bban meger.s.tett fizet.s neve/)).toBeTruthy();
    expect(screen.queryByText(/Csak az .sszeg .s a d.tumok illenek/)).toBeNull();
  });

  it("labels the to-do of a pair that only the amount ties", () => {
    expect(reasonText(`reconcile:amount_only:${INVOICE.slice(0, 16)}:${LINE}`)).toMatch(/^Eld.ntend. lehets.ges kifizet.s/);
  });
});
