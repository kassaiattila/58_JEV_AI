// 174 (review 160 M-3, M-4): two pairs the service accepts that the page refused by hand. A line set aside for its
// wording (a fee, interest or repayment word in its memo) can be paired by hand, as the service allows; a line set
// aside for another reason cannot. A card purchase compared on its original amount (137) pairs in whole: an equal
// original amount needs no reason, a different one does. Synthetic lines and invoices only.
import { describe, expect, it } from "vitest";
import type { ReconcileCandidate, ReconcileInvoice, ReconcileLine, ReconcileRelation } from "../api";
import { planPairing } from "./pairing";

const STMT = "a".repeat(64);
const LINE = `${STMT.slice(0, 16)}:000000000001:0`;
const INV = "e".repeat(64);

const candidate = (relation: ReconcileRelation): ReconcileCandidate => ({
  invoice_id: INV, line_id: LINE, proposed: false, amount_only: false, signals: ["supplier_name"],
  amount_relation: relation, multiple_candidates: false, source_review_required: false, fx: null, strength: 60,
});
const line = (over: Partial<ReconcileLine> = {}): ReconcileLine => ({
  id: LINE, statement_id: STMT, account: "111122233333444455556666", statement_type: "bank_account", currency: "HUF",
  booking_date: "2026-04-20", direction: "debit", amount: "12700.00", counterparty_name: "EXAMPLE AGENCY",
  counterparty_account: null, description: "Transfer", memo: "INV-777 jutalek szamla", original_amount: null,
  original_currency: null, state: "excluded", excluded_reason: "payment_kind_review", allocated: "0", rest: "12700.00",
  mark: null, allocations: [], rejected: [], candidates: [], statement_verified: true, file: "statement.json",
  partner: "example agency", earlier_marks: [], ...over,
});
const invoice = (over: Partial<ReconcileInvoice> = {}): ReconcileInvoice => ({
  id: INV, doc_type: "invoice_hu", number: "INV-777", supplier_name: "Example Agency Kft.", amount: "12700.00",
  currency: "HUF", issue_date: "2026-04-01", due_date: "2026-04-15", payment_method: null, file: "INV-777.pdf",
  state: "no_payment_found", allocated: "0", rest: "12700.00", allocations: [], candidates: [], source: "approved", ...over,
});

describe("174 M-3 a line set aside for its wording", () => {
  it("pairs by hand", () => {
    expect(planPairing([line()], [invoice()])).toMatchObject({ ok: true, needsReason: false, exact: true });
  });

  it("but a line set aside for another reason does not", () => {
    expect(planPairing([line({ excluded_reason: "own_account_transfer" })], [invoice()])).toEqual({ ok: false, why: "line_excluded" });
    expect(planPairing([line({ excluded_reason: null })], [invoice()])).toEqual({ ok: false, why: "line_excluded" });
  });
});

describe("174 M-4 a card purchase compared on its original amount", () => {
  const card = (relation: ReconcileRelation, over: Partial<ReconcileLine> = {}) => line({
    statement_type: "card", amount: "7291.00", rest: "7291.00", original_amount: "20.00", original_currency: "USD",
    state: "open", excluded_reason: null, memo: null, candidates: [candidate(relation)], ...over,
  });
  const usd = invoice({ doc_type: "invoice_foreign", amount: "20.00", rest: "20.00", currency: "USD" });

  it("pairs in whole without a reason when the original amount is equal", () => {
    expect(planPairing([card("equal")], [usd])).toMatchObject({ ok: true, converted: true, needsReason: false, exact: true });
  });

  it("asks for a reason when it differs", () => {
    expect(planPairing([card("different")], [usd])).toMatchObject({ ok: true, converted: true, needsReason: true, exact: false });
  });

  it("refuses a side already paired in part", () => {
    expect(planPairing([card("equal", { allocated: "1000.00", rest: "6291.00" })], [usd])).toEqual({ ok: false, why: "currency" });
  });
});
