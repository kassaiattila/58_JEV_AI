// 143 (DECISIONS 143): the finder of the pairing page's two lists. The owner found the invoice list beside a selected
// statement line hard to read: nothing said which invoice is the line's payment and why. The service compares the
// line with every invoice of the page in code (jav/domains/finance/reconcile_package.py `matches`); this module sorts the invoices
// into three groups and says, per invoice, what matches the line — the name, the invoice number, the account, the
// amount — in words a person checks at a glance.
// - Fitting: the engine's candidates of the line, the invoices the AI chose for it, and those the service says fit.
// - By amount only: the other free invoices, the nearest amount first.
// - Bound or settled: paid (by another line or this one), cancelled by a credit note, proposed for another line, or
//   rejected for this line; closed by default, so the free ones stand out.
// Until the comparison arrives (or when the service cannot give it), the engine's candidates still fit and the rest
// is ordered by amount, as before 143.
import type { ReconcileCandidate, ReconcileInvoice, ReconcileLine, ReconcileMatch } from "../../api";
import { parseCanonical } from "./money";
import { candidateOf, rankedCandidates, rest } from "./pairing";
import { aiChosen, aiPicks } from "./partners";

/** Whether the invoice is still free for the line, and if not, why. */
export type Binding =
  | { kind: "free" } | { kind: "partly_paid" } | { kind: "paid"; lines: string[] } | { kind: "this_line" }
  | { kind: "credited" } | { kind: "proposed_elsewhere"; lines: string[] } | { kind: "rejected" };

/** One criterion of a comparison: matches, loosely matches, does not match, contradicts (another account), unknown. */
export type Verdict = "yes" | "loose" | "no" | "differs" | "unknown";
export interface Criteria { name: Verdict; number: Verdict; account: Verdict; amount: Verdict }

export interface FinderEntry {
  invoice: ReconcileInvoice; match: ReconcileMatch | null; candidate?: ReconcileCandidate;
  ai: { engine: string; probability: number | null }[]; binding: Binding;
  /** a candidate of this line also proposed for another line */
  alsoFor: string[];
}
export interface FinderSections { fits: FinderEntry[]; byAmount: FinderEntry[]; bound: FinderEntry[] }

/** Whether an invoice is still free for the line. */
export function bindingOf(invoice: ReconcileInvoice, line: ReconcileLine): Binding {
  if (line.rejected.includes(invoice.id)) return { kind: "rejected" };
  if (invoice.state === "credited") return { kind: "credited" };
  if (line.allocations.some((a) => a.invoice_id === invoice.id)) return { kind: "this_line" };
  if (rest(invoice) <= 0n) return { kind: "paid", lines: invoice.allocations.map((a) => a.line_id) };
  const elsewhere = invoice.candidates.filter((c) => c.proposed && c.line_id !== line.id).map((c) => c.line_id);
  if (elsewhere.length && !candidateOf(line, invoice.id)) return { kind: "proposed_elsewhere", lines: elsewhere };
  return parseCanonical(invoice.allocated) ? { kind: "partly_paid" } : { kind: "free" };
}

/** What matches the line, from the service's comparison (or the engine's candidate while it has not arrived). */
export function criteria(line: ReconcileLine, invoice: ReconcileInvoice, match: ReconcileMatch | null, candidate?: ReconcileCandidate): Criteria {
  const facts = match ?? candidate;
  if (!facts) return { name: "unknown", number: "unknown", account: "unknown", amount: "unknown" };
  const s = new Set<string>(facts.signals);
  const lineName = Boolean(line.counterparty_name || line.description);
  const lineText = Boolean(line.memo || line.description);
  const relation = facts.amount_relation;
  return {
    name: s.has("supplier_name") || s.has("learned_name") ? "yes" : s.has("supplier_name_fuzzy") ? "loose"
      : invoice.supplier_name && lineName ? "no" : "unknown",
    number: s.has("invoice_number") || s.has("reference") ? "yes" : invoice.number && lineText ? "no" : "unknown",
    account: s.has("supplier_account") ? "yes" : match?.account_differs ? "differs" : "unknown",
    amount: relation === "equal" || relation === "fx_within" || relation === "combined" ? "yes"
      : relation === "different" || relation === "fx_outside" ? "no" : "unknown",
  };
}

const abs = (v: bigint) => (v < 0n ? -v : v);

/** The invoices of the page (`invoices`: after the search and the filters) in the finder's three groups for `line`;
 *  `matches`: the service's comparison of the line, null until it arrives. */
export function finderSections(line: ReconcileLine, invoices: ReconcileInvoice[], matches: Map<string, ReconcileMatch> | null): FinderSections {
  const order = new Map(matches ? [...matches.keys()].map((id, n) => [id, n]) : []);
  const ranked = rankedCandidates(line).map((c) => c.invoice_id);
  const chosen = aiChosen(line);
  const entries = invoices.map((invoice): FinderEntry => {
    const candidate = line.rejected.includes(invoice.id) ? undefined : candidateOf(line, invoice.id);
    const alsoFor = candidate ? invoice.candidates.filter((c) => c.proposed && c.line_id !== line.id).map((c) => c.line_id) : [];
    return { invoice, match: matches?.get(invoice.id) ?? null, candidate, ai: aiPicks(line, invoice.id), binding: bindingOf(invoice, line), alsoFor };
  });
  const bound = entries.filter((e) => !["free", "partly_paid"].includes(e.binding.kind));
  const free = entries.filter((e) => ["free", "partly_paid"].includes(e.binding.kind));
  const fits = free.filter((e) => e.candidate || e.ai.length || e.match?.fit);
  const byAmount = free.filter((e) => !fits.includes(e));
  if (matches) {
    const at = (e: FinderEntry) => order.get(e.invoice.id) ?? Number.MAX_SAFE_INTEGER;
    for (const list of [fits, byAmount, bound]) list.sort((a, b) => at(a) - at(b));
  } else {
    // before the comparison: the engine's ranking, then the AI's own choices; the rest by the nearest amount
    const at = (e: FinderEntry) => {
      const n = ranked.indexOf(e.invoice.id);
      return n >= 0 ? n : ranked.length + chosen.indexOf(e.invoice.id);
    };
    fits.sort((a, b) => at(a) - at(b));
    const target = rest(line);
    const distance = (i: ReconcileInvoice) => abs(rest(i) - target);
    byAmount.sort((a, b) => Number(a.invoice.currency !== line.currency) - Number(b.invoice.currency !== line.currency)
      || (distance(a.invoice) < distance(b.invoice) ? -1 : distance(a.invoice) > distance(b.invoice) ? 1 : 0));
    bound.sort((a, b) => (b.invoice.issue_date ?? "").localeCompare(a.invoice.issue_date ?? ""));
  }
  return { fits, byAmount, bound };
}

/** The days from the invoice's due date to the line's booking day (positive: late; the service's `days_from_due`). */
export function daysFromDue(line: ReconcileLine, invoice: ReconcileInvoice): number | null {
  const day = (s: string | null | undefined) => (s && /^\d{4}-\d{2}-\d{2}/.test(s) ? Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) : null);
  const due = day(invoice.due_date);
  const booked = day(line.booking_date);
  return due === null || booked === null ? null : Math.round((booked - due) / 86_400_000);
}
