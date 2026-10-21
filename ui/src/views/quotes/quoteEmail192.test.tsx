// 192 (plan F-quote-package B6a, DECISIONS 191, 192): the quote request under its email in a mailbox package - the
// request put together from the email's parts (each value with the part it came from), what the whole request lacks,
// the quotes already made from it, and a quote started from there. The email's page shows it through the item part
// registry; the next step's name says the extraction reads the email's text too. Spies for the service; invented names.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type ItemResult, type QuoteEmailPart } from "../../api";
import { setLanguage } from "../../i18n";
import { nextFlowText } from "../../labels";
import { ITEM_PARTS } from "../../logic/registry";
import { EmailReview } from "../../review/EmailReview";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); window.location.hash = ""; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const PART: QuoteEmailPart = {
  request: {
    workpackage_id: "wp-000000000191", item_id: "item-1", kind: "email", title: "Request for monitors", sender: "buyer@example.com",
    received_at: "2026-11-02T10:00:00",
    parts: [
      { kind: "email_text", name: "Request for monitors", item_id: null, doc_id: "d1", values: {} },
      { kind: "attachment", name: "list.pdf", item_id: "item-2", doc_id: "d2", values: {} },
    ],
    fields: { customer_name: "Invented Buyer Ltd", deadline: null }, sources: { customer_name: 0 },
    items: [{ description: "24 inch monitor", quantity: "3", unit: "pc" }], items_from: 1,
  },
  gaps: [], quotes: [], source: { workpackage_id: "wp-000000000191", item_id: "item-1" },
};

function mail(part: QuoteEmailPart | null): ItemResult {
  return {
    run_id: "run-1", item_id: "item-1", kind: "email", extraction: null, correction: null, source: null, provenance: {},
    open_reasons: [], earlier_open_reasons: [],
    email: { subject: "Request for monitors", sender: "buyer@example.com", sender_name: null, to: [], received_at: null, mailbox: null,
      body: "Please quote 3 monitors.", attachments: ["list.pdf"],
      result: { intent: "quote_request", intent_label: "Quote request", confidence: 0.98, next_flow: "m2:quote_request", next_flow_reads_text: true,
        attachments: [{ filename: "list.pdf", doc_type: "quote_request" }], from_this_run: true, signals: {} } },
    ...(part ? { parts: { quote_request: part } } : {}),
  } as unknown as ItemResult;
}

describe("the quote request under its email (192)", () => {
  it("is shown on the email's page through the item part registry", () => {
    expect(Object.keys(ITEM_PARTS)).toEqual(["quote_request"]);
    render(<EmailReview data={mail(PART)} onChanged={() => {}} wpId="wp-000000000191" />);
    const part = screen.getByRole("region", { name: "Quote request" });
    expect(part.textContent).toContain("Invented Buyer Ltd");
    expect(part.textContent).toContain("read from list.pdf"); // the items came from the attachment, named by its file
    expect(screen.getByText("The request has what a quote needs.")).toBeTruthy();
    expect(screen.getByText("Data extraction from the email and its attachments (Quote request)")).toBeTruthy();
  });

  it("is not shown for an email that is no quote request", () => {
    render(<EmailReview data={mail(null)} onChanged={() => {}} />);
    expect(screen.queryByRole("region", { name: "Quote request" })).toBeNull();
  });

  it("starts a quote named by the customer and opens it", async () => {
    const create = vi.spyOn(api, "createQuotePackage").mockResolvedValue({ workpackage_id: "wp-000000000196" });
    render(<EmailReview data={mail(PART)} onChanged={() => {}} />);
    const button = screen.getByRole("button", { name: "Start a quote from this email" });
    expect(button.className).toContain("primary");
    fireEvent.click(button);
    await waitFor(() => expect(create).toHaveBeenCalledWith({ name: "Quote: Invented Buyer Ltd", source: "wp-000000000191", item_id: "item-1" }));
    await waitFor(() => expect(window.location.hash).toBe("#/workpackages/wp-000000000196/review"));
  });

  it("says what the whole request lacks, and links the quotes already made from it", () => {
    const lacking: QuoteEmailPart = { ...PART, gaps: [{ code: "quote:no_items", message: "" }], quotes: [{ id: "wp-000000000197", name: "Earlier quote" }] };
    render(<EmailReview data={mail(lacking)} onChanged={() => {}} />);
    expect(screen.getByText("The request names no item: neither the email's text nor an attachment has one").className).toContain("s-review");
    expect(screen.getByRole("link", { name: "Earlier quote" }).getAttribute("href")).toBe("#/workpackages/wp-000000000197/review");
    expect(screen.getByRole("button", { name: "Start another quote from this email" }).className).toContain("secondary");
  });

  it("names the next step by what the type reads", () => {
    expect(nextFlowText("m2:quote_request", true)).toBe("Data extraction from the email and its attachments (Quote request)");
    expect(nextFlowText("m2:invoice_hu")).toMatch(/^Data extraction from the attachment \(/);
  });
});
