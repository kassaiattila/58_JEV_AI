// 147 (DECISIONS 147): the quick review of a reconciliation package. The groups with their lines, counts and totals;
// the sure groups start ticked, the AI's suggestions to look at do not; a group is accepted for its ticked lines (with a
// second click), and a stale view is reloaded. The local service is replaced by spies; synthetic names only.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor } from "../../../api";
import type { QuickReview, QuickReviewLine, ReconcileWorkspace } from "../api";
import { setLanguage } from "../../../i18n";
import { ReconcileQuickReview } from "./ReconcileQuickReview";
import { confirmAction } from "../../../confirm.testutil";

function line(id: string, over: Partial<QuickReviewLine> = {}): QuickReviewLine {
  return { id, statement_id: "stmt", booking_date: "2026-04-14", amount: "13.00", currency: "HUF", direction: "debit",
    counterparty_name: "Example Market", memo: null, description: null, ...over };
}

function review(over: Partial<QuickReview> = {}): QuickReview {
  return {
    workpackage_id: "wp-00000000000a", threshold: 0.95,
    groups: [
      { id: "sure_pairs", action: "pair", count: 1, totals: { HUF: "100.00" }, lines: [line("l-pair", { amount: "100.00",
        counterparty_name: "Example Supplier", memo: "INV-0001", invoices: [{ id: "inv", number: "INV-0001", supplier_name: "Example Supplier Kft.",
          amount: "100.00", currency: "HUF", issue_date: "2026-04-01" }] })] },
      { id: "earlier", action: "mark", count: 0, totals: {}, lines: [] },
      { id: "ai_sure", action: "mark", count: 1, totals: { HUF: "13.00" }, lines: [line("l-sure", { category: "private",
        ai: { jev: { kind: "retail_purchase", probability: 0.97 }, gpt: { kind: "retail_purchase", probability: 0.9999 } } })] },
      { id: "ai_review", action: "mark", count: 2, totals: { HUF: "29.00" }, lines: [
        line("l-low", { amount: "14.00", counterparty_name: "Example Kiosk", category: "private", ai: { jev: { kind: "retail_purchase", probability: 0.8 } } }),
        line("l-one", { amount: "15.00", counterparty_name: "Example Cash Point", category: "cash", ai: { jev: { kind: "cash", probability: 0.99 } } })] },
      { id: "rest", action: "none", count: 1, totals: { HUF: "17.00" }, lines: [line("l-rest", { amount: "17.00", counterparty_name: "Example Somebody" })] },
    ],
    excluded: { payment_kind_review: { count: 1, totals: { HUF: "18.00" }, lines: [] } },
    decided: {},
    ...over,
  };
}

