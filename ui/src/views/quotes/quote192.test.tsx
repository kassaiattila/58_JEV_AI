// 192 (plan F-quote-package B5, DECISIONS 191, 192): the quote composed beside its request, and its approval. The draft
// starts from the proposal or from the requested items; every change is sent at once with the state the page read; a
// stale page is reloaded; a list price typed again is no price of a person's own; a line to check is confirmed by a
// person; what holds the approval is listed by line, and the approval is the shared element. The local service is
// replaced by spies; invented names only.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor, type CaseView, type QuoteDraftView, type QuoteView, type WorkpackageView } from "../../api";
import { setLanguage } from "../../i18n";
import { stepLabel } from "../../labels";
import { Approval, LineEditor, MatchProposal, RecordView } from "./QuoteElements";
import { quoteStatus } from "./quoteStatus";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

// a quote without a draft yet
const NO_DRAFT: QuoteView["draft"] = {
  draft: null, state: 0, approval: { active: null, versions: [] }, approved: null, lines: [], totals: null, currency: null,
  vat_percent: null, blockers: [], warnings: [], fingerprint: null, price_list: null, proposal_newer: false,
  language: null, languages: ["hu", "en"],
};
const ITEMS = [
  { sku: "HW-MON-24", name: "Monitor 24 inch", unit: "pc", unit_price: "54900", category: "hardware" },
  { sku: "HW-MON-27", name: "Monitor 27 inch", unit: "pc", unit_price: "119000", category: "hardware" },
];
const base = { description: null, unit: null, unit_price: null, discount_percent: null, note: null, checked: false,
  checked_by: null, checked_at: null, proposed_sku: null, candidates: [] as string[] };
const priced = (sku: string, name: string, quantity: string, price: string, net: string) => ({
  sku, name, quantity, unit: "pc", list_price: price, unit_price: price, manual_price: false, discount_percent: "0",
  discount_from: null, net });

const LINES: QuoteDraftView["lines"] = [
  { ...base, id: "l1", row: 0, requested: { description: "24 inch monitor", quantity: 3, unit: "pc" }, sku: "HW-MON-24",
    quantity: "3", mark: "sure", priced: priced("HW-MON-24", "Monitor 24 inch", "3", "54900", "164700") },
  { ...base, id: "l2", row: 1, requested: { description: "2 monitors", quantity: 2, unit: "pc" }, sku: "HW-MON-24",
    quantity: "2", mark: "check", candidates: ["HW-MON-24", "HW-MON-27"],
    priced: priced("HW-MON-24", "Monitor 24 inch", "2", "54900", "109800") },
  { ...base, id: "l3", row: 2, requested: { description: "coffee machine", quantity: 1, unit: "pc" }, sku: null,
    description: "coffee machine", quantity: "1", mark: "not_listed", priced: null },
];

const DRAFT: QuoteDraftView = {
  draft: { price_list: "pl-0123456789", version: 1, header: { customer_name: "Invented Buyer Ltd", contact_name: null, deadline: "2026-11-20", note: null },
    lines: LINES, started_from: "proposal", request_key: "k", proposal_at: "2026-10-21T15:00:00+00:00" },
  state: 7, approval: { active: null, versions: [] }, approved: null, lines: LINES, totals: null, currency: "HUF", vat_percent: "27",
  blockers: [{ code: "quote:line_unchecked", line: "l2", row: 1 }, { code: "quote:line_no_item", line: "l3", row: 2 }],
  warnings: [], fingerprint: "f".repeat(64),
  price_list: { price_list: "pl-0123456789", name: "Invented 2026", version: 1, state: "active", items: ITEMS }, proposal_newer: false,
  language: "hu", languages: ["hu", "en"],
};
const READY_DRAFT: QuoteDraftView = { ...DRAFT, blockers: [], totals: { net: "274500", vat: "74115", gross: "348615" } };

