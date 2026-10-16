// 160 (review M-1): a pairing whose invoice left the pairing, and a pairing or a mark whose line is no longer on its
// statement, are listed with the decisions that no longer count, each with its reason and a revoke button; their
// blockers say what they are. Artificial data, no service.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReconcileBlocker, ReconcileUnfit, ReconcileWorkspace } from "../../api";
import { blockerGroupText, blockerText } from "./labels";
import { Unfit } from "./ReconcileStages";

const BASE: ReconcileUnfit = {
  kind: "allocation", ref: "17", reason: "amounts", line_id: "l1", invoice_id: "inv-000000000001", invoice_reason: null,
  category: null, statement_id: "s1", workpackage_id: "wp-1", line_amount: "100.00", invoice_amount: "100.00",
  line_total: "100.00", invoice_total: "60.00", currency: "HUF", booking_date: "2026-04-10", direction: "debit",
  counterparty_name: "Example Supplier", invoice_file: "szamla.pdf", file: "kivonat.pdf",
};
const LEFT_OUT: ReconcileUnfit = { ...BASE, ref: "18", reason: "invoice_left_out", invoice_reason: "duplicate_undecided",
  line_total: null, invoice_total: null };
const GONE: ReconcileUnfit = { ...BASE, ref: "19", reason: "line_gone", line_total: null, invoice_total: null, booking_date: null,
  direction: null, counterparty_name: null };
const MARK_GONE: ReconcileUnfit = { ...GONE, kind: "mark", ref: "20", invoice_id: null, invoice_file: null, category: "fee",
  line_amount: null, invoice_amount: null };

function renderRows(rows: ReconcileUnfit[], onRevoke = vi.fn()) {
  render(<Unfit ws={{ unfit: rows } as unknown as ReconcileWorkspace} readOnly={false} busy={false} onRevoke={onRevoke} />);
  return onRevoke;
}

describe("160 decisions that no longer count", () => {
  it("say why each one no longer counts", () => {
    renderRows([BASE, LEFT_OUT, GONE, MARK_GONE]);
    expect(screen.getByRole("heading", { name: "Már nem érvényes döntések" })).toBeTruthy();
    expect(screen.getByText("megváltozott egy összeg")).toBeTruthy();
    expect(screen.getByText("a számla kiesett a párosításból: Eldöntetlen ismétlődés")).toBeTruthy();
    expect(screen.getAllByText("a sort javították vagy újraolvasták")).toHaveLength(2);
  });

  it("show a gone line by its statement and a mark by its reason, and revoke the mark", () => {
    const onRevoke = renderRows([MARK_GONE]);
    expect(screen.getByText("már nincs rajta: kivonat.pdf")).toBeTruthy();
    expect(screen.getByText("nem kell számla (Banki díj vagy kamat)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Visszavonás" }));
    expect(onRevoke).toHaveBeenCalledWith(MARK_GONE);
  });

  it("name their blockers", () => {
    const left = { code: "allocation_invoice_left_out", doc_id: "inv-000000000001", file: "szamla.pdf", kind: "invoice" } as ReconcileBlocker;
    const gone = { code: "decision_line_gone", doc_id: "s1", file: "kivonat.pdf", kind: "statement" } as ReconcileBlocker;
    expect(blockerText(left)).toBe("Egy párosítás számlája már nem vesz részt a párosításban: szamla.pdf");
    expect(blockerText(gone)).toBe("Egy döntés sora már nincs rajta a kivonaton: kivonat.pdf");
    expect(blockerGroupText("allocation_invoice_left_out", 2)).toBe("2 párosítás számlája már nem vesz részt a párosításban");
    expect(blockerGroupText("decision_line_gone", 3)).toBe("3 döntés sora már nincs rajta a kivonaton");
  });
});
