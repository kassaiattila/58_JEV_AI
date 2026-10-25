// 191 (plan F-quote-package B3, DECISIONS 191): the quote as a kind of work - its form in the new work wizard (a quote
// request already processed, chosen from the service's search, with the quotes already made from it) and its package's
// Request stage (the request's fields with the part each came from, its items, its gaps, the active price list). The
// local service is replaced by spies; invented names only.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type QuoteProposal, type QuoteRequestCandidate, type QuoteView, type WorkpackageView } from "../../api";
import { setLanguage } from "../../i18n";
import { PACKAGE_PARTS } from "../../logic/packageParts";
import { hasOwnForm } from "../../logic/steps";
import { stepLabel } from "../../labels";
import { QUOTE_BLOCKER, QuoteCreate } from "./Quote";
import { Approval, LineEditor, MatchProposal, RecordView } from "./QuoteElements";
import { quoteStatus } from "./quoteStatus";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const CANDIDATE: QuoteRequestCandidate = {
  workpackage_id: "wp-000000000191", workpackage_name: "Invented mailbox", item_id: "item-1", kind: "email",
  title: "Request for monitors", sender: "buyer@example.com", received_at: "2026-11-02T10:00:00", customer_name: "Invented Buyer Ltd",
  items: 1, quotes: [{ id: "wp-000000000192", name: "Earlier quote" }],
};

// 192: a quote without a draft yet
const NO_DRAFT: QuoteView["draft"] = {
  draft: null, state: 0, approval: { active: null, versions: [] }, approved: null, lines: [], totals: null, currency: null,
  vat_percent: null, blockers: [], warnings: [], fingerprint: null, price_list: null, proposal_newer: false,
  language: null, languages: ["hu", "en"],
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
  proposal: null, proposal_cap: { engine: "jev", items: 1, usd: { jev: "0.003" } }, draft: NO_DRAFT,
};

const READY: QuoteView = {
  ...QUOTE, blockers: [],
  price_lists: [{ price_list: "pl-0123456789", name: "Invented 2026", version: 2, currency: "HUF", vat_percent: "27", items: 24,
                  discounts: [], fingerprint: "f" }],
  proposal_cap: { engine: "jev", items: 2, usd: { jev: "0.006" } },
};

const PROPOSAL: QuoteProposal = {
  state: "done", engine: "jev", price_list: "pl-0123456789", version: 2, requested_by: "Synthetic reviewer",
  requested_at: "2026-11-02T10:00:00+00:00", finished_at: "2026-11-02T10:00:05+00:00", error: null, limits: { jev: "0.006" },
  stale: true,
  lines: [
    { row: 0, description: "24 inch monitor", quantity: "3", unit: "pc", answer: { mark: "sure", sku: "HW-MON-24", candidates: ["HW-MON-24"], method: "jev" } },
    { row: 1, description: "2 monitors", quantity: "2", unit: "pc", answer: { mark: "check", sku: "HW-MON-24", candidates: ["HW-MON-24", "HW-MON-27"], method: "jev" } },
    { row: 2, description: "2 tablets", quantity: "2", unit: "pc", answer: { mark: "not_listed", sku: null, candidates: [], method: "jev" } },
  ],
};

