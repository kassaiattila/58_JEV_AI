// 145 (backlog F-reconciliation E3b; DECISIONS 131, 132, 145): the reconciliation package's Result stage - what blocks
// the approval and accepting a command-line source, the approval of the summary the person saw, the approved version
// with its download and reopening with a reason, the earlier versions, and the locked pairing. Synthetic data only;
// the service is spied on.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DsPage, type DsRow } from "../../../api";
import type { ReconcileStatement, ReconcileStatementCurrent, ReconcileVersionMeta, ReconcileWorkspace } from "../api";
import { setLanguage } from "../../../i18n";
import { ReconcileResult } from "./ReconcileResult";
import { confirmAction } from "../../../confirm.testutil";

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
// 263 (F3): the statement's two tables are the service's lists (`reconcile_statement_invoices`, `..._lines`)
const listPage = (name: string, rows: DsRow[]): DsPage => ({
  dataset: { name, label: name, scope: ["workpackage_id"], optional_scope: ["version"] },
  columns: name.endsWith("invoices")
    ? [{ key: "number", label: "Invoice number", kind: "text" }, { key: "counterparty", label: "Counterparty", kind: "text" },
       { key: "result", label: "Result", kind: "enum", labels: { paid: "Paid", no_payment_found: "No payment in the covered period" } },
       { key: "days_late", label: "Days late", kind: "number" }]
    : [{ key: "counterparty", label: "Counterparty", kind: "text" }, { key: "result", label: "Result", kind: "enum",
        labels: { paired: "Paired", needs_no_invoice: "Needs no invoice", open: "Open" } }, { key: "pays", label: "Reason or invoice", kind: "text" }],
  rows, total: rows.length, matched: rows.length, offset: 0, limit: 50, facets: {},
} as unknown as DsPage);
const INVOICE_ROWS: DsRow[] = [
  { _key: "a".repeat(64), number: "INV-0001", counterparty: "Example Supplier Kft.", buyer: false, result: "paid", days_late: 5 },
  { _key: "b".repeat(64), number: "INV-0002", counterparty: "Other Supplier Kft.", buyer: false, result: "no_payment_found", days_late: null, overdue_days: 14 },
];
const LINE_ROWS: DsRow[] = [
  { _key: "l1", counterparty: "Example Supplier", result: "paired", pays: "INV-0001" },
  { _key: "l2", counterparty: "Bank", result: "needs_no_invoice", pays: null, reason: "fee", note: null },
  { _key: "l3", counterparty: "Someone", result: "open", pays: null, reason: null, note: null },
];
const lists = (invoices: DsRow[] = INVOICE_ROWS) => vi.spyOn(api, "datasetQuery").mockImplementation(async (name) =>
  listPage(name, name === "reconcile_statement_invoices" ? invoices : LINE_ROWS));

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

function result(archived = false, workspace: ReconcileWorkspace = ws) {
  const onChanged = vi.fn();
  const reloadWorkspace = vi.fn();
  render(<ReconcileResult ws={workspace} archived={archived} onChanged={onChanged} reloadWorkspace={reloadWorkspace} />);
  return { onChanged, reloadWorkspace };
}

describe("the Result stage of a reconciliation package (145)", () => {
  it("shows the summary, its warnings and the draft's download, and approves what the person saw", async () => {
    vi.spyOn(api, "reconcileStatement").mockResolvedValue(draft());
    const approve = vi.spyOn(api, "reconcileApprove").mockResolvedValue(draft({ approval: { active: v1, versions: [v1] } }));
    vi.spyOn(api, "reconcileStatementVersion").mockResolvedValue({ ...v1, statement });
    lists();
    const { reloadWorkspace, onChanged } = result();
    expect(await screen.findByText("Nothing blocks the approval.")).toBeTruthy();
    expect(screen.getByText("No statement for 2026-05: A")).toBeTruthy();
    const invoices = screen.getByRole("region", { name: "Invoices" });
    expect((await within(invoices).findAllByText("No payment in the covered period")).length).toBeGreaterThan(0);  // its group and its cell
    expect(within(invoices).getByText("14 overdue")).toBeTruthy();
    const lines = screen.getByRole("region", { name: "Statement lines" });
    expect(await within(lines).findByText("Bank fee or interest")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Download the draft/ }).getAttribute("href")).toBe(`/api/workpackages/${WP}/reconcile/statement.xlsx`);
    const button = screen.getByRole("button", { name: "Approve the reconciliation (1 open lines listed)" });
    fireEvent.click(button); // the first click asks for a confirmation
    expect(approve).not.toHaveBeenCalled();
    fireEvent.click(confirmAction());
    await waitFor(() => expect(approve).toHaveBeenCalledWith(WP, FP));
    expect(await screen.findByText(/Approved: version 1, by Synthetic reviewer/)).toBeTruthy();
    expect(reloadWorkspace).toHaveBeenCalled();
    expect(onChanged).toHaveBeenCalled();
  });

  it("shows an own party's outgoing invoice by its buyer (U1)", async () => {
    vi.spyOn(api, "reconcileStatement").mockResolvedValue(draft());
    // 263 (F3): the service names the buyer in the invoices' list (`buyer`); the page says so beside it
    lists([INVOICE_ROWS[0], { ...INVOICE_ROWS[1], counterparty: "Example Buyer Zrt.", buyer: true }]);
    result(false);
    const invoices = await screen.findByRole("region", { name: "Invoices" });
    expect(await within(invoices).findByRole("columnheader", { name: /Counterparty/ })).toBeTruthy();
    expect(within(invoices).getByText("Example Buyer Zrt.")).toBeTruthy();
    expect(within(invoices).getByText("· buyer of an outgoing invoice")).toBeTruthy();
    expect(within(invoices).getByText("Example Supplier Kft.")).toBeTruthy();  // an incoming one keeps its supplier
  });

  it("lists what blocks the approval and accepts the command-line documents as sources", async () => {
    vi.spyOn(api, "reconcileStatement").mockResolvedValue(draft({
      blockers: [{ code: "source_no_run", doc_id: DOC, file: "elmu002.pdf", kind: "invoice" },
        { code: "source_not_approved", doc_id: "e".repeat(64), file: "inv.pdf", kind: "invoice" }],
    }));
    const accept = vi.spyOn(api, "reconcileAcceptSources").mockResolvedValue(draft());
    result();
    expect(await screen.findByText(/Processed on the command line, not in a document batch: elmu002.pdf/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /Approve the reconciliation/ }) as HTMLButtonElement).disabled).toBe(true);
    const button = screen.getByRole("button", { name: "Accept 1 command-line documents as sources" });
    fireEvent.click(button);
    fireEvent.click(confirmAction());
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
    fireEvent.click(confirmAction());
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
