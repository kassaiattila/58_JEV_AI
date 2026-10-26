// 231 (stage D0, D0-g; the reassessment of 2026-10-26, F15, P12): a person's typed work in the quote is never lost
// without a word and never silently written over another person's. A save refused because someone else saved meanwhile
// keeps the person's change beside the version saved now; keeping it saves only the person's changes over theirs, dropping
// it takes theirs. A save whose outcome is not known (the connection broke) is kept and sent again. The unsaved work
// survives switching to another case and back, the browser warns before the page is left with it, and the quote is not
// approved while it has any. The local service is replaced by spies; invented names only.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor, type CaseView } from "../../api";
import { setLanguage } from "../../i18n";
import type { QuoteDraftView, QuoteView } from "./api";
import { Approval, LineEditor } from "./QuoteElements";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { vi.restoreAllMocks(); });

const CASE = "wp-0000000d0f00";
const base = { description: null, unit: null, unit_price: null, discount_percent: null, note: null, checked: true,
  checked_by: "Synthetic reviewer", checked_at: null, proposed_sku: null, candidates: [] as string[], mark: "sure" as const };
const priced = (quantity: string, net: string) => ({ sku: "HW-MON-24", name: "Monitor 24 inch", quantity, unit: "pc",
  list_price: "54900", unit_price: "54900", manual_price: false, discount_percent: "0", discount_from: null, net });
const line = (id: string, quantity: string, net: string) =>
  ({ ...base, id, row: 0, requested: null, sku: "HW-MON-24", quantity, priced: priced(quantity, net) });

