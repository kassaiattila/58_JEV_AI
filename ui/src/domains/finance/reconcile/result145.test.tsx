// 145 (backlog F-reconciliation E3b; DECISIONS 131, 132, 145): the reconciliation package's Result stage - what blocks
// the approval and accepting a command-line source, the approval of the summary the person saw, the approved version
// with its download and reopening with a reason, the earlier versions, and the locked pairing. Synthetic data only;
// the service is spied on.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor } from "../../../api";
import type { ReconcileStatement, ReconcileStatementCurrent, ReconcileVersionMeta, ReconcileWorkspace } from "../api";
import { setLanguage } from "../../../i18n";
import { ReconcileResult } from "./ReconcileResult";

const WP = "wp-0000000000ff";
const DOC = "d".repeat(64);
const FP = "f".repeat(64);

const statement: ReconcileStatement = {
  format: 1, package: { id: WP, name: "April" }, party: "Example Home", period: ["2026-04-01", "2026-04-30"],
  accounts: ["111122233333444455556666"],
  invoices: [
    { id: "a".repeat(64), number: "INV-0001", supplier_name: "Example Supplier Kft.", supplier_tax_id: "12345678-2-41",
      issue_date: "2026-04-01", fulfillment_date: null, due_date: "2026-04-15", amount: "100.00", currency: "HUF",
      payment_method: "transfer", file: "inv.pdf", result: "paid", engine_state: "confirmed", allocated: "100.00", rest: "0.00",
      paid_on: "2026-04-20", days_from_due: 5, overdue_days: null, double_payment: false, credited_by: null, other_party: null,
      source: "approved", paid_by: [{ line_id: "l1", line_amount: "100.00", invoice_amount: "100.00", booking_date: "2026-04-20", account: "A", in_scope: true }] },
    { id: "b".repeat(64), number: "INV-0002", supplier_name: "Other Supplier Kft.", supplier_tax_id: null, issue_date: "2026-04-02",
      fulfillment_date: null, due_date: "2026-04-16", amount: "300.00", currency: "HUF", payment_method: null, file: null,
      result: "no_payment_found", engine_state: "no_payment_found", allocated: "0", rest: "300.00", paid_on: null,
      days_from_due: null, overdue_days: 14, double_payment: false, credited_by: null, other_party: null, source: "approved", paid_by: [] },
  ],
  lines: [
    { id: "l1", account: "A", currency: "HUF", booking_date: "2026-04-20", value_date: null, direction: "debit", amount: "100.00",
      counterparty_name: "Example Supplier", counterparty_account: null, memo: "INV-0001", description: null, file: "s.json",
      statement_verified: true, result: "paired", engine_state: "allocated", reason: null, note: null, allocated: "100.00", rest: "0.00",
      pays: [{ invoice_id: "a".repeat(64), number: "INV-0001", supplier_name: "Example Supplier Kft.", line_amount: "100.00", invoice_amount: "100.00" }] },
    { id: "l2", account: "A", currency: "HUF", booking_date: "2026-04-21", value_date: null, direction: "debit", amount: "15.00",
      counterparty_name: "Bank", counterparty_account: null, memo: "fee", description: null, file: "s.json", statement_verified: true,
      result: "needs_no_invoice", engine_state: "marked", reason: "fee", note: null, allocated: "0", rest: "15.00", pays: [] },
    { id: "l3", account: "A", currency: "HUF", booking_date: "2026-04-22", value_date: null, direction: "debit", amount: "70.00",
      counterparty_name: "Someone", counterparty_account: null, memo: "?", description: null, file: "s.json", statement_verified: true,
      result: "open", engine_state: "open", reason: null, note: null, allocated: "0", rest: "70.00", pays: [] },
  ],
  warnings: [{ code: "month_without_statement", account: "A", month: "2026-05" }],
  counts: { invoices: { no_payment_found: 1, paid: 1 }, lines: { needs_no_invoice: 1, open: 1, paired: 1 }, open_lines: 1 },
};
const v1: ReconcileVersionMeta = {
  version: 1, fingerprint: FP, approved_by: "Synthetic reviewer", approved_at: "2026-10-11T10:00:00+00:00",
  reopened_by: null, reopened_at: null, reopen_note: null,
};
const draft = (over: Partial<ReconcileStatementCurrent> = {}): ReconcileStatementCurrent => ({
  statement, fingerprint: FP, blockers: [], warnings: statement.warnings, approval: { active: null, versions: [] }, ...over,
});
const ws = { workpackage_id: WP, blockers: [], decision_state: [[0]] } as unknown as ReconcileWorkspace;

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

function result(archived = false) {
  const onChanged = vi.fn();
  const reloadWorkspace = vi.fn();
  render(<ReconcileResult ws={ws} archived={archived} onChanged={onChanged} reloadWorkspace={reloadWorkspace} />);
  return { onChanged, reloadWorkspace };
}

