// 148 (DECISIONS 148): an outgoing invoice's partner is its buyer. The quick review names an invoice by its partner (the
// service's partner_name: the supplier of an incoming invoice, the buyer of an outgoing one), not by the own company that
// issued it. The local service is replaced by a spy; synthetic names only.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, setActor } from "../../../api";
import type { QuickReview } from "../api";
import { setLanguage } from "../../../i18n";
import { ReconcileQuickReview } from "./ReconcileQuickReview";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("names an outgoing invoice by its buyer", async () => {
  const review: QuickReview = {
    workpackage_id: "wp-00000000000a", threshold: 0.95, excluded: {}, decided: {},
    groups: [{ id: "sure_pairs", action: "pair", count: 1, totals: { HUF: "100.00" }, lines: [{
      id: "l-in", statement_id: "stmt", booking_date: "2026-04-14", amount: "100.00", currency: "HUF", direction: "credit",
      counterparty_name: "Northwind Trading", memo: "INV-0001", description: null,
      invoices: [{ id: "inv", number: "INV-0001", supplier_name: "Sample Own Company Kft.", partner_name: "Northwind Trading Ltd.",
        amount: "100.00", currency: "HUF", issue_date: "2026-04-01" }] }] }],
  };
  vi.spyOn(api, "reconcileQuickReview").mockResolvedValue(review);
  render(<ReconcileQuickReview wpId="wp-00000000000a" readOnly={false} onWorkspace={vi.fn()} onCards={vi.fn()} />);
  const group = await screen.findByRole("region", { name: "Sure pairs" });
  expect(group.textContent).toContain("INV-0001 · Northwind Trading Ltd.");
  expect(group.textContent).not.toContain("Sample Own Company");
});