function view(quote: QuoteView): WorkpackageView {
  return { workpackage: { id: "wp-000000000193", name: "Quote", source_kind: "quote" }, quote } as unknown as WorkpackageView;
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

describe("the quote package (191)", () => {
  it("is a kind of work with its own form; the quote package's page is gone (231 A3d)", () => {
    expect(hasOwnForm("quote")).toBe(true);
    expect(PACKAGE_PARTS.quote).toBeUndefined();  // 231 (C3b5a): the logic packs' registry went
    expect(quoteStatus(QUOTE)).toEqual({ process: "2 part(s), 1 requested item(s)", review: "1 gap(s) to clear first",
      result: "not approved yet" });
    expect(stepLabel("quote_request_check", { n: 2 }, "")).toBe("Check the request: 2 gap(s)");
    expect(stepLabel("quote_compose", {}, "")).toBe("Compose the quote");
  });

  it("chooses a request found by the service, warns of a quote already made, and names the quote by its customer", async () => {
    const search = vi.spyOn(api, "quoteRequests").mockResolvedValue({ requests: [CANDIDATE] });
    const create = vi.spyOn(api, "startCase").mockResolvedValue({ case_id: "wp-000000000194" });  // 231 (A6c): a case
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
    await waitFor(() => expect(create).toHaveBeenCalledWith({ pack: "it_quote", name: "Quote: Invented Buyer Ltd",
      record: { workpackage_id: "wp-000000000191", item_id: "item-1" } }));
    await waitFor(() => expect(window.location.hash).toBe("#/cases/wp-000000000194"));
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

  it("asks for the proposal with its cost cap, and shows each line's mark and other candidates", async () => {
    const ask = vi.spyOn(api, "requestQuoteProposal").mockResolvedValue({ ...PROPOSAL, state: "queued", lines: [] });
    const changed = vi.fn();
    const { rerender } = render(<QuoteStages view={view(READY)} stage="review" onChanged={changed} />);
    const button = screen.getByRole("button", { name: "Ask for the proposal" });
    expect(button.className).toContain("primary");
    expect(button.querySelector(".spend")?.textContent).toBe("≤ 0.0060 USD"); // a cap below a cent keeps its digits
    fireEvent.click(button);
    await waitFor(() => expect(ask).toHaveBeenCalledWith("wp-000000000193"));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    rerender(<QuoteStages view={view({ ...READY, proposal: PROPOSAL })} stage="review" onChanged={changed} />);
    // a stale proposal is asked again as the view's main action; a current one leaves that to composing the quote
    expect(screen.getByRole("button", { name: "Ask for a new proposal" }).className).toContain("primary");
    expect(screen.getByText("the request or the price list changed since").className).toContain("s-warn");
    const rows = within(screen.getByRole("table", { name: "Proposed lines" })).getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("sure").className).toContain("s-done");
    expect(within(rows[1]).getByText("to check").className).toContain("s-review");
    expect(within(rows[1]).getByText("HW-MON-27")).toBeTruthy();
    expect(within(rows[2]).getByText("not in the price list").className).toContain("s-warn");
    rerender(<QuoteStages view={view({ ...READY, proposal: { ...PROPOSAL, stale: false } })} stage="review" onChanged={changed} />);
    expect(screen.getByRole("button", { name: "Ask for a new proposal" }).className).toContain("secondary");
  });

  it("does not ask while a gap is open, and asks the page again while the proposal is being made", () => {
    vi.useFakeTimers();
    try {
      const changed = vi.fn();
      render(<QuoteStages view={view({ ...READY, proposal: { ...PROPOSAL, state: "running", lines: [] } })} stage="review" onChanged={changed} />);
      expect(screen.getByRole("button", { name: "Ask for a new proposal" })).toHaveProperty("disabled", true);
      vi.advanceTimersByTime(4100);
      expect(changed).toHaveBeenCalledTimes(2);
      cleanup();
      render(<QuoteStages view={view(QUOTE)} stage="review" onChanged={changed} />);
      expect(screen.getByRole("button", { name: "Ask for the proposal" })).toHaveProperty("disabled", true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("says a request that can no longer be read", () => {
    const gone: QuoteView = { ...QUOTE, request: null, blockers: [{ code: "quote:request_missing", message: "" }] };
    render(<QuoteStages view={view(gone)} stage="process" onChanged={() => {}} />);
    expect(screen.getByText(QUOTE_BLOCKER["quote:request_missing"])).toBeTruthy();
    expect(screen.queryByRole("table", { name: "The request's data" })).toBeNull();
  });
});
