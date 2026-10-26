// 231 (plan stage C, C1a; DECISIONS 231): what an email may start, on its own page in a mailbox package - every process
// whose intake takes it, with the record put together from the email's parts (each value with the part it came from),
// what the record lacks as a whole, the cases already started from it, and a case started from there. The page names no
// process (until C1a the quote's own card, 192 B6a); the next step's name says the extraction reads the email's text too.
// Spies for the service; invented names.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type IntakeOffer, type ItemResult } from "../api";
import { setLanguage } from "../i18n";
import { nextFlowText } from "../labels";
import { ITEM_PARTS } from "../logic/registry";
import { EmailReview } from "../review/EmailReview";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); window.location.hash = ""; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const OFFER: IntakeOffer = {
  pack: "invented_quote", title: "IT quote", starts: "offer", record: { workpackage_id: "wp-000000000191", item_id: "item-1" },
  preview: {
    title: "Request for monitors",
    parts: [{ kind: "email_text", name: "Request for monitors" }, { kind: "attachment", name: "list.pdf" }],
    fields: { customer_name: "Invented Buyer Ltd", deadline: null }, sources: { customer_name: 0 },
    items: [{ description: "24 inch monitor", quantity: "3", unit: "pc" }], items_from: 1,
  },
  list_field: "requested_items", record_type: "quote_request", gaps: [], label: "Invented Buyer Ltd", cases: [],
};

function mail(offers: IntakeOffer[]): ItemResult {
  return {
    run_id: "run-1", item_id: "item-1", kind: "email", extraction: null, correction: null, source: null, provenance: {},
    open_reasons: [], earlier_open_reasons: [],
    email: { subject: "Request for monitors", sender: "buyer@example.com", sender_name: null, to: [], received_at: null, mailbox: null,
      body: "Please quote 3 monitors.", attachments: ["list.pdf"],
      result: { intent: "quote_request", intent_label: "Quote request", confidence: 0.98, next_flow: "m2:quote_request", next_flow_reads_text: true,
        attachments: [{ filename: "list.pdf", doc_type: "quote_request" }], from_this_run: true, signals: {} } },
    intake: offers,
  } as unknown as ItemResult;
}

describe("what an email may start (231 C1a)", () => {
  it("shows each process that takes the email, with the record it would start from", async () => {
    expect(Object.keys(ITEM_PARTS)).toEqual([]);  // no domain's own part under an email
    render(<EmailReview data={mail([OFFER])} onChanged={() => {}} wpId="wp-000000000191" />);
    const offer = await screen.findByRole("region", { name: "IT quote" });
    expect(offer.textContent).toContain("Invented Buyer Ltd");
    expect(offer.textContent).toContain("read from list.pdf"); // the list came from the attachment, named by its file
    expect(screen.getByText("The record has what a case needs.")).toBeTruthy();
    expect(screen.getByText("Data extraction from the email and its attachments (Quote request)")).toBeTruthy();
  });

  it("shows nothing for an email no process takes", () => {
    render(<EmailReview data={mail([])} onChanged={() => {}} />);
    expect(screen.queryByRole("region", { name: "IT quote" })).toBeNull();
  });

  it("starts a case named by the process and the record, and opens it", async () => {
    const create = vi.spyOn(api, "startCase").mockResolvedValue({ case_id: "wp-000000000196" });
    render(<EmailReview data={mail([OFFER])} onChanged={() => {}} />);
    const button = await screen.findByRole("button", { name: "Start a case from this email" });
    expect(button.className).toContain("primary");
    fireEvent.click(button);
    await waitFor(() => expect(create).toHaveBeenCalledWith({ pack: "invented_quote", name: "IT quote: Invented Buyer Ltd",
      record: { workpackage_id: "wp-000000000191", item_id: "item-1" } }));
    await waitFor(() => expect(window.location.hash).toBe("#/cases/wp-000000000196"));
  });

  it("says what the whole record lacks, and links the cases already started from it", async () => {
    const lacking: IntakeOffer = { ...OFFER, gaps: [{ code: "quote:no_items", message: "The request names no item" }],
      cases: [{ id: "wp-000000000197", name: "Earlier quote" }] };
    render(<EmailReview data={mail([lacking])} onChanged={() => {}} />);
    expect((await screen.findByText("The request names no item")).className).toContain("s-review");
    expect(screen.getByRole("link", { name: "Earlier quote" }).getAttribute("href")).toBe("#/cases/wp-000000000197");
    expect(screen.getByRole("button", { name: "Start another case from this email" }).className).toContain("secondary");
  });

  it("names the next step by what the type reads", () => {
    expect(nextFlowText("m2:quote_request", true)).toBe("Data extraction from the email and its attachments (Quote request)");
    expect(nextFlowText("m2:invoice_hu")).toMatch(/^Data extraction from the attachment \(/);
  });
});