const APPROVED = { header: { customer_name: "Invented Buyer Ltd" }, totals: READY_DRAFT.totals, currency: "HUF", vat_percent: "27",
  price_list: { price_list: "pl-0123456789", name: "Invented 2026", version: 1, fingerprint: "p" }, request: { title: null, key: "k" },
  lines: [{ id: "l1", row: 0, requested: null, mark: "sure" as const, note: null, checked_by: null, sku: "HW-MON-24", name: "Monitor 24 inch",
    quantity: "5", unit: "pc", unit_price: "54900", net: "274500", manual_price: false, discount_percent: "0" }] };

const QUOTE: QuoteView = {
  request: { workpackage_id: "wp-000000000191", item_id: "item-1", kind: "email", title: "Request for monitors", sender: "buyer@example.com",
    received_at: "2026-11-02T10:00:00", parts: [], fields: { customer_name: "Invented Buyer Ltd", deadline: "2026-11-20" }, sources: {},
    items: [{ description: "24 inch monitor", quantity: "3", unit: "pc" }, { description: "2 monitors", quantity: "2", unit: "pc" },
      { description: "coffee machine", quantity: "1", unit: "pc" }], items_from: 0 },
  source: { workpackage_id: "wp-000000000191", item_id: "item-1", workpackage_name: "Invented mailbox" },
  price_lists: [{ price_list: "pl-0123456789", name: "Invented 2026", version: 1, currency: "HUF", vat_percent: "27", items: 2,
    discounts: [], fingerprint: "p" }],
  blockers: [], proposal: null, proposal_cap: { engine: "jev", items: 3, usd: { jev: "0.009" } }, draft: DRAFT,
};

function view(quote: QuoteView, status = "active"): WorkpackageView {
  return { workpackage: { id: "wp-000000000195", name: "Quote", source_kind: "quote", status }, quote } as unknown as WorkpackageView;
}

/** 231 (A3d): the quote's stages as a case's page shows them, through its elements (the quote package's page is gone). */
function QuoteStages({ view, stage, onChanged }: { view: WorkpackageView; stage: string; onChanged: () => void }) {
  const { workpackage, quote } = view as unknown as { workpackage: { id: string; status?: string }; quote: QuoteView };
  const page = { case: { status: workpackage.status ?? "open" }, steps: {}, tabs: [], next: null } as unknown as CaseView;
  const props = (type: string) => ({ caseId: workpackage.id, element: { type, step: null, data: { quote } }, page, onChanged });
  if (stage === "process") return <RecordView {...props("record_view")} />;
  if (stage === "review") return <><MatchProposal {...props("match_proposal")} /><LineEditor {...props("line_editor")} /></>;
  return <Approval {...props("approval")} />;
}

