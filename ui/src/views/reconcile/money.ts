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

/** What a person types ("12 345,67", "12345.67", "12,345.67") → a scaled integer; the decimal mark is the chosen
 *  language's (comma in Hungarian, point in English); spaces and the other mark group thousands. */
export function parseInput(text: string): bigint | null {
  const hu = getLocale() === "hu-HU";
  const cleaned = text.replace(/[\s\u00a0\u202f]/g, "").replace(hu ? /\./g : /,/g, "").replace(hu ? "," : ".", ".");
  return parseCanonical(cleaned);
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
