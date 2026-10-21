// 191 (plan F-quote-package B3, DECISIONS 191): the quote as a kind of work - its form in the new work wizard (a quote
// request already processed, chosen from the service's search, with the quotes already made from it) and its package's
// Request stage (the request's fields with the part each came from, its items, its gaps, the active price list). The
// local service is replaced by spies; invented names only.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type QuoteRequestCandidate, type QuoteView, type WorkpackageView } from "../../api";
import { setLanguage } from "../../i18n";
import { LOGIC } from "../../logic/registry";
import { hasOwnForm } from "../../logic/steps";
import { stepLabel } from "../../labels";
import { QUOTE_BLOCKER, QuoteCreate, quoteStatus, QuoteStages } from "./Quote";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const CANDIDATE: QuoteRequestCandidate = {
  workpackage_id: "wp-000000000191", workpackage_name: "Invented mailbox", item_id: "item-1", kind: "email",
  title: "Request for monitors", sender: "buyer@example.com", received_at: "2026-11-02T10:00:00", customer_name: "Invented Buyer Ltd",
  items: 1, quotes: [{ id: "wp-000000000192", name: "Earlier quote" }],
};

const QUOTE: QuoteView = {
  request: {
    workpackage_id: "wp-000000000191", item_id: "item-1", kind: "email", title: "Request for monitors", sender: "buyer@example.com",
    received_at: "2026-11-02T10:00:00",
    parts: [
      { kind: "email_text", name: "Request for monitors", item_id: null, doc_id: "d1", values: {} },
      { kind: "attachment", name: "list.xlsx", item_id: "item-2", doc_id: "d2", values: {} },
    ],
    fields: { customer_name: "Invented Buyer Ltd", deadline: null }, sources: { customer_name: 0 },
    items: [{ description: "24 inch monitor", quantity: "3", unit: "pc" }], items_from: 1,
  },
  source: { workpackage_id: "wp-000000000191", item_id: "item-1", workpackage_name: "Invented mailbox" },
  price_lists: [], blockers: [{ code: "quote:no_price_list", message: "There is no active price list" }],
};

function view(quote: QuoteView): WorkpackageView {
  return { workpackage: { id: "wp-000000000193", name: "Quote", source_kind: "quote" }, quote } as unknown as WorkpackageView;
}

describe("the quote package (191)", () => {
  it("is a kind of work with its own form and a logic pack's stages", () => {
    expect(hasOwnForm("quote")).toBe(true);
    expect(LOGIC.quote.stages?.labels).toEqual({ process: "Request", review: "Quote", result: "Approval" });
    expect(quoteStatus(view(QUOTE))).toEqual({ process: "2 part(s), 1 requested item(s)", review: "1 gap(s) to clear first",
      result: "not approved yet" });
    expect(stepLabel("quote_request_check", { n: 2 }, "")).toBe("Check the request: 2 gap(s)");
    expect(stepLabel("quote_compose", {}, "")).toBe("Compose the quote");
  });

  it("chooses a request found by the service, warns of a quote already made, and names the quote by its customer", async () => {
    const search = vi.spyOn(api, "quoteRequests").mockResolvedValue({ requests: [CANDIDATE] });
    const create = vi.spyOn(api, "createQuotePackage").mockResolvedValue({ workpackage_id: "wp-000000000194" });
    const done = vi.fn();
    render(<QuoteCreate onDone={done} />);
    const button = screen.getByRole("button", { name: "Create" });
    expect(button).toHaveProperty("disabled", true);
    await waitFor(() => expect(search).toHaveBeenCalledWith(undefined));
    fireEvent.click(screen.getByRole("button", { name: "Quote request" }));
    fireEvent.click(await screen.findByRole("option", { name: /Request for monitors/ }));
    expect(await screen.findByText(/customer: Invented Buyer Ltd/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Earlier quote" }).getAttribute("href")).toBe("#/workpackages/wp-000000000192");
    expect((screen.getByLabelText(/Name/) as HTMLInputElement).placeholder).toBe("Quote: Invented Buyer Ltd");
    fireEvent.click(button);
    await waitFor(() => expect(create).toHaveBeenCalledWith({ name: "Quote: Invented Buyer Ltd", source: "wp-000000000191", item_id: "item-1" }));
    await waitFor(() => expect(done).toHaveBeenCalledWith("wp-000000000194"));
  });

  it("shows the request's fields with the part each came from, its items and its gaps", () => {
    render(<QuoteStages view={view(QUOTE)} stage="process" onChanged={() => {}} />);
    const fields = within(screen.getByRole("table", { name: "The request's data" }));
    const customer = fields.getByText("Invented Buyer Ltd").closest("tr") as HTMLElement;
    expect(within(customer).getByText("the email's text: Request for monitors")).toBeTruthy();
    const deadline = fields.getAllByRole("row")[2];
    expect(within(deadline).getByText("—")).toBeTruthy(); // a field no part has
    expect(screen.getByText("read from attachment: list.xlsx")).toBeTruthy();
    const items = within(screen.getByRole("table", { name: /requested items/i }));
    expect(items.getByText("24 inch monitor")).toBeTruthy();
    expect(items.getByText("3").className).toContain("tnum");
    expect(screen.getByText(QUOTE_BLOCKER["quote:no_price_list"])).toBeTruthy();
    expect(screen.getByRole("link", { name: "Settings › Price lists" }).getAttribute("href")).toBe("#/settings/prices");
    expect(screen.getByRole("link", { name: "in Invented mailbox" }).getAttribute("href")).toBe("#/workpackages/wp-000000000191");
  });

  it("says a request that can no longer be read", () => {
    const gone: QuoteView = { ...QUOTE, request: null, blockers: [{ code: "quote:request_missing", message: "" }] };
    render(<QuoteStages view={view(gone)} stage="process" onChanged={() => {}} />);
    expect(screen.getByText(QUOTE_BLOCKER["quote:request_missing"])).toBeTruthy();
    expect(screen.queryByRole("table", { name: "The request's data" })).toBeNull();
  });
});