describe("the quote composed beside its request (192)", () => {
  it("starts from the finished proposal, or from the requested items alone", async () => {
    const start = vi.spyOn(api, "startQuoteDraft").mockResolvedValue(DRAFT);
    const done = { state: "done" as const, engine: "jev" as const, price_list: "pl-0123456789", version: 1, requested_by: "x",
      requested_at: "2026-10-21T15:00:00+00:00", finished_at: "2026-10-21T15:00:05+00:00", error: null, limits: {}, lines: [], stale: false };
    const { rerender } = render(<QuoteStages view={view({ ...QUOTE, draft: NO_DRAFT, proposal: done })} stage="review" onChanged={() => {}} />);
    const compose = screen.getByRole("button", { name: "Compose the quote from the proposal" });
    expect(compose.className).toContain("primary");
    expect(screen.getByRole("button", { name: "Ask for a new proposal" }).className).toContain("secondary");
    fireEvent.click(compose);
    await waitFor(() => expect(start).toHaveBeenCalledWith("wp-000000000195", { source: "proposal", expected_state: 0 }));
    rerender(<QuoteStages view={view({ ...QUOTE, draft: NO_DRAFT })} stage="review" onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Start without a proposal" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("wp-000000000195", { source: "request", expected_state: 0 }));
  });

  it("shows each line beside its requested item, with its mark and what still holds it", () => {
    render(<QuoteStages view={view(QUOTE)} stage="review" onChanged={() => {}} />);
    const side = within(screen.getByRole("complementary", { name: "The request" }));
    expect(side.getByText("coffee machine")).toBeTruthy();
    const lines = screen.getByRole("table", { name: "The quote's lines" });
    const groups = lines.querySelectorAll("tbody");
    expect(groups).toHaveLength(3);
    expect(within(groups[0] as HTMLElement).getByText("sure").className).toContain("s-done");
    expect(within(groups[0] as HTMLElement).getByText("Asked: 24 inch monitor · 3 pc")).toBeTruthy();
    expect(within(groups[1] as HTMLElement).getByText("to check").className).toContain("s-review");
    expect((groups[1] as HTMLElement).className).toContain("open");
    expect(within(groups[2] as HTMLElement).getByText("No item: choose a price list item, or give a price of your own with a note")).toBeTruthy();
    // the list price shows as the line's value, in ink; the line outside the list has none yet
    expect((screen.getByRole("textbox", { name: "Line 1: unit price" }) as HTMLInputElement).value).toBe("54,900");
    expect((screen.getByRole("textbox", { name: "Line 3: unit price" }) as HTMLInputElement).value).toBe("");
    expect(screen.getByText("2 thing(s) to settle before the approval").className).toContain("s-review");
    expect(screen.getByText("The totals show once every line is priced.")).toBeTruthy();
    // the page header's next step is the view's one solid action
    expect(screen.getByRole("link", { name: "To the approval" }).className).toContain("secondary");
  });

  it("confirms a line to check, and sends a typed price with the state the page read", async () => {
    const save = vi.spyOn(api, "saveQuoteDraft").mockResolvedValue({ ...DRAFT, state: 8 });
    const changed = vi.fn();
    render(<QuoteStages view={view(QUOTE)} stage="review" onChanged={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "Confirm the item" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const [wp, sent, state] = save.mock.calls[0];
    expect([wp, state]).toEqual(["wp-000000000195", 7]);
    expect(sent.lines.map((l) => [l.id, l.checked])).toEqual([["l1", false], ["l2", true], ["l3", false]]);
    await waitFor(() => expect(changed).toHaveBeenCalled());
    const price = screen.getByRole("textbox", { name: "Line 3: unit price" });
    fireEvent.change(price, { target: { value: "45 000" } });
    fireEvent.blur(price);
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1][1].lines[2].unit_price).toBe("45 000"); // the service reads it the Hungarian way
    expect(save.mock.calls[1][2]).toBe(8);
  });

  it("saves two quick changes one after another, the second on the first one's answer", async () => {
    let answer: (v: QuoteDraftView) => void = () => {};
    const save = vi.spyOn(api, "saveQuoteDraft")
      .mockImplementationOnce(() => new Promise((resolve) => { answer = resolve; }))
      .mockResolvedValueOnce({ ...DRAFT, state: 9 });
    render(<QuoteStages view={view(QUOTE)} stage="review" onChanged={() => {}} />);
    const first = screen.getByRole("textbox", { name: "Line 1: quantity" });
    fireEvent.change(first, { target: { value: "4" } });
    fireEvent.blur(first);
    const second = screen.getByRole("textbox", { name: "Line 2: quantity" });
    fireEvent.change(second, { target: { value: "6" } });
    fireEvent.blur(second);
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1)); // the second waits for the first
    answer({ ...DRAFT, state: 8 });
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save.mock.calls[1][2]).toBe(8);
    expect(save.mock.calls[1][1].lines[1].quantity).toBe("6");
  });

  it("does not take the list price typed again for a price of a person's own", async () => {
    const save = vi.spyOn(api, "saveQuoteDraft").mockResolvedValue({ ...DRAFT, state: 8 });
    render(<QuoteStages view={view(QUOTE)} stage="review" onChanged={() => {}} />);
    const price = screen.getByRole("textbox", { name: "Line 1: unit price" });
    fireEvent.change(price, { target: { value: "50,000" } });
    fireEvent.change(price, { target: { value: "54,900" } }); // typed back to the list's price
    fireEvent.blur(price);
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1].lines[0].unit_price).toBeNull();
  });

  it("chooses another item from the price list or a line of one's own", async () => {
    const save = vi.spyOn(api, "saveQuoteDraft").mockResolvedValue({ ...DRAFT, state: 8 });
    render(<QuoteStages view={view(QUOTE)} stage="review" onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Line 2: item" }));
    // the proposal's other candidate comes first, under its own heading
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options[0]).toContain("A line of my own");
    expect(options[1]).toContain("Monitor 27 inch");
    fireEvent.click(screen.getByRole("option", { name: /Monitor 27 inch/ }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1].lines[1].sku).toBe("HW-MON-27");
  });

  it("reloads a page that is stale, and says so", async () => {
    vi.spyOn(api, "saveQuoteDraft").mockRejectedValue(new ApiError(409, "revision_conflict", "changed"));
    const changed = vi.fn();
    render(<QuoteStages view={view(QUOTE)} stage="review" onChanged={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "Confirm the item" }));
    expect(await screen.findByText("The quote changed since it was shown; it has been reloaded. Check it and try again.")).toBeTruthy();
    expect(changed).toHaveBeenCalled();
  });

  it("lists what holds the approval by line, and approves a quote that is ready", async () => {
    const approve = vi.spyOn(api, "approveQuote").mockResolvedValue({ ...READY_DRAFT, approved: APPROVED,
      approval: { active: { version: 1, fingerprint: "f".repeat(64), approved_by: "Synthetic reviewer", approved_at: "2026-10-21T15:00:00+00:00",
        reopened_by: null, reopened_at: null, reopen_note: null }, versions: [] } });
    const { rerender } = render(<QuoteStages view={view(QUOTE)} stage="result" onChanged={() => {}} />);
    expect(screen.getByText("Line 2: To check: confirm the proposed item or choose another")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve the quote" })).toHaveProperty("disabled", true);
    rerender(<QuoteStages view={view({ ...QUOTE, draft: READY_DRAFT })} stage="result" onChanged={() => {}} />);
    const button = screen.getByRole("button", { name: "Approve the quote (348,615 HUF gross)" });
    expect(button.className).toContain("primary");
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "Sure? Click again" }));
    await waitFor(() => expect(approve).toHaveBeenCalledWith("wp-000000000195", "f".repeat(64)));
    expect(await screen.findByText("The quote has been approved.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "The approved quote: version 1" })).toBeTruthy();
  });

  it("keeps an approved quote unchanged, and reopens it only with a reason", async () => {
    const active = { version: 1, fingerprint: "f".repeat(64), approved_by: "Synthetic reviewer", approved_at: "2026-10-21T15:00:00+00:00",
      reopened_by: null, reopened_at: null, reopen_note: null };
    const locked: QuoteView = { ...QUOTE, draft: { ...READY_DRAFT, approval: { active, versions: [active] }, approved: APPROVED } };
    const reopen = vi.spyOn(api, "reopenQuote").mockResolvedValue(READY_DRAFT);
    const { rerender } = render(<QuoteStages view={view(locked)} stage="review" onChanged={() => {}} />);
    expect(screen.queryByRole("table", { name: "The quote's lines" })?.querySelector("input")).toBeFalsy();
    expect(screen.getByRole("link", { name: "To change it, reopen it in Approval." })).toBeTruthy();
    rerender(<QuoteStages view={view(locked)} stage="result" onChanged={() => {}} />);
    const button = screen.getByRole("button", { name: "Reopen" });
    expect(button).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByRole("textbox", { name: "Reason for reopening" }), { target: { value: "Six monitors" } });
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "Sure? Click again" }));
    await waitFor(() => expect(reopen).toHaveBeenCalledWith("wp-000000000195", "Six monitors"));
  });

  it("names the quote's steps and stages", () => {
    expect(stepLabel("quote_approve", {}, "")).toBe("Approve the quote");
    expect(stepLabel("quote_approved", { version: 2 }, "")).toBe("Approved: version 2");
    expect(stepLabel("quote_compose", { n: 3 }, "")).toBe("Compose the quote: 3 to settle");
    expect(quoteStatus(QUOTE)).toMatchObject({ review: "3 line(s), 2 to settle", result: "not approved yet" });
    expect(quoteStatus({ ...QUOTE, draft: READY_DRAFT })?.result).toBe("348,615 HUF gross, to approve");
  });
});
