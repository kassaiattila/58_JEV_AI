// 153 (review A3): a pairing that no longer fits the amounts of its line or invoice is listed in the package's
// Preparation stage with a revoke button, and its blocker says what it is. Artificial data, no service.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReconcileBlocker, ReconcileLine, ReconcileUnfit, ReconcileWorkspace } from "../../api";
import { blockerText } from "./labels";
import { LineFacts } from "./LineFacts";
import { Unfit } from "./ReconcileStages";

const ROW: ReconcileUnfit = {
  kind: "allocation", ref: "17", reason: "amounts", line_id: "l1", invoice_id: "inv-000000000001", invoice_reason: null,
  category: null, statement_id: "s1", workpackage_id: "wp-1",
  line_amount: "100.00", invoice_amount: "100.00", line_total: "100.00", invoice_total: "60.00", currency: "HUF",
  booking_date: "2026-04-10", direction: "debit", counterparty_name: "Example Supplier", invoice_file: "szamla.pdf", file: null,
};

describe("153 pairings that no longer fit", () => {
  it("are listed with the amounts now and can be revoked", () => {
    const onRevoke = vi.fn();
    render(<Unfit ws={{ unfit: [ROW] } as unknown as ReconcileWorkspace} readOnly={false} busy={false} onRevoke={onRevoke} />);
    expect(screen.getByRole("heading", { name: "Már nem érvényes döntések" })).toBeTruthy();  // 160: marks too
    expect(screen.getByText("kifizetve: szamla.pdf")).toBeTruthy();
    expect(screen.getByText(/számla 60,00/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Visszavonás" }));
    expect(onRevoke).toHaveBeenCalledWith(ROW);
  });

  it("show nothing without such a pairing, and name the blocker", () => {
    const { container } = render(<Unfit ws={{ unfit: [] } as unknown as ReconcileWorkspace} readOnly={false} busy={false} onRevoke={() => {}} />);
    expect(container.textContent).toBe("");
    const b = { code: "allocation_no_longer_fits", doc_id: "inv-000000000001", file: "szamla.pdf", kind: "invoice" } as ReconcileBlocker;
    expect(blockerText(b)).toBe("Egy párosítás már nem fér bele a sora vagy a számlája összegébe: szamla.pdf");
  });
});

// 153 (decision of 2026-10-13, review A4): a line to an account a statement prints but no own party holds stays in the
// pairing, marked on its facts.
describe("153 a payment to an account not registered as own", () => {
  const LINE = {
    id: "l1", statement_id: "s1", account: "111122233333444455556666", statement_type: "bank_account", currency: "HUF",
    booking_date: "2026-04-10", value_date: null, direction: "debit", amount: "1000.00", counterparty_name: "Example Home",
    counterparty_account: "12121212-34343434-56565656", description: "Transfer", memo: "savings", running_balance: null,
    state: "open", excluded_reason: null, allocated: "0", rest: "1000.00", mark: null, allocations: [], candidates: [],
    rejected: [], statement_verified: true, file: null,
  } as unknown as ReconcileLine;

  it("is marked, and a line to a registered one is not", () => {
    const { rerender } = render(<LineFacts line={{ ...LINE, own_account_unregistered: true }} repeat={false} invoices={new Map()} />);
    expect(screen.getByText("nem nyilvántartott saját számlára")).toBeTruthy();
    rerender(<LineFacts line={LINE} repeat={false} invoices={new Map()} />);
    expect(screen.queryByText("nem nyilvántartott saját számlára")).toBeNull();
  });
});
