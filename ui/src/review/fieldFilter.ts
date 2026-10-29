// 083 (the owner's trial): the small filter above the fields in Review — „Javítandó” (to fix: the field has an open
// to-do in this run), „Bizonytalan” (uncertain: the machine is not confident and nobody has checked the field yet) and
// „Mind” (all fields).
import type { ItemResult } from "../api";
import { tmap } from "../labels";
import { bandOf, bandsFor, type Bands } from "./geometry";

export type FieldFilter = "fix" | "uncertain" | "all";
export const FIELD_FILTERS: FieldFilter[] = ["fix", "uncertain", "all"];
export const FILTER_LABEL: Record<FieldFilter, string> = tmap({ fix: "To fix", uncertain: "Uncertain", all: "All" });

/** Whether a person has confirmed the field (its value then stays confirmed until it changes). */
export const isConfirmed = (res: ItemResult, f: string) => Object.prototype.hasOwnProperty.call(res.correction.confirmed ?? {}, f);

/** The fields of each filter, in the given order. A corrected or confirmed field is not uncertain any more: a person
 *  has set or checked it. */
/** 167 (review 153 E): a check across fields raises its to-do on the document; its fields are the ones to fix, so the
 *  "to fix" filter reaches them (it showed 0 for a due date before the issue date). */
const CROSS_FIELDS: Record<string, string[]> = {
  "validator:dates.due_before_issue": ["issue_date", "due_date"],
  "validator:dates.unparseable": ["issue_date", "due_date"],
  "validator:totals.mismatch": ["net_total", "vat_total", "gross_total"],
  "validator:totals.unparseable": ["net_total", "vat_total", "gross_total"],
};

export function classifyFields(fields: string[], res: ItemResult, bands: Bands): Record<FieldFilter, string[]> {
  const withReason = new Set(res.open_reasons.flatMap((r) => (r.field ? [r.field] : CROSS_FIELDS[r.reason] ?? [])));
  const weak = (f: string) => {
    const p = res.provenance[f];
    const band = bandOf(p?.confidence, bandsFor(p, bands));
    return (band === "check" || band === "likely_wrong") && !p?.corrected && !isConfirmed(res, f);
  };
  return { fix: fields.filter((f) => withReason.has(f)), uncertain: fields.filter(weak), all: fields };
}

/** The filter an item opens with: the one chosen earlier while it has fields on this item, otherwise „Javítandó” when
 *  there is something to fix, otherwise „Mind”. */
export function initialFilter(counts: Record<FieldFilter, number>, last: FieldFilter | null): FieldFilter {
  if (last && counts[last] > 0) return last;
  return counts.fix > 0 ? "fix" : "all";
}

/** 083: after a field was confirmed with Enter, the field to go on with: the next one when the confirmed field is still
 *  listed (for example under „Mind”), otherwise the one that took its place; null when nothing comes after it (the
 *  workspace then goes to the next item with to-dos). */
export function nextAfterConfirm(before: string[], after: string[], field: string): string | null {
  const still = after.indexOf(field);
  if (still >= 0) return after[still + 1] ?? null;
  const i = before.indexOf(field);
  return i >= 0 && i < after.length ? after[i] : null;
}

/** The note when the chosen filter has no field left (for example after the last field to fix was confirmed). */
export const EMPTY_FILTER: Record<FieldFilter, string> = tmap({
  fix: "Nothing is left to fix on this item.",
  uncertain: "No uncertain, unverified field is left on this item.",
  all: "This item has no simple fields.",
});
