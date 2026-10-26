// 156 (redesign): one solid action per view on the quick review — accepting the sure pairs; every other group's
// acceptance is secondary. The local service is replaced by a spy; synthetic names only.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, setActor } from "../../../api";
import type { QuickReview, QuickReviewLine } from "../api";
import { setLanguage } from "../../../i18n";
import { ReconcileQuickReview } from "./ReconcileQuickReview";

const line = (id: string): QuickReviewLine => ({ id, statement_id: "stmt", booking_date: "2026-04-14", amount: "13.00", currency: "HUF",
  direction: "debit", counterparty_name: "Example Market", memo: null, description: null });

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("only the sure pairs' acceptance is the solid action", async () => {
  vi.spyOn(api, "reconcileQuickReview").mockResolvedValue({
    workpackage_id: "wp-00000000000a", threshold: 0.95, excluded: {}, decided: {},
    groups: [
      { id: "sure_pairs", action: "pair", count: 1, totals: { HUF: "13.00" }, lines: [line("l-pair")] },
      { id: "ai_sure", action: "mark", count: 1, totals: { HUF: "13.00" }, lines: [line("l-sure")] },
    ],
  } as unknown as QuickReview);
  render(<ReconcileQuickReview wpId="wp-00000000000a" readOnly={false} onWorkspace={vi.fn()} onCards={vi.fn()} />);
  const pairs = await screen.findByRole("region", { name: "Sure pairs" });
  const sure = screen.getByRole("region", { name: "Sure by AI" });
  expect(within(pairs).getByRole("button", { name: "Accept 1 line(s)" }).classList.contains("primary")).toBe(true);
  expect(within(sure).getByRole("button", { name: "Accept 1 line(s)" }).classList.contains("primary")).toBe(false);
  expect(document.querySelectorAll("button.primary")).toHaveLength(1);
});
