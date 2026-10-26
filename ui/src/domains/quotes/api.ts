// The quotes domain: quote requests, quotes and price lists. 231 (C3e): in the domain's folder (until then
// `ui/src/api/quotes.ts`); the domain adds its calls to the shared client when the interface loads (`./index.tsx`), and
// their types and its upload check by declaration merging (below).
import { enc, request } from "../../api/client";
import type { ApprovalState, OwnApproval, OwnVersion } from "../../api/types";
import type { OutputTemplateIssue, OutputTemplateState } from "../../api/outputs";

/** 191 (plan F-quote-package B3): one part of a quote request: the email's own text, an attachment, or a document. */
export interface QuoteRequestPart {
  kind: "email_text" | "attachment" | "document"; name: string; item_id: string | null; doc_id: string;
  values: Record<string, unknown>;
}
/** A requested item as read (the stored quantity is text, "3"). */
export interface QuoteRequestedItem { description?: string | null; quantity?: string | number | null; unit?: string | null }
/** A quote request put together from its parts: each header field with the part it came from (`sources`). */
export interface QuoteRequest {
  workpackage_id: string; item_id: string; kind: "email" | "document"; title: string; sender: string | null;
  received_at: string | null; parts: QuoteRequestPart[]; fields: Record<string, unknown>; sources: Record<string, number>;
  items: QuoteRequestedItem[]; items_from: number | null;
}
export type QuoteBlockerCode = "quote:request_missing" | "quote:no_customer" | "quote:no_items" | "quote:no_price_list";
export interface QuotePriceList {
  price_list: string; name: string; version: number; currency: string; vat_percent: string; items: number;
  discounts: PriceRule[]; fingerprint: string;
}
/** 191 B4c: a requested item's proposed price list item: its mark (sure, to check, not listed; null when it failed),
 *  the item, the likely candidates, how it was decided (code, jev, gpt). */
export interface QuoteMatchAnswer {
  mark: "sure" | "check" | "not_listed" | null; sku?: string | null; name?: string | null; probability?: number | null; candidates?: string[];
  method?: "code" | "jev" | "gpt"; engine?: "jev" | "gpt"; error?: string | null;
}
export interface QuoteProposalLine { row: number; description?: string | null; quantity?: string | number | null; unit?: string | null; answer: QuoteMatchAnswer }
export interface QuoteProposal {
  state: "queued" | "running" | "done" | "failed"; engine: "jev" | "gpt"; price_list: string; version: number;
  requested_by: string; requested_at: string; finished_at: string | null; error: string | null;
  limits: Record<string, string>; lines: QuoteProposalLine[]; stale: boolean;
}
export interface QuoteView {
  request: QuoteRequest | null;
  source: { workpackage_id: string; item_id: string; workpackage_name: string | null } | null;
  price_lists: QuotePriceList[]; blockers: { code: QuoteBlockerCode; message: string }[];
  proposal: QuoteProposal | null;
  /** what a new proposal reserves with the application's engine: provider -> USD */
  proposal_cap: { engine: "jev" | "gpt"; items: number; usd: Record<string, string> };
  /** 192 (B5): the quote as a person composes it, and its approval */
  draft: QuoteDraftView;
  /** 196: the approved version's reply letter (absent from a service older than 196) */
  letter?: QuoteLetterView;
  /** D0-b: the case's steps this view is of (a match, its composition, its letter; "" when the case has none), which
   *  the quote's calls name */
  steps?: QuoteSteps;
}
export interface QuoteSteps { match: string; compose: string; letter: string }
/** 192 (plan F-quote-package B5): a quote line as stored: the page's parts (`QuoteLineIn`) and the service's (its
 *  requested item, the proposal's mark and candidates, who confirmed its item). */
export type QuoteLineMark = "sure" | "check" | "not_listed" | "failed";
export interface QuoteLineIn {
  id: string | null; sku: string | null; description: string | null; unit: string | null; quantity: string | null;
  unit_price: string | null; discount_percent: string | null; note: string | null; checked: boolean;
}
export interface QuoteDraftLine extends QuoteLineIn {
  id: string; row: number | null; requested: { description: string | null; quantity: unknown; unit: string | null } | null;
  checked_by: string | null; checked_at: string | null; mark: QuoteLineMark | null; proposed_sku: string | null;
  candidates: string[];
}
/** A line priced by code (`jav/domains/quotes/quote_pricing.py`): amounts as canonical text. */
export interface QuotePricedLine {
  sku: string | null; name: string; quantity: string; unit: string; list_price: string | null; unit_price: string;
  manual_price: boolean; discount_percent: string; discount_from: "rule" | "manual" | null; net: string;
}
export interface QuoteDraftIn {
  price_list: string; version: number; header: Record<string, string | null>; lines: QuoteLineIn[];
  /** 196: the language of the quote's documents (hu, en) */
  language?: string | null;
}
export interface QuoteDraftContent extends Omit<QuoteDraftIn, "lines"> {
  lines: QuoteDraftLine[]; started_from: "proposal" | "request"; request_key: string; proposal_at: string | null;
}
export type QuoteDraftBlockerCode = "quote:line_no_item" | "quote:line_no_description" | "quote:line_unknown_item"
  | "quote:line_no_quantity" | "quote:line_unchecked" | "quote:line_note_missing" | "quote:no_lines" | "quote:no_customer";
