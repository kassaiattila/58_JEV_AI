// 132: exact money arithmetic for the pairing page. The service sends amounts as canonical decimal text ("1234.50");
// the page adds and compares them as integers scaled to four decimals, never as floating-point numbers, and sends
// canonical text back (the service never guesses a separator).
import { getLocale } from "../../i18n";

const SCALE = 4;
const FACTOR = 10n ** BigInt(SCALE);

/** Canonical decimal text ("-1234.5", "100.00") → a scaled integer; null when it is not one. */
export function parseCanonical(text: string | null | undefined): bigint | null {
  const m = /^(-)?(\d+)(?:\.(\d{1,4}))?$/.exec((text ?? "").trim());
  if (!m) return null;
  const value = BigInt(m[2]) * FACTOR + BigInt((m[3] ?? "").padEnd(SCALE, "0"));
  return m[1] ? -value : value;
}

/** A scaled integer → canonical text with at least two decimals ("1234.50"). */
export function canonical(value: bigint): string {
  const sign = value < 0n ? "-" : "";
  const abs = value < 0n ? -value : value;
  const whole = (abs / FACTOR).toString();
  const frac = (abs % FACTOR).toString().padStart(SCALE, "0").replace(/0+$/, "").padEnd(2, "0");
  return `${sign}${whole}.${frac}`;
}

const GROUPED: Record<string, RegExp> = { ".": /^\d{1,3}(?:\.\d{3})+$/, ",": /^\d{1,3}(?:,\d{3})+$/ };

/** What a person types → a scaled integer; null when it is not a number or can be read two ways (153, review A1: the
 *  page dropped every point in Hungarian, so "60.50" became 6050 and a pair was saved a hundred times too large). The
 *  rules of the service's reader of typed numbers (`jav/numbers.py` `read_input`), in the chosen language: the
 *  language's decimal mark (a comma in Hungarian, a point in English) alone is the decimal mark, but not before
 *  exactly three digits ("28,000" in Hungarian reads two ways); the other mark alone only groups thousands ("28.000",
 *  "1.234.567" in Hungarian), otherwise it reads two ways ("60.50" in Hungarian); with both marks the last one is the
 *  decimal mark ("12.345,67", "12,345.67"). Spaces group thousands. Only zeros read as zero either way. */
export function parseInput(text: string | null | undefined): bigint | null {
  const s = (text ?? "").replace(/[\s  ]/g, "");
  if (!/^-?[\d.,]+$/.test(s) || !/\d/.test(s)) return null;
  if (!/[1-9]/.test(s)) return 0n;
  const hu = getLocale() === "hu-HU";
  const dec = hu ? "," : ".";
  const grp = hu ? "." : ",";
  const sign = s.startsWith("-") ? "-" : "";
  const body = s.slice(sign.length);
  if (body.includes(dec) && body.includes(grp)) {
    const at = Math.max(body.lastIndexOf(","), body.lastIndexOf("."));
    const mark = body[at];
    const whole = body.slice(0, at);
    if (whole.includes(mark) || !GROUPED[mark === "," ? "." : ","].test(whole)) return null;
    return parseCanonical(`${sign}${whole.replace(/[.,]/g, "")}.${body.slice(at + 1)}`);
  }
  if (body.includes(dec)) {
    const parts = body.split(dec);
    if (parts.length > 2 || parts[1].length === 3) return null;
    return parseCanonical(`${sign}${parts[0]}.${parts[1]}`);
  }
  if (body.includes(grp)) return GROUPED[grp].test(body) ? parseCanonical(`${sign}${body.split(grp).join("")}`) : null;
  return parseCanonical(s);
}

/** A scaled integer for display: grouped thousands, the language's decimal mark, two decimals (more if needed). */
export function display(value: bigint | null, currency?: string | null): string {
  if (value === null) return "–";
  const [whole, frac] = canonical(value).split(".");
  const hu = getLocale() === "hu-HU";
  const sign = whole.startsWith("-") ? "\u2212" : "";
  const digits = whole.replace("-", "").replace(/\B(?=(\d{3})+(?!\d))/g, hu ? "\u00a0" : ",");
  const text = `${sign}${digits}${hu ? "," : "."}${frac}`;
  return currency ? `${text}\u00a0${currency}` : text;
}

/** Canonical text for display; "–" when missing or unreadable. */
export function show(text: string | null | undefined, currency?: string | null): string {
  return display(parseCanonical(text), currency);
}

export function sum(values: (bigint | null)[]): bigint {
  return values.reduce<bigint>((acc, v) => acc + (v ?? 0n), 0n);
}

export const min = (a: bigint, b: bigint): bigint => (a < b ? a : b);
