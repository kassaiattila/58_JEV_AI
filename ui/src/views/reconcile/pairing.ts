// 132: what a selection of statement lines and invoices would pair, before anything is sent. It mirrors the service's
// rules (jav/reconcile_package.py `allocate`), so the page can say in advance what is missing; the service checks
// everything again.
// - One line pays one or more invoices, or one invoice is paid by one or more lines (instalments); several on both
//   sides at once is not a pairing a person can check.
// - In one currency each pair gets an amount: by default what is left on both sides, in the order of the selection.
//   A step that leaves a rest on a line or an invoice it touches needs a reason.
// - A card line and an invoice of another currency pair only in whole, one to one; outside the card band or without
//   an exchange rate it needs a reason.
import type { ReconcileAllocationPair, ReconcileCandidate, ReconcileInvoice, ReconcileLine } from "../../api";
import { canonical, min, parseCanonical } from "./money";

export interface PlannedPair { line: ReconcileLine; invoice: ReconcileInvoice; amount: bigint | null } // null: whole, converted
export type Refusal =
  | "nothing" | "many_to_many" | "line_marked" | "line_excluded" | "line_settled" | "invoice_settled" | "currency" | "too_many";
export type Plan =
  | { ok: true; pairs: PlannedPair[]; converted: boolean; needsReason: boolean; exact: boolean }
  | { ok: false; why: Refusal };

export const rest = (x: { rest: string | null }): bigint => parseCanonical(x.rest) ?? 0n;

export function candidateOf(line: ReconcileLine, invoiceId: string): ReconcileCandidate | undefined {
  return line.candidates.find((c) => c.invoice_id === invoiceId);
}

/** The default plan of a selection (`lines` and `invoices` in the order they were selected). */
export function planPairing(lines: ReconcileLine[], invoices: ReconcileInvoice[]): Plan {
  if (!lines.length || !invoices.length) return { ok: false, why: "nothing" };
  if (lines.length > 1 && invoices.length > 1) return { ok: false, why: "many_to_many" };
  if (lines.some((l) => l.state === "marked")) return { ok: false, why: "line_marked" };
  if (lines.some((l) => l.state === "excluded")) return { ok: false, why: "line_excluded" };
  if (lines.some((l) => rest(l) <= 0n)) return { ok: false, why: "line_settled" };
  if (invoices.some((i) => rest(i) <= 0n)) return { ok: false, why: "invoice_settled" };
  const currencies = new Set([...lines.map((l) => l.currency), ...invoices.map((i) => i.currency)]);
  if (currencies.size > 1) {
    const [line] = lines;
    const [invoice] = invoices;
    const relation = lines.length === 1 && invoices.length === 1 ? candidateOf(line, invoice.id)?.amount_relation : undefined;
    const whole = parseCanonical(line?.allocated) === 0n && parseCanonical(invoice?.allocated) === 0n;
    if (!relation || !["fx_within", "fx_outside", "no_rate"].includes(relation) || !whole) return { ok: false, why: "currency" };
    return { ok: true, pairs: [{ line, invoice, amount: null }], converted: true, needsReason: relation !== "fx_within", exact: relation === "fx_within" };
  }
  const pairs: PlannedPair[] = [];
  if (lines.length === 1) {
    let left = rest(lines[0]);
    for (const invoice of invoices) {
      const share = min(left, rest(invoice));
      if (share <= 0n) return { ok: false, why: "too_many" };
      pairs.push({ line: lines[0], invoice, amount: share });
      left -= share;
    }
  } else {
    let left = rest(invoices[0]);
    for (const line of lines) {
      const share = min(left, rest(line));
      if (share <= 0n) return { ok: false, why: "too_many" };
      pairs.push({ line, invoice: invoices[0], amount: share });
      left -= share;
    }
  }
  return check(pairs);
}

/** The plan of one currency with the amounts a person set: every amount above zero and within what both sides have
 *  left. */
export function check(pairs: PlannedPair[]): Plan {
  const usedLine = new Map<string, bigint>();
  const usedInvoice = new Map<string, bigint>();
  for (const p of pairs) {
    if (p.amount === null || p.amount <= 0n) return { ok: false, why: "nothing" };
    usedLine.set(p.line.id, (usedLine.get(p.line.id) ?? 0n) + p.amount);
    usedInvoice.set(p.invoice.id, (usedInvoice.get(p.invoice.id) ?? 0n) + p.amount);
  }
  const lines = new Map(pairs.map((p) => [p.line.id, p.line]));
  const invoices = new Map(pairs.map((p) => [p.invoice.id, p.invoice]));
  const leftLine = [...usedLine].map(([id, used]) => rest(lines.get(id)!) - used);
  const leftInvoice = [...usedInvoice].map(([id, used]) => rest(invoices.get(id)!) - used);
  if (leftLine.some((v) => v < 0n)) return { ok: false, why: "line_settled" };
  if (leftInvoice.some((v) => v < 0n)) return { ok: false, why: "invoice_settled" };
  const exact = [...leftLine, ...leftInvoice].every((v) => v === 0n);
  return { ok: true, pairs, converted: false, needsReason: !exact, exact };
}

/** The pairs as the service takes them: one amount per pair in one currency, none for a converted pair. */
export function toRequest(pairs: PlannedPair[]): ReconcileAllocationPair[] {
  return pairs.map((p) => ({ invoice_doc_id: p.invoice.id, line_id: p.line.id, ...(p.amount !== null ? { line_amount: canonical(p.amount) } : {}) }));
}

/** The candidates of a line, the best first: proposed, then the same amount only, then the rest. */
export function rankedCandidates(line: ReconcileLine): ReconcileCandidate[] {
  const rank = (c: ReconcileCandidate) => (c.proposed ? 0 : c.amount_only ? 1 : c.amount_relation === "fx_within" ? 2 : 3);
  // 134: within a rank, the stronger tie first (the service's strength: signals, amounts, booked by the due date)
  return [...line.candidates].sort((a, b) => rank(a) - rank(b) || (b.strength ?? 0) - (a.strength ?? 0));
}
