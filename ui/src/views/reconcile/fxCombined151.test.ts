// 151 (DECISIONS 151): one forint bank line paying two franc invoices together. The plan takes both in whole and leaves
// the line's split to the service; a proposed group needs no reason, a group outside the band does, and a group without
// a rate, of two currencies or with a side already paired cannot be planned. Synthetic lines and invoices only.
import { describe, expect, it } from "vitest";
import type { ReconcileCandidate, ReconcileInvoice, ReconcileLine, ReconcileRelation } from "../../api";
import { planPairing, toRequest } from "./pairing";

const STMT = "a".repeat(64);
const LINE = `${STMT.slice(0, 16)}:000000000001:0`;
const IDS = ["1", "2"].map((n) => n.repeat(64));

const candidate = (id: string, relation: ReconcileRelation): ReconcileCandidate => ({
  invoice_id: id, line_id: LINE, proposed: relation === "combined", amount_only: false, signals: ["invoice_number"],
  amount_relation: relation, multiple_candidates: false, source_review_required: false, fx: null, strength: 90,
  combined: relation === "combined" ? IDS : null,
});
const line = (relation: ReconcileRelation, over: Partial<ReconcileLine> = {}): ReconcileLine => ({
  id: LINE, statement_id: STMT, account: "111122233333444455556666", statement_type: "bank_account", currency: "HUF",
  booking_date: "2026-04-20", direction: "credit", amount: "2812320.00", counterparty_name: "NORTHWIND TRADING",
  counterparty_account: null, description: "Incoming transfer", memo: "INV-0002 INV-0003", original_amount: null,
  original_currency: null, state: "proposed", excluded_reason: null, allocated: "0", rest: "2812320.00", mark: null,
  allocations: [], rejected: [], candidates: IDS.map((id) => candidate(id, relation)), statement_verified: true,
  file: "statement.json", partner: "northwind trading", earlier_marks: [], ...over,
});
const invoice = (id: string, number: string, amount: string, over: Partial<ReconcileInvoice> = {}): ReconcileInvoice => ({
  id, doc_type: "invoice_out", number, supplier_name: "Sample Own Company Kft.", amount, currency: "CHF",
  issue_date: "2026-04-01", due_date: "2026-05-01", payment_method: null, file: `${number}.pdf`, state: "proposed",
  allocated: "0", rest: amount, allocations: [], candidates: [], source: "approved", ...over,
});
const INVOICES = [invoice(IDS[0], "INV-0002", "5000.00"), invoice(IDS[1], "INV-0003", "2000.00")];

describe("151 a forint line paying two invoices of another currency", () => {
  it("plans the proposed group in whole, with no reason and no amounts", () => {
    const plan = planPairing([line("combined")], INVOICES);
    expect(plan).toMatchObject({ ok: true, converted: true, needsReason: false, exact: true });
    if (!plan.ok) throw new Error("planned");
    expect(toRequest(plan.pairs)).toEqual(IDS.map((id) => ({ invoice_doc_id: id, line_id: LINE })));
  });

  it("asks for a reason outside the band", () => {
    expect(planPairing([line("fx_outside")], INVOICES)).toMatchObject({ ok: true, needsReason: true, exact: false });
  });

  it("refuses a group without a rate, of two currencies, or with a side already paired", () => {
    expect(planPairing([line("no_rate")], INVOICES)).toEqual({ ok: false, why: "currency" });
    expect(planPairing([line("combined")], [INVOICES[0], { ...INVOICES[1], currency: "USD" }])).toEqual({ ok: false, why: "currency" });
    expect(planPairing([line("combined")], [INVOICES[0], { ...INVOICES[1], allocated: "100.00", rest: "1900.00" }]))
      .toEqual({ ok: false, why: "currency" });
  });
});