export type QuoteDraftWarningCode = "quote:price_list_superseded" | "quote:request_changed" | "quote:request_missing";
export interface QuoteListItem { sku: string; name: string; unit: string; unit_price: string; category: string | null }
export interface QuoteTotals { net: string; vat: string; gross: string }
/** The quote as an approval records it (`jav/domains/quotes/quote_draft.py` `_content`). */
export interface QuoteApproved {
  header: Record<string, string | null>; totals: QuoteTotals | null; currency: string; vat_percent: string;
  lines: (Partial<Omit<QuotePricedLine, "sku" | "name">> & { id: string; row: number | null; requested: QuoteDraftLine["requested"];
    mark: QuoteLineMark | null; note: string | null; checked_by: string | null; sku: string | null; name: string | null })[];
  price_list: { price_list: string; name: string; version: number; fingerprint: string };
  request: { workpackage_id?: string; item_id?: string; title: string | null; key: string };
  language?: string;  // 196
}
export interface QuoteDraftView {
  draft: QuoteDraftContent | null; state: number; approval: OwnApproval; approved: QuoteApproved | null;
  lines: (QuoteDraftLine & { priced: QuotePricedLine | null })[];
  totals: QuoteTotals | null; currency: string | null; vat_percent: string | null;
  blockers: { code: QuoteDraftBlockerCode; line: string | null; row: number | null }[];
  warnings: { code: QuoteDraftWarningCode; version?: number | null }[];
  fingerprint: string | null;
  price_list: { price_list: string; name: string; version: number; state: string; items: QuoteListItem[] } | null;
  proposal_newer: boolean;
  /** 196: the language of the quote's documents, and the languages it can be */
  language: string | null; languages: string[];
  /** D0-b: the case's composition step it is of */
  step?: string;
  /** D0-d: the approval's state of that step (out of date, returned) */
  approval_state?: ApprovalState;
}
/** 196 (plan F-Word-output W3): the reply letter of the approved version (`jav/domains/quotes/quote_letter.py` `view`): GPT's
 *  paragraph and its state, the code's check of it, the body to accept, the accepted one, and the cap of asking GPT. */
export interface QuoteLetterView {
  version: number | null; state: "queued" | "running" | "done" | "failed" | null; paragraph: string | null;
  problems: string[]; error: string | null; body: string | null; accepted: { body: string; by: string; at: string } | null;
  decision_state: number; to: string | null; subject: string | null; cap: Record<string, string>; usage: unknown;
  /** D0-b: the case's letter step it is of */
  step?: string;
}
/** 191 (plan F-quote-package B2): the columns of a price list file (`configs/price_lists.json`). */
export type PriceListColumn = "sku" | "name" | "unit" | "unit_price" | "category";
/** A price list file's or settings' check: its problems and warnings (where: `Sheet!5`, or `rule 2`), the sheet read,
 *  the header found per column, the number of items and their categories. */
export interface PriceListCheck {
  ok: boolean; problems: OutputTemplateIssue[]; warnings: OutputTemplateIssue[]; sheet: string | null;
  columns: Partial<Record<PriceListColumn, string>>; items: number; categories: string[];
}
/** A rule that lowers a price: a line of the category from the quantity on costs the percent less (stored numbers as
 *  text, "10", "2.5"). */
export interface PriceRule { category: string; min_quantity: string; percent: string }
export interface PriceListVersion {
  price_list: string; name: string; version: number; state: OutputTemplateState; change: "upload" | "settings";
  based_on: number | null; currency: string; vat_percent: string; fingerprint: string; file_name: string; sha256: string;
  made_by: string; made_at: string; activated_by: string | null; activated_at: string | null; retired_by: string | null;
  retired_at: string | null; items: number; discounts: PriceRule[]; check: PriceListCheck;
}
export interface PriceListItem { sku: string; name: string; unit: string; unit_price: string; category: string | null }
/** A version with its items, and the categories its rules may name. */
export interface PriceListDetail extends PriceListVersion { item_rows: PriceListItem[]; categories: string[] }
/** A price list with its versions, newest first; `active`: the active version's number. */
export interface PriceList { price_list: string; name: string; active: number | null; retired: boolean; versions: PriceListVersion[] }
export interface PriceListsListing {
  price_lists: PriceList[]; currencies: string[]; currency: string; vat_percent: string;
  columns: Record<PriceListColumn, { required: boolean; headers: string[] }>;
}

