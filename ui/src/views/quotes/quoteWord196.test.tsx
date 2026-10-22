// 196 (plan F-Word-output W2, DECISIONS 196): the quote's Word document. The language of the quote's documents is
// chosen with its header and sent with the draft; the draft downloads as a Word document once every line is priced,
// and an approved version downloads as the document its approval stored. The local service is replaced by spies;
// invented names only.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type QuoteDraftView, type QuoteView, type WorkpackageView } from "../../api";
import { setLanguage } from "../../i18n";
import { QuoteStages } from "./Quote";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const LINE = {
  id: "l1", row: 0, requested: { description: "24 inch monitor", quantity: "3", unit: "pc" }, sku: "HW-MON-24", description: null,
  unit: null, quantity: "3", unit_price: null, discount_percent: null, note: null, checked: false, checked_by: null, checked_at: null,
  mark: "sure" as const, proposed_sku: "HW-MON-24", candidates: ["HW-MON-24"],
  priced: { sku: "HW-MON-24", name: "Monitor 24 inch", quantity: "3", unit: "pc", list_price: "54900", unit_price: "54900",
    manual_price: false, discount_percent: "0", discount_from: null, net: "164700" },
};
const DRAFT: QuoteDraftView = {
  draft: { price_list: "pl-0123456789", version: 1, header: { customer_name: "Invented Buyer Ltd", note: null }, lines: [LINE],
    started_from: "proposal", request_key: "k", proposal_at: null, language: "hu" },
  state: 4, approval: { active: null, versions: [] }, approved: null, lines: [LINE],
  totals: { net: "164700", vat: "44469", gross: "209169" }, currency: "HUF", vat_percent: "27", blockers: [], warnings: [],
  fingerprint: "f".repeat(64), proposal_newer: false, language: "hu", languages: ["hu", "en"],
  price_list: { price_list: "pl-0123456789", name: "Invented 2026", version: 1, state: "active",
    items: [{ sku: "HW-MON-24", name: "Monitor 24 inch", unit: "pc", unit_price: "54900", category: "hardware" }] },
};
const VERSION = { version: 1, fingerprint: "f".repeat(64), approved_by: "Synthetic reviewer", approved_at: "2026-10-22T09:00:00+00:00",
  reopened_by: null, reopened_at: null, reopen_note: null };

const QUOTE: QuoteView = {
  request: { workpackage_id: "wp-000000000191", item_id: "item-1", kind: "email", title: "Request for monitors", sender: "buyer@example.com",
    received_at: "2026-11-02T10:00:00", parts: [], fields: { customer_name: "Invented Buyer Ltd" }, sources: {},
    items: [{ description: "24 inch monitor", quantity: "3", unit: "pc" }], items_from: 0 },
  source: { workpackage_id: "wp-000000000191", item_id: "item-1", workpackage_name: "Invented mailbox" },
  price_lists: [], blockers: [], proposal: null, proposal_cap: { engine: "jev", items: 1, usd: { jev: "0.003" } }, draft: DRAFT,
};

function view(draft: QuoteDraftView): WorkpackageView {
  return { workpackage: { id: "wp-000000000196", name: "Quote", source_kind: "quote", status: "active" }, quote: { ...QUOTE, draft } } as unknown as WorkpackageView;
}

describe("the quote's Word document (196)", () => {
  it("chooses the documents' language with the header and sends it with the draft", async () => {
    vi.spyOn(api, "packageOutputTemplates").mockResolvedValue({ workpackage_id: "wp-000000000196", outputs: {} } as never);
    const save = vi.spyOn(api, "saveQuoteDraft").mockResolvedValue({ ...DRAFT, state: 5, language: "en" });
    render(<QuoteStages view={view(DRAFT)} stage="review" onChanged={() => {}} />);
    const trigger = screen.getByRole("button", { name: /Language of the quote's documents/ });
    expect(trigger.textContent).toContain("Magyar");
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: /English/ }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const [, sent, state] = save.mock.calls[0];
    expect([sent.language, state]).toEqual(["en", 4]);
  });

  it("downloads the draft as a Word document once every line is priced", () => {
    vi.spyOn(api, "packageOutputTemplates").mockResolvedValue({ workpackage_id: "wp-000000000196", outputs: {} } as never);
    const { rerender } = render(<QuoteStages view={view(DRAFT)} stage="review" onChanged={() => {}} />);
    expect(screen.getByRole("link", { name: "Download the draft (Word)" }).getAttribute("href"))
      .toBe("/api/workpackages/wp-000000000196/quote/draft/quote.docx");
    rerender(<QuoteStages view={view({ ...DRAFT, totals: null })} stage="review" onChanged={() => {}} />);
    expect(screen.queryByRole("link", { name: "Download the draft (Word)" })).toBeNull();
  });

  it("downloads an approved version as the document its approval stored, and an earlier one too", () => {
    const approved: QuoteDraftView = {
      ...DRAFT, approval: { active: { ...VERSION, version: 2 }, versions: [{ ...VERSION, version: 2 }, { ...VERSION, reopened_at: "2026-10-22T10:00:00+00:00", reopened_by: "x", reopen_note: "more" }] },
      approved: { header: { customer_name: "Invented Buyer Ltd" }, totals: DRAFT.totals, currency: "HUF", vat_percent: "27", lines: [],
        price_list: { price_list: "pl-0123456789", name: "Invented 2026", version: 1, fingerprint: "p" }, request: { title: null, key: "k" } },
    };
    render(<QuoteStages view={view(approved)} stage="result" onChanged={() => {}} />);
    expect(screen.getByRole("link", { name: "Download version 2 (Word)" }).getAttribute("href"))
      .toBe("/api/workpackages/wp-000000000196/quote/versions/2/quote.docx");
    const earlier = screen.getAllByRole("link", { name: "Download (Word)" }).map((a) => a.getAttribute("href"));
    expect(earlier).toContain("/api/workpackages/wp-000000000196/quote/versions/1/quote.docx");
  });
});