function draft(state: number, quantity: string, note: string | null = null): QuoteDraftView {
  const lines = [line("l1", quantity, "54900")];
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

const quote = (d: QuoteDraftView): QuoteView => ({
  request: null, source: null, price_lists: [], blockers: [], proposal: null,
  proposal_cap: { engine: "jev", items: 1, usd: { jev: "0.003" } }, draft: d,
} as unknown as QuoteView);

function element(Kind: typeof LineEditor, d: QuoteDraftView, onChanged = () => {}) {
  const page = { case: { status: "open" }, steps: {}, tabs: [], next: null } as unknown as CaseView;
  return <Kind caseId={CASE} element={{ type: "line_editor", step: null, data: { quote: quote(d) } }} page={page} onChanged={onChanged} />;
}

function typeQuantity(value: string, blur = true) {
  const box = screen.getByRole("textbox", { name: "Line 1: quantity" });
  fireEvent.change(box, { target: { value } });
  if (blur) fireEvent.blur(box);
}

describe("a save someone else's save refused", () => {
  it("keeps my change beside the version saved now, and keeping it saves only mine over theirs", async () => {
    const save = vi.spyOn(api, "saveQuoteDraft").mockRejectedValueOnce(new ApiError(409, "revision_conflict", "changed"))
      .mockResolvedValueOnce(draft(10, "4", "their note"));
    const changed = vi.fn();
    const { rerender } = render(element(LineEditor, draft(7, "3"), changed));
    typeQuantity("4");
    await waitFor(() => expect(changed).toHaveBeenCalled());  // the version saved now is read again
    expect(screen.getByText("Not saved: someone else saved it meanwhile")).toBeTruthy();
    rerender(element(LineEditor, draft(9, "5", "their note"), changed));
    const row = (await screen.findByText("Line 1: Quantity")).closest("tr")!;
    expect(row.textContent).toBe("Line 1: Quantitychanged by them too45");
    expect((screen.getByRole("textbox", { name: "Line 1: quantity" }) as HTMLInputElement).value).toBe("4");  // mine stays typed
    fireEvent.click(screen.getByRole("button", { name: "Keep my changes" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    const [, body, state] = save.mock.calls[1];
    expect([state, body.lines[0].quantity, body.header.note]).toEqual([9, "4", "their note"]);  // their note stays theirs
    await waitFor(() => expect(screen.queryByText(/^Someone else saved this meanwhile/)).toBe(null));
  });

  it("drops mine for theirs when the person says so twice", async () => {
    const save = vi.spyOn(api, "saveQuoteDraft").mockRejectedValueOnce(new ApiError(409, "revision_conflict", "changed"));
    const { rerender } = render(element(LineEditor, draft(7, "3")));
    typeQuantity("4");
    await screen.findByText("Not saved: someone else saved it meanwhile");
    rerender(element(LineEditor, draft(9, "5")));
    fireEvent.click(await screen.findByRole("button", { name: "Drop mine, keep theirs" }));
    fireEvent.click(screen.getByRole("button", { name: "Sure? Click again" }));
    expect((screen.getByRole("textbox", { name: "Line 1: quantity" }) as HTMLInputElement).value).toBe("5");
    expect(screen.getByText("Every change is saved at once.")).toBeTruthy();
    expect(save).toHaveBeenCalledTimes(1);
  });

  it("says nothing more when the version saved now holds my change already", async () => {
    vi.spyOn(api, "saveQuoteDraft").mockRejectedValueOnce(new ApiError(409, "revision_conflict", "changed"));
    const { rerender } = render(element(LineEditor, draft(7, "3")));
    typeQuantity("4");
    await screen.findByText("Not saved: someone else saved it meanwhile");
    rerender(element(LineEditor, draft(8, "4")));  // an earlier try of mine went through
    await waitFor(() => expect(screen.queryByText(/^Someone else saved this meanwhile/)).toBe(null));
    expect(screen.getByText("Every change is saved at once.")).toBeTruthy();
  });
});

describe("a save whose outcome is not known", () => {
  it("keeps the change, says so, and sends it again", async () => {
    const save = vi.spyOn(api, "saveQuoteDraft").mockRejectedValueOnce(new ApiError(0, "offline", "the service cannot be reached"))
      .mockResolvedValueOnce(draft(8, "4"));
    render(element(LineEditor, draft(7, "3")));
    typeQuantity("4");
    expect(await screen.findByText("Whether it was saved is not known")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save again" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect([save.mock.calls[1][2], save.mock.calls[1][1].lines[0].quantity]).toEqual([7, "4"]);
    expect(await screen.findByText(/^Saved /)).toBeTruthy();
  });
});

describe("unsaved work on the page", () => {
  const leaving = () => { const e = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented; };

  it("survives switching to another case and back, and the browser warns before the page is left", () => {
    const first = render(element(LineEditor, draft(7, "3")));
    typeQuantity("4", false);
    expect(screen.getByText("Changes not saved yet")).toBeTruthy();
    first.unmount();  // another case
    expect(leaving()).toBe(true);
    render(element(LineEditor, draft(7, "3")));
    expect((screen.getByRole("textbox", { name: "Line 1: quantity" }) as HTMLInputElement).value).toBe("4");
    const stored = [sessionStorage, localStorage].flatMap((s) => Array.from({ length: s.length }, (_, i) => `${s.key(i)}=${s.getItem(s.key(i)!)}`));
    expect(stored.filter((x) => x.includes(CASE) || x.includes("quote:"))).toEqual([]);  // never in the browser's storage
  });

  it("holds the approval until it is saved", async () => {
    vi.spyOn(api, "saveQuoteDraft").mockResolvedValue(draft(8, "4"));
    const editor = render(element(LineEditor, draft(7, "3")));
    typeQuantity("4", false);
    editor.unmount();
    const approval = render(element(Approval, draft(7, "3")));
    expect(screen.getByText("The quote has changes not saved yet")).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Approve the quote/ })).toHaveProperty("disabled", true);
    approval.unmount();
    render(element(LineEditor, draft(7, "3")));
    await act(async () => { fireEvent.blur(screen.getByRole("textbox", { name: "Line 1: quantity" })); });
    await screen.findByText(/^Saved /);
    expect(leaving()).toBe(false);
  });
});
