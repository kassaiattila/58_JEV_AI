// 231 (plan stage A, A6; DECISIONS 231): a process pack's case page: its pack's tabs, each built from registered screen
// elements; the quote's elements render the quote package's parts from the quote view their data carries, with the
// quote package's status lines; asking for the proposal starts the case's step. Synthetic data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor, type CaseView } from "../api";
import type { QuoteView } from "../domains/quotes/api";
import { setLanguage } from "../i18n";
import { CasePage } from "./CasePage";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const QUOTE: QuoteView = {
  request: {
    workpackage_id: "wp-000000000191", item_id: "item-1", kind: "email", title: "Request for monitors", sender: "buyer@example.com",
    received_at: "2026-11-02T10:00:00", parts: [{ kind: "email_text", name: "Request for monitors", item_id: null, doc_id: "d1", values: {} }],
    fields: { customer_name: "Invented Buyer Ltd", deadline: null }, sources: { customer_name: 0 },
    items: [{ description: "24 inch monitor", quantity: "3", unit: "pc" }], items_from: 0,
  },
  source: { workpackage_id: "wp-000000000191", item_id: "item-1", workpackage_name: "Invented mailbox" },
  price_lists: [{ price_list: "pl-0123456789", name: "Invented 2026", version: 2, currency: "HUF", vat_percent: "27", items: 24,
                  discounts: [], fingerprint: "f" }],
  blockers: [], proposal: null, proposal_cap: { engine: "jev", items: 1, usd: { jev: "0.003" } },
  draft: { draft: null, state: 0, approval: { active: null, versions: [] }, approved: null, lines: [], totals: null, currency: null,
           vat_percent: null, blockers: [], warnings: [], fingerprint: null, price_list: null, proposal_newer: false, language: null,
           languages: ["hu", "en"] },
};
const step = (state: string, extra: Partial<CaseView["steps"][string]> = {}) => ({
  title: null, uses: "x@1", start: "auto" as const, state, phase: null, waiting_for: null, awaiting_start: false, note: null, result: null, ...extra,
});
const PAGE: CaseView = {
  case: { id: "wp-000000000231", pack: "it_quote", version: "1.0.0", title: "IT quote", name: "Quote: Invented Buyer Ltd", status: "open" },
  steps: { request: step("done"), match: step("running", { start: "person", awaiting_start: true, phase: "awaiting_start" }),
           compose: step("waiting"), document: step("waiting"), letter: step("waiting") },
  tabs: [
    { id: "request", label: "Request", elements: [{ type: "record_view", step: "request", data: { quote: QUOTE } }] },
    { id: "quote", label: "Quote", elements: [{ type: "match_proposal", step: "match", data: { quote: QUOTE } },
                                               { type: "line_editor", step: "compose", data: { quote: QUOTE } }] },
    { id: "approval", label: "Approval", elements: [{ type: "approval", step: "compose", letter_step: "letter", data: { quote: QUOTE } }] },
  ],
  next: { code: "quote_propose", label: "Ask for the proposal", stage: "review", tab: "quote" },
};

describe("a process pack's case (231)", () => {
  it("shows its pack's tabs with the quote's status lines and opens the tab of its first open step", async () => {
    vi.spyOn(api, "casePage").mockResolvedValue(PAGE);
    render(<CasePage caseId="wp-000000000231" />);
    expect(await screen.findByRole("heading", { name: "Quote: Invented Buyer Ltd" })).toBeTruthy();
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((x) => x.textContent)).toEqual([expect.stringContaining("Request"), expect.stringContaining("Quote"),
                                                    expect.stringContaining("Approval")]);
    expect(tabs[0].textContent).toContain("1 part(s), 1 requested item(s)");
    expect(tabs[1].getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByRole("button", { name: /Ask for the proposal/ })).toBeTruthy();
    // the header's next step, as on a work package's page: a button beside the panel's own, until a tab is chosen
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Ask for the proposal/ })).toHaveLength(2));
  });

  it("asks for the proposal by starting the case's step", async () => {
    vi.spyOn(api, "casePage").mockResolvedValue(PAGE);
    const start = vi.spyOn(api, "startCaseStep").mockResolvedValue(PAGE);
    const direct = vi.spyOn(api, "requestQuoteProposal");
    render(<CasePage caseId="wp-000000000231" tab="quote" />);
    // on the next step's own tab the header only names it
    expect(await screen.findByText(/Ask for the proposal/, { selector: ".next-hint" })).toBeTruthy();
    fireEvent.click(await screen.findByRole("button", { name: /Ask for the proposal/ }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("wp-000000000231", "match"));
    expect(direct).not.toHaveBeenCalled();
  });

  it("says when there is no such case", async () => {
    vi.spyOn(api, "casePage").mockRejectedValue(new ApiError(404, "not_found", "not found"));
    render(<CasePage caseId="wp-000000000000" />);
    expect(await screen.findByRole("heading", { name: "The case was not found" })).toBeTruthy();
  });
});
