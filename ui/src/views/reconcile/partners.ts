// 135 (plan 134 P2): a statement line's partner and what is known about it, for the pairing page. The partner is the
// line's counterparty name without its reference numbers (the service's `partner`, jav/reconcile.py `name_key`); its
// lines are grouped and marked as needing no invoice in one step. A suggestion for the reason comes from a person's
// earlier marks of the partner's lines first, then from the AI's kind of payment (jav/reconcile_ai.py) — a suggestion
// only: a person chooses and saves it.
import { OPEN_LINE_STATES, type ReconcileAiEngine, type ReconcileLine } from "../../api";
import { parseCanonical } from "./money";

export const ENGINES: ReconcileAiEngine[] = ["jev", "gpt"];

export interface KindAnswer {
  engine: ReconcileAiEngine; kind: string; probability: number | null; mark: string | null; expects: boolean | null;
  /** 136: asked once for the partner, on another of its lines */
  lent: boolean;
}

/** The AI's kind of payment for a line, per engine that answered (JEV first). */
export function kinds(line: ReconcileLine): KindAnswer[] {
  return ENGINES.flatMap((engine) => {
    const a = line.ai?.[engine];
    return a?.kind ? [{ engine, kind: a.kind, probability: a.kind_probability, mark: a.suggested_mark, expects: a.expects_invoice,
      lent: Boolean(a.asked_line_id) }] : [];
  });
}

/** The engines that chose this invoice as the line's payment, with their probability. */
export function aiPicks(line: ReconcileLine, invoiceId: string): { engine: ReconcileAiEngine; probability: number | null }[] {
  return ENGINES.flatMap((engine) => {
    const a = line.ai?.[engine];
    return a?.pays === invoiceId ? [{ engine, probability: a.pays_probability }] : [];
  });
}

/** The invoices the AI chose for a line (either engine), in the order JEV, GPT. */
export function aiChosen(line: ReconcileLine): string[] {
  return [...new Set(ENGINES.map((e) => line.ai?.[e]?.pays).filter((x): x is string => Boolean(x)))];
}

/** A line a person still decides, without a candidate, whose kind of payment says an invoice should exist (either
 *  engine): the invoice is probably missing from the store. */
export function expectsInvoice(line: ReconcileLine): boolean {
  return OPEN_LINE_STATES.includes(line.state) && !line.candidates.length && kinds(line).some((k) => k.expects === true);
}

export type SuggestionSource = "earlier" | "ai_both" | "ai_one";
export interface MarkSuggestion { category: string; source: SuggestionSource; lines?: number; engines?: ReconcileAiEngine[] }

/** The reason suggested for marking these lines: the most frequent earlier reason of their partner; otherwise the
 *  reason both engines' kind suggests for every line; otherwise the one engine that answered alone does. None when the
 *  engines disagree or a line's kind expects an invoice. */
export function suggestMark(lines: ReconcileLine[]): MarkSuggestion | null {
  if (!lines.length) return null;
  const earlier = new Map<string, number>();
  for (const l of lines) for (const e of l.earlier_marks ?? []) earlier.set(e.category, Math.max(earlier.get(e.category) ?? 0, e.lines));
  const best = [...earlier].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0];
  if (best) return { category: best[0], source: "earlier", lines: best[1] };
  const per = lines.map((l) => kinds(l));
  if (per.some((ks) => !ks.length || ks.some((k) => !k.mark))) return null;
  const marks = new Set(per.flatMap((ks) => ks.map((k) => k.mark!)));
  if (marks.size !== 1) return null;
  const engines = ENGINES.filter((e) => per.every((ks) => ks.some((k) => k.engine === e)));
  return { category: [...marks][0], source: per.every((ks) => ks.length === ENGINES.length) ? "ai_both" : "ai_one", engines };
}

export interface PartnerGroup { key: string; name: string; lines: ReconcileLine[] }

/** The lines grouped by partner, the group with the most lines first, then by name; a line without a name is its own
 *  group. The lines keep their order inside a group. */
export function groupByPartner(lines: ReconcileLine[]): PartnerGroup[] {
  const groups = new Map<string, PartnerGroup>();
  for (const l of lines) {
    const key = l.partner ?? `line:${l.id}`;
    const g = groups.get(key) ?? { key, name: l.counterparty_name || l.description || l.memo || "–", lines: [] };
    g.lines.push(l);
    groups.set(key, g);
  }
  return [...groups.values()].sort((a, b) => b.lines.length - a.lines.length || a.name.localeCompare(b.name));
}

/** The lines a person can mark as needing no invoice now: still to decide and nothing allocated. */
export const markable = (l: ReconcileLine) => OPEN_LINE_STATES.includes(l.state) && parseCanonical(l.allocated) === 0n;
