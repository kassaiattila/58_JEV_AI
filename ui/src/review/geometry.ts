// Tiszta segédek a forráshoz kötött ellenőrzéshez (045 K3b). React nélkül, tesztelhetően.
// A koordináták oldal-relatívak (0–1), bal felső origóval: [x0, y0, x1, y1]. A V4 review-view.ts viselkedését követik.
import type { Box, Provenance, SourceWord } from "../api";
import { tmap } from "../labels";

export type Band = "confident" | "check" | "likely_wrong" | "unknown";
export interface Bands { confident: number; check: number }

// 057: olvasáskor fordít (tmap), a kirajzoló komponens useLocale()-lal frissül
export const BAND_LABEL: Record<Band, string> = tmap({
  confident: "Magabiztos",
  check: "Ellenőrzendő",
  likely_wrong: "Valószínűleg hibás",
  unknown: "Nincs becslés",
}) as Record<Band, string>;

/** A modell becslése sávba sorolva. A javított mező mindig „ellenőrzendő” (a becslés a gépi értékre vonatkozott). */
export function bandOf(confidence: number | null | undefined, bands: Bands, corrected = false): Band {
  if (corrected) return "check";
  if (confidence === null || confidence === undefined || Number.isNaN(confidence)) return "unknown";
  if (confidence >= bands.confident) return "confident";
  if (confidence >= bands.check) return "check";
  return "likely_wrong";
}

const PAD = 0.004;

function contains(b: Box, x: number, y: number, pad = PAD): boolean {
  return x >= b[0] - pad && x <= b[2] + pad && y >= b[1] - pad && y <= b[3] + pad;
}

/** A mező kerete(i) a képen: pontos (`located`) vagy közelítő (`approximate`: a sor, ahonnan a modell választott). */
export function frameBoxes(p: Provenance | undefined): Box[] {
  if (!p || (p.status !== "located" && p.status !== "approximate")) return [];
  return p.boxes?.length ? p.boxes : p.bbox ? [p.bbox] : [];
}

/** A pont alatti mezők (keretük tartalmazza), kulcs szerint rendezve — ismételt kattintás a következőre lép. */
export function fieldsAtPoint(prov: Record<string, Provenance>, page: number, x: number, y: number): string[] {
  return Object.entries(prov)
    .filter(([, p]) => p.page === page && frameBoxes(p).some((b) => contains(b, x, y)))
    .map(([k]) => k)
    .sort();
}

/** A következő mező az átfedő keretek között (körbe). */
export function cyclePick(hits: string[], current: string | null): string | null {
  if (!hits.length) return null;
  const i = current ? hits.indexOf(current) : -1;
  return hits[(i + 1) % hits.length];
}

/** A keret kicsit nagyobb a szövegnél, hogy ne takarja el a betűket. */
export function inflate(b: Box, by: number): { left: number; top: number; width: number; height: number } {
  const x0 = Math.max(0, b[0] - by), y0 = Math.max(0, b[1] - by), x1 = Math.min(1, b[2] + by), y1 = Math.min(1, b[3] + by);
  return { left: x0 * 100, top: y0 * 100, width: (x1 - x0) * 100, height: (y1 - y0) * 100 };
}

/** A pont alatti szó (kattintásos kijelöléshez). */
export function wordAt(words: SourceWord[], page: number, x: number, y: number): SourceWord | null {
  return words.find((w) => w.page === page && contains([w.x0, w.y0, w.x1, w.y1], x, y, 0.002)) ?? null;
}

/** A húzott téglalapba eső szavak (a szó közepe a téglalapon belül), olvasási sorrendben. */
export function wordsInRect(words: SourceWord[], page: number, a: { x: number; y: number }, b: { x: number; y: number }): SourceWord[] {
  const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x), y0 = Math.min(a.y, b.y), y1 = Math.max(a.y, b.y);
  return words
    .filter((w) => w.page === page && (w.x0 + w.x1) / 2 >= x0 && (w.x0 + w.x1) / 2 <= x1 && (w.y0 + w.y1) / 2 >= y0 && (w.y0 + w.y1) / 2 <= y1)
    .sort((p, q) => p.id - q.id);
}

/** A kijelölt szavak szövege olvasási sorrendben. */
export function selectionText(words: SourceWord[], ids: number[]): string {
  const set = new Set(ids);
  return words.filter((w) => set.has(w.id)).sort((a, b) => a.id - b.id).map((w) => w.text).join(" ");
}

/** Mezősorrend: előbb a nyitott teendővel érintettek, aztán a gyenge becslésűek, egyébként az alapsorrend. */
export function orderFields(fields: string[], reasonFields: Set<string>, band: (f: string) => Band): string[] {
  const rank = (f: string) => (reasonFields.has(f) ? 0 : band(f) === "likely_wrong" ? 1 : 2);
  return fields.map((f, i) => ({ f, i })).sort((a, b) => rank(a.f) - rank(b.f) || a.i - b.i).map((x) => x.f);
}