const WORKSPACE = { lines: [], invoices: [] } as unknown as ReconcileWorkspace;

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the quick review", () => {
  it("shows the groups, ticks the sure ones and leaves the AI's suggestions to look at unticked", async () => {
    vi.spyOn(api, "reconcileQuickReview").mockResolvedValue(review());
    render(<ReconcileQuickReview wpId="wp-00000000000a" readOnly={false} onWorkspace={vi.fn()} onCards={vi.fn()} />);
    const sure = await screen.findByRole("region", { name: "Sure by AI" });
    expect(sure.textContent).toContain("JEV is at least 0.95 sure of it");
    expect(sure.textContent).toContain("Private expense · JEV: Retail purchase 0.97 · GPT: Retail purchase 1.00");
    expect(within(sure).getByRole("button", { name: "Accept 1 line(s)" })).toBeTruthy();
    const look = screen.getByRole("region", { name: "AI suggestion: look at it" });
    expect((within(look).getByRole("button", { name: "Accept 0 line(s)" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("region", { name: "Sure pairs" }).textContent).toContain("INV-0001 · Example Supplier Kft.");
    expect(screen.queryByRole("region", { name: "As decided before" })).toBeNull();  // an empty group is not shown
    expect(screen.getByText("5 line(s) to decide; 4 of them are in a group you can accept at once.")).toBeTruthy();
    expect(screen.getByText(/Left out by the code \(1\)/)).toBeTruthy();
  });

  it("158: counts only the lines to decide, not the incoming money shown for information", async () => {
    const info = line("l-in", { direction: "credit", counterparty_name: "Example Customer", ai: { jev: { kind: "customer_payment", probability: 0.9 } } });
    const groups = [...review().groups, { id: "expects_invoice" as const, action: "none" as const, count: 1, to_decide: 0, totals: { HUF: "13.00" }, lines: [info] }];
    vi.spyOn(api, "reconcileQuickReview").mockResolvedValue(review({ groups }));
    render(<ReconcileQuickReview wpId="wp-00000000000a" readOnly={false} onWorkspace={vi.fn()} onCards={vi.fn()} />);
    expect(await screen.findByRole("region", { name: "An invoice is expected" })).toBeTruthy();
    expect(screen.getByText("5 line(s) to decide; 4 of them are in a group you can accept at once.")).toBeTruthy();
  });

  it("accepts a group's ticked lines with a second click and shows the new review", async () => {
    vi.spyOn(api, "reconcileQuickReview").mockResolvedValue(review());
    const after = review({ groups: review().groups.map((g) => (g.id === "ai_review" ? { ...g, count: 1, lines: g.lines.slice(1) } : g)) });
    const accept = vi.spyOn(api, "reconcileQuickAccept").mockResolvedValue({ accepted: 1, review: after, workspace: WORKSPACE });
    const onWorkspace = vi.fn();
    render(<ReconcileQuickReview wpId="wp-00000000000a" readOnly={false} onWorkspace={onWorkspace} onCards={vi.fn()} />);
    const look = await screen.findByRole("region", { name: "AI suggestion: look at it" });
    fireEvent.click(within(look).getByRole("checkbox", { name: /Line of 2026-04-14, 14/ }));
    const button = within(look).getByRole("button", { name: "Accept 1 line(s)" });
    fireEvent.click(button);
    expect(accept).not.toHaveBeenCalled();  // the first click only arms it
    fireEvent.click(confirmAction());
    await waitFor(() => expect(accept).toHaveBeenCalledWith("wp-00000000000a", "ai_review", ["l-low"]));
    expect(onWorkspace).toHaveBeenCalledWith(WORKSPACE);
    expect(await screen.findByText("1 line(s) decided.")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "AI suggestion: look at it" })).queryByText("Example Kiosk")).toBeNull();
  });

  it("reloads when the group changed meanwhile, and a read-only package only shows the groups", async () => {
    const load = vi.spyOn(api, "reconcileQuickReview").mockResolvedValue(review());
    vi.spyOn(api, "reconcileQuickAccept").mockRejectedValue(new ApiError(409, "revision_conflict", "1 line(s) are no longer in this group"));
    render(<ReconcileQuickReview wpId="wp-00000000000a" readOnly={false} onWorkspace={vi.fn()} onCards={vi.fn()} />);
    const sure = await screen.findByRole("region", { name: "Sure by AI" });
    const button = within(sure).getByRole("button", { name: "Accept 1 line(s)" });
    fireEvent.click(button);
    fireEvent.click(confirmAction());
    expect(await screen.findByText(/changed meanwhile and has been reloaded/)).toBeTruthy();
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    cleanup();
    render(<ReconcileQuickReview wpId="wp-00000000000a" readOnly onWorkspace={vi.fn()} onCards={vi.fn()} />);
    expect(await screen.findByRole("region", { name: "Sure by AI" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Accept/ })).toBeNull();
  });

  it("lays each group out as a card in the page flow, not as the document page's highlight frame", async () => {
    // 148: the groups once wore the highlight frame's class (absolutely positioned, ignoring clicks), so they were drawn
    // on top of one another and their buttons could not be pressed.
    vi.spyOn(api, "reconcileQuickReview").mockResolvedValue(review());
    render(<ReconcileQuickReview wpId="wp-00000000000a" readOnly={false} onWorkspace={vi.fn()} onCards={vi.fn()} />);
    await screen.findByRole("region", { name: "Sure by AI" });
    const groups = screen.getAllByRole("region");
    expect(groups.length).toBe(4);
    for (const group of groups) {
      expect(group.classList.contains("card")).toBe(true);
      expect(group.classList.contains("rc-box")).toBe(false);
    }
  });
});