/** D0-b: the case's step a quote call is about, as the address's query (none: the case's first such step) */
const atStep = (step?: string) => (step ? `?step=${enc(step)}` : "");

export const quotesApi = {
  /** 191 B4c: queues the quote's proposal (the worker makes it); D0-b: of the case's match `step` */
  requestQuoteProposal: (wpId: string, step?: string) =>
    request<QuoteProposal>("POST", `/workpackages/${enc(wpId)}/quote/proposal${atStep(step)}`, {}),
  /** 192 B5: the quote's draft started, saved after a change (with the state the page read), approved and reopened;
   *  D0-b: of the case's composition `step` */
  startQuoteDraft: (wpId: string, body: { source: "proposal" | "request"; expected_state: number; replace?: boolean }, step?: string) =>
    request<QuoteDraftView>("POST", `/workpackages/${enc(wpId)}/quote/draft/start${atStep(step)}`, body),
  saveQuoteDraft: (wpId: string, draft: QuoteDraftIn, expectedState: number, step?: string) =>
    request<QuoteDraftView>("PUT", `/workpackages/${enc(wpId)}/quote/draft${atStep(step)}`, { draft, expected_state: expectedState }),
  approveQuote: (wpId: string, fingerprint: string, step?: string) =>
    request<QuoteDraftView>("POST", `/workpackages/${enc(wpId)}/quote/approve${atStep(step)}`, { fingerprint }),
  reopenQuote: (wpId: string, note: string, step?: string) =>
    request<QuoteDraftView>("POST", `/workpackages/${enc(wpId)}/quote/reopen${atStep(step)}`, { note }),
  quoteVersion: (wpId: string, version: number) =>
    request<OwnVersion & { quote: QuoteApproved }>("GET", `/workpackages/${enc(wpId)}/quote/versions/${version}`),
  /** 196: the quote as a Word document: the draft's (marked as a draft) and an approved version's as it was stored */
  quoteDraftDocxUrl: (wpId: string, step?: string) => `/api/workpackages/${enc(wpId)}/quote/draft/quote.docx${atStep(step)}`,
  quoteVersionDocxUrl: (wpId: string, version: number) => `/api/workpackages/${enc(wpId)}/quote/versions/${version}/quote.docx`,
  /** 196 W3: the reply letter: GPT's paragraph asked, the body accepted (with the state the page read), the letter file;
   *  D0-b: of the case's letter `step` */
  requestQuoteLetterParagraph: (wpId: string, step?: string) =>
    request<QuoteLetterView>("POST", `/workpackages/${enc(wpId)}/quote/letter/paragraph${atStep(step)}`, {}),
  acceptQuoteLetter: (wpId: string, body: string, expectedState: number, step?: string) =>
    request<QuoteLetterView>("PUT", `/workpackages/${enc(wpId)}/quote/letter${atStep(step)}`, { body, expected_state: expectedState }),
  quoteLetterEmlUrl: (wpId: string, version: number, step?: string) =>
    `/api/workpackages/${enc(wpId)}/quote/versions/${version}/letter.eml${atStep(step)}`,
  /** 191 (plan F-quote-package B2): the seller's price lists; an upload is read by the service from the path the
   *  system's file picker chose, and a refused file gives 422 `price_list_refused` with the check (`ApiError.check`) */
  priceLists: () => request<PriceListsListing>("GET", "/price-lists"),
  uploadPriceList: (body: { name: string; path: string; price_list?: string; currency?: string; vat_percent?: string }) =>
    request<PriceListVersion>("POST", "/price-lists", body),
  priceListVersion: (priceList: string, version: number) =>
    request<PriceListDetail>("GET", `/price-lists/${enc(priceList)}/versions/${version}`),
  /** the rules, the currency and the VAT rate as a new draft version (409 `price_list_state` when nothing changes) */
  changePriceListSettings: (priceList: string, version: number, body: { discounts: PriceRule[]; currency: string; vat_percent: string }) =>
    request<PriceListVersion>("POST", `/price-lists/${enc(priceList)}/versions/${version}/settings`, body),
  activatePriceList: (priceList: string, version: number) =>
    request<PriceListVersion>("POST", `/price-lists/${enc(priceList)}/versions/${version}/activate`, {}),
  retirePriceList: (priceList: string) => request<PriceListVersion>("POST", `/price-lists/${enc(priceList)}/retire`, {}),
  priceListFileUrl: (priceList: string, version: number) => `/api/price-lists/${enc(priceList)}/versions/${version}/file`,
  /** 178/179 (plan 170 L4): own output templates, and a package's choice of them */
};

type QuotesCalls = typeof quotesApi;
declare module "../../api" {
  interface DomainCalls extends QuotesCalls {}
}
declare module "../../api/client" {
  interface UploadChecks { price_list: PriceListCheck }
}