describe("the Result stage of a reconciliation package (145)", () => {
  it("shows the summary, its warnings and the draft's download, and approves what the person saw", async () => {
    vi.spyOn(api, "reconcileStatement").mockResolvedValue(draft());
    const approve = vi.spyOn(api, "reconcileApprove").mockResolvedValue(draft({ approval: { active: v1, versions: [v1] } }));
    vi.spyOn(api, "reconcileStatementVersion").mockResolvedValue({ ...v1, statement });
    const { reloadWorkspace, onChanged } = result();
    expect(await screen.findByText("Nothing blocks the approval.")).toBeTruthy();
    expect(screen.getByText("No statement for 2026-05: A")).toBeTruthy();
    const invoices = screen.getByRole("region", { name: "Invoices" });
    expect(within(invoices).getByText("No payment in the covered period")).toBeTruthy();
    expect(within(invoices).getByText("14 overdue")).toBeTruthy();
    const lines = screen.getByRole("region", { name: "Statement lines" });
    expect(within(lines).getByText("Bank fee or interest")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Download the draft/ }).getAttribute("href")).toBe(`/api/workpackages/${WP}/reconcile/statement.xlsx`);
    const button = screen.getByRole("button", { name: "Approve the reconciliation (1 open lines listed)" });
    fireEvent.click(button); // the first click asks for a confirmation
    expect(approve).not.toHaveBeenCalled();
    fireEvent.click(button);
    await waitFor(() => expect(approve).toHaveBeenCalledWith(WP, FP));
    expect(await screen.findByText(/Approved: version 1, by Synthetic reviewer/)).toBeTruthy();
    expect(reloadWorkspace).toHaveBeenCalled();
    expect(onChanged).toHaveBeenCalled();
  });

  it("lists what blocks the approval and accepts the command-line documents as sources", async () => {
    vi.spyOn(api, "reconcileStatement").mockResolvedValue(draft({
      blockers: [{ code: "source_no_run", doc_id: DOC, file: "elmu002.pdf", kind: "invoice" },
        { code: "source_not_approved", doc_id: "e".repeat(64), file: "inv.pdf", kind: "invoice" }],
    }));
    const accept = vi.spyOn(api, "reconcileAcceptSources").mockResolvedValue(draft());
    result();
    expect(await screen.findByText(/Processed on the command line, not in a work package: elmu002.pdf/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /Approve the reconciliation/ }) as HTMLButtonElement).disabled).toBe(true);
    const button = screen.getByRole("button", { name: "Accept 1 command-line documents as sources" });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(accept).toHaveBeenCalledWith(WP, [DOC]));
    expect(await screen.findByText("The documents have been accepted as sources.")).toBeTruthy();
  });

  it("shows the approved version as it was approved, its download, and reopens it with a reason", async () => {
    const earlier = { ...v1, version: 1, reopened_by: "Synthetic reviewer", reopened_at: "2026-10-11T11:00:00+00:00", reopen_note: "late invoice" };
    const v2 = { ...v1, version: 2 };
    vi.spyOn(api, "reconcileStatement").mockResolvedValue(draft({ fingerprint: "0".repeat(64), approval: { active: v2, versions: [v2, earlier] } }));
    vi.spyOn(api, "reconcileStatementVersion").mockResolvedValue({ ...v2, statement });
    const reopen = vi.spyOn(api, "reconcileReopen").mockResolvedValue(draft());
    result();
    expect(await screen.findByText(/Approved: version 2, by Synthetic reviewer/)).toBeTruthy();
    expect(screen.getByText(/The data has changed since the approval/)).toBeTruthy(); // the fingerprints differ
    expect(screen.getByRole("link", { name: /Download version 2/ }).getAttribute("href")).toBe(`/api/workpackages/${WP}/reconcile/statement.xlsx?version=2`);
    const versions = screen.getByRole("region", { name: "Earlier versions" });
    expect(within(versions).getByText(/Version 1: approved by Synthetic reviewer/)).toBeTruthy();
    const button = screen.getByRole("button", { name: "Reopen" });
    expect((button as HTMLButtonElement).disabled).toBe(true); // a reason first
    fireEvent.change(screen.getByLabelText("Reason for reopening"), { target: { value: "a late invoice arrived" } });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(reopen).toHaveBeenCalledWith(WP, "a late invoice arrived"));
  });

  it("offers no approval or reopening on an archived package", async () => {
    vi.spyOn(api, "reconcileStatement").mockResolvedValue(draft());
    result(true);
    expect(await screen.findByText("Nothing blocks the approval.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Approve the reconciliation/ })).toBeNull();
  });
});

describe("the approved package in the header (145)", () => {
  it("names the approved version as the next step and on the Result stage", async () => {
    const { stepLabel } = await import("../../../labels");
    expect(stepLabel("reconcile_approved", { version: 2 }, "Approved: version 2")).toBe("Approved: version 2");
    // 231 (C3a-2): the case page's Summary tab line says the approved version (src/elements/pairingStatus.ts)
  });
});
