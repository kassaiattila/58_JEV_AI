// 153 (review A3): a pairing that no longer fits the amounts of its line or invoice is listed in the package's
// Preparation stage with a revoke button, and its blocker says what it is. Artificial data, no service.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReconcileBlocker, ReconcileUnfit, ReconcileWorkspace } from "../../api";
import { blockerText } from "./labels";
import { Unfit } from "./ReconcileStages";

const ROW: ReconcileUnfit = {
  kind: "allocation", ref: "17", line_id: "l1", invoice_id: "inv-000000000001", statement_id: "s1", workpackage_id: "wp-1",
  line_amount: "100.00", invoice_amount: "100.00", line_total: "100.00", invoice_total: "60.00", currency: "HUF",
  booking_date: "2026-04-10", direction: "debit", counterparty_name: "Example Supplier", invoice_file: "szamla.pdf",
};

describe("153 pairings that no longer fit", () => {
  it("are listed with the amounts now and can be revoked", () => {
    const onRevoke = vi.fn();
    render(<Unfit ws={{ unfit: [ROW] } as unknown as ReconcileWorkspace} readOnly={false} busy={false} onRevoke={onRevoke} />);
    expect(screen.getByRole("heading", { name: "Már nem férő párosítások" })).toBeTruthy();
    expect(screen.getByText("szamla.pdf")).toBeTruthy();
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
