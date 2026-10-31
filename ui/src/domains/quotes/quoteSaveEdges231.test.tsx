// 231 (stage D, D-a; the reassessment after D0 of 2026-10-26, F07, F08, F10, P01, T11, T12): a person's typing on an
// older version never silently writes over a newer one, and a change to a row another person removed is not settled
// for them. Typing records the version it started from: when a newer version arrives before the save (another person
// saved, the editor opened again), the person compares where the other person changed the same field, and the typing
// goes on over the newer version elsewhere. A change to a removed row stays until the person decides. While anything is
// not saved, the head says so instead of "ready to approve". The local service is replaced by spies; invented names.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor, type CaseView } from "../../api";
import { setLanguage } from "../../i18n";
import type { QuoteDraftView, QuoteView } from "./api";
import { LineEditor } from "./QuoteElements";
import { confirmAction } from "../../confirm.testutil";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { vi.restoreAllMocks(); });

const CASE = "wp-0000000d0a40";
const base = { description: null, unit: null, unit_price: null, discount_percent: null, note: null, checked: true,
  checked_by: "Synthetic reviewer", checked_at: null, proposed_sku: null, candidates: [] as string[], mark: "sure" as const };
const priced = (quantity: string) => ({ sku: "HW-MON-24", name: "Monitor 24 inch", quantity, unit: "pc", list_price: "54900",
  unit_price: "54900", manual_price: false, discount_percent: "0", discount_from: null, net: "54900" });

function draft(state: number, quantity: string | null, note: string | null = null): QuoteDraftView {
  const lines = quantity === null ? [] : [{ ...base, id: "l1", row: 0, requested: null, sku: "HW-MON-24", quantity, priced: priced(quantity) }];
  return {
    draft: { price_list: "pl-0123456789", version: 1, header: { customer_name: "Invented Buyer Ltd", note },
      lines, started_from: "request", request_key: "k", proposal_at: null },
    state, approval: { active: null, versions: [] }, approved: null, lines, totals: { net: "54900", vat: "14823", gross: "69723" },
    currency: "HUF", vat_percent: "27", blockers: [], warnings: [], fingerprint: "f".repeat(64),
    price_list: { price_list: "pl-0123456789", name: "Invented 2026", version: 1, state: "active",
      items: [{ sku: "HW-MON-24", name: "Monitor 24 inch", unit: "pc", unit_price: "54900", category: null }] },
    proposal_newer: false, language: "hu", languages: ["hu", "en"],
  };
}

function editor(d: QuoteDraftView, onChanged = () => {}) {
  const page = { case: { status: "open" }, steps: {}, tabs: [], next: null } as unknown as CaseView;
  const quote = { request: null, source: null, price_lists: [], blockers: [], proposal: null,
    proposal_cap: { engine: "jev", items: 1, usd: { jev: "0.003" } }, draft: d } as unknown as QuoteView;
  return <LineEditor caseId={CASE} element={{ type: "line_editor", step: null, data: { quote } }} page={page} onChanged={onChanged} />;
}

const quantity = () => screen.getByRole("textbox", { name: "Line 1: quantity" }) as HTMLInputElement;

describe("typing on an older version", () => {
  it("is compared where the newer version changed the same field, never sent over it silently", async () => {
    const save = vi.spyOn(api, "saveQuoteDraft");
    const { rerender } = render(editor(draft(7, "3")));
    fireEvent.change(quantity(), { target: { value: "4" } });  // typed, not saved yet
    rerender(editor(draft(9, "5")));  // another person saved 5 meanwhile
    const row = (await screen.findByText("Line 1: Quantity")).closest("tr")!;
    expect(row.textContent).toBe("Line 1: Quantitychanged by them too45");
    fireEvent.blur(quantity());
    await new Promise((r) => setTimeout(r, 50));
    expect(save).not.toHaveBeenCalled();  // nothing is sent until the person decides
  });

  it("goes on over the newer version where it changed another field", async () => {
    const save = vi.spyOn(api, "saveQuoteDraft").mockResolvedValue(draft(10, "4", "their note"));
    const { rerender } = render(editor(draft(7, "3")));
    fireEvent.change(quantity(), { target: { value: "4" } });
    rerender(editor(draft(9, "3", "their note")));
    fireEvent.blur(quantity());
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const [, body, state] = save.mock.calls[0];
    expect([state, body.lines[0].quantity, body.header.note]).toEqual([9, "4", "their note"]);
    expect(screen.queryByText(/^Someone else saved this meanwhile/)).toBe(null);
  });

  it("says the changes are to be saved first instead of ready to approve", () => {
    render(editor(draft(7, "3")));
    expect(screen.getByText("ready to approve")).toBeTruthy();
    fireEvent.change(quantity(), { target: { value: "4" } });
    expect(screen.getByText("save the changes first")).toBeTruthy();
    expect(screen.queryByText("ready to approve")).toBe(null);
  });
});

describe("a change to a row another person removed", () => {
  it("stays until the person decides", async () => {
    vi.spyOn(api, "saveQuoteDraft").mockRejectedValueOnce(new ApiError(409, "revision_conflict", "changed"));
    const { rerender } = render(editor(draft(7, "3")));
    fireEvent.change(quantity(), { target: { value: "4" } });
    fireEvent.blur(quantity());
    await screen.findByText("Not saved: someone else saved it meanwhile");
    rerender(editor(draft(9, null)));  // they removed the line
    expect(await screen.findByText("they removed it: yours cannot be applied")).toBeTruthy();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText("Not saved: someone else saved it meanwhile")).toBeTruthy();  // not settled for them
    fireEvent.click(screen.getByRole("button", { name: "Drop mine, keep theirs" }));
    fireEvent.click(confirmAction());
    await waitFor(() => expect(screen.queryByText(/^Someone else saved this meanwhile/)).toBe(null));
  });
});
