// 135 (plan 134 P2): the filters that narrow the two lists of the pairing page — the lines by partner, the AI's kind of
// payment, direction and amount; the other invoices by supplier, own party, currency, state, issue date, amount (or
// near the selected line's amount) and whether they have a candidate. They narrow what is shown only; the selected
// line's candidates always stand at the top of the invoice list.
import type { ReconcileInvoice, ReconcileLine } from "../../api";
import { fold } from "../../labels";
import { parseCanonical, parseInput } from "./money";
import { kinds } from "./partners";
import { rest } from "./pairing";

export interface LineFilters { partner: string; kind: string; direction: "" | "debit" | "credit"; min: string; max: string }
export interface InvoiceFilters {
  supplier: string; party: string; currency: string; state: string; from: string; to: string; min: string; max: string;
  near: boolean; nearPct: string; withCandidates: boolean;
}

export const NO_LINE_FILTERS: LineFilters = { partner: "", kind: "", direction: "", min: "", max: "" };
export const NO_INVOICE_FILTERS: InvoiceFilters = {
  supplier: "", party: "", currency: "", state: "", from: "", to: "", min: "", max: "", near: false, nearPct: "10", withCandidates: false,
};
export const NO_PARTY = "-"; // the party filter's value for the invoices no own party claims

/** How many filters are set (the toggle's count). */
export function activeCount(f: LineFilters | InvoiceFilters): number {
  return Object.entries(f).filter(([k, v]) => k !== "nearPct" && v !== "" && v !== false).length;
}

/** The supplier key the supplier filter compares: the name folded (case and accents). */
export const supplierKey = (i: ReconcileInvoice) => fold((i.supplier_name ?? "").trim());

const abs = (v: bigint) => (v < 0n ? -v : v);

function inRange(value: bigint | null, min: string, max: string): boolean {
  const lo = min.trim() ? parseInput(min) : null;
  const hi = max.trim() ? parseInput(max) : null;
  if (lo === null && hi === null) return true;
  if (value === null) return false;
  return (lo === null || value >= lo) && (hi === null || value <= hi);
}

export function lineMatches(f: LineFilters, l: ReconcileLine): boolean {
  if (f.partner && l.partner !== f.partner) return false;
  if (f.kind && !kinds(l).some((k) => k.kind === f.kind)) return false;
  if (f.direction && l.direction !== f.direction) return false;
  const amount = parseCanonical(l.amount);
  return inRange(amount === null ? null : abs(amount), f.min, f.max);
}

/** `target`: the selected line, for "near its amount" (an invoice of its currency whose rest is within the share). */
export function invoiceMatches(f: InvoiceFilters, i: ReconcileInvoice, target: ReconcileLine | null): boolean {
  if (f.supplier && supplierKey(i) !== f.supplier) return false;
  if (f.party && (f.party === NO_PARTY ? Boolean(i.party) : i.party?.id !== f.party)) return false;
  if (f.currency && i.currency !== f.currency) return false;
  if (f.state && i.state !== f.state) return false;
  const day = (i.issue_date ?? "").slice(0, 10);
  if ((f.from && (!day || day < f.from)) || (f.to && (!day || day > f.to))) return false;
  if (f.withCandidates && !i.candidates.length) return false;
  if (!inRange(parseCanonical(i.amount), f.min, f.max)) return false;
  if (f.near && target) {
    if (i.currency !== target.currency) return false;
    const pct = Number((f.nearPct || "0").replace(",", "."));
    const want = rest(target);
    const slack = (want * BigInt(Math.round(Math.max(0, pct) * 100))) / 10000n;
    if (abs(rest(i) - want) > slack) return false;
  }
  return true;
}
