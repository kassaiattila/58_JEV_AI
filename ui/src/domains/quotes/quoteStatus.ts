// 195 (plan G-tidy R5): the quote's status lines and summary, apart from the quote's pages, which load only when one is
// opened; 231 (A3d): a case's tabs show them, from the quote view its elements carry (`ui/src/elements/registry.tsx`).
// The amount's form is shared with the quote's editor.
import type { QuoteView } from "./api";
import { getLocale, t } from "../../i18n";
import { fieldLabel } from "../../labels";
import type { Stage } from "../../route";

/** 197: the request's and the quote's fields by the quote request's own names (its customer is the requester). */
export const quoteFieldLabel = (f: string) => fieldLabel(f, "quote_request");

/** An amount in the quote's currency: forints whole, others to cents (as the pricing rounds), grouped. */
export function amountText(v: string | null | undefined, currency: string | null): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  const digits = currency === "HUF" ? 0 : 2;
  return Number.isFinite(n)
    ? n.toLocaleString(getLocale(), { minimumFractionDigits: digits, maximumFractionDigits: Math.max(digits, 2), useGrouping: "always" } as unknown as Intl.NumberFormatOptions)
    : String(v);
}

/** The stages' status lines and the case's summary. */
export function quoteStatus(q: QuoteView | null | undefined): Record<Stage, string> | null {
  if (!q) return null;
  const d = q.draft;
  const active = d.approval.active;
  let review = q.blockers.length ? t("{{n}} gap(s) to clear first", { n: q.blockers.length }) : t("ready to compose");
  if (active) review = t("approved");
  else if (d.draft) review = d.blockers.length ? t("{{n}} line(s), {{m}} to settle", { n: d.lines.length, m: d.blockers.length })
    : t("{{n}} line(s), ready", { n: d.lines.length });
  let result = t("not approved yet");
  if (active) result = t("approved: version {{n}}", { n: active.version });
  else if (d.totals && !d.blockers.length) {
    result = t("{{gross}} {{currency}} gross, to approve", { gross: amountText(d.totals.gross, d.currency), currency: d.currency ?? "" });
  }
  return {
    process: q.request ? t("{{n}} part(s), {{m}} requested item(s)", { n: q.request.parts.length, m: q.request.items.length })
      : t("the request cannot be read"),
    review, result,
  };
}

export function quoteSummary(q: QuoteView | null | undefined): string | null {
  const r = q?.request;
  if (!r) return q ? t("Quote from a request that can no longer be read") : null;
  const customer = r.fields.customer_name ? String(r.fields.customer_name) : null;
  return customer ? t("Quote for {{customer}}: {{title}}", { customer, title: r.title }) : t("Quote: {{title}}", { title: r.title });
}
