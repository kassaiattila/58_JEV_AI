// 265 (code review UI-12): the tables' amounts, the quote's and the utility report's go through the shared formatters
// and write exactly what their own copies wrote (the old formulas are kept here as the reference), in both languages.
import { afterEach, describe, expect, it } from "vitest";
import { getLocale, setLanguage } from "./i18n";
import { groupedAmount, moneyText, numText } from "./labels";
import { amountText } from "./domains/quotes/quoteStatus";
import { huf } from "./domains/finance/UtilityReport";

const VALUES = ["0", "5", "12.5", "1200.5", "1200.505", "28000", "-1234567.891", "0.004", "abc", "", null, undefined];

const grouped = (v: unknown, digits: number) => {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  return Number.isFinite(n)
    ? n.toLocaleString(getLocale(), { minimumFractionDigits: digits, maximumFractionDigits: Math.max(digits, 2),
      useGrouping: "always" } as unknown as Intl.NumberFormatOptions)
    : String(v);
};
const oldHuf = (v: string | null | undefined) =>
  v === null || v === undefined ? "" : Number(v).toLocaleString(getLocale(), { maximumFractionDigits: 2 });

afterEach(async () => { await setLanguage("hu"); });

describe("the shared amount formatters (265)", () => {
  for (const language of ["hu", "en"] as const) {
    it(`write what the copies wrote (${language})`, async () => {
      await setLanguage(language);
      for (const v of VALUES) {
        expect(moneyText(v), String(v)).toBe(grouped(v, 2));
        expect(groupedAmount(v, 0), String(v)).toBe(grouped(v, 0));
        expect(amountText(v as string | null | undefined, "HUF"), String(v)).toBe(grouped(v, 0));
        expect(amountText(v as string | null | undefined, "EUR"), String(v)).toBe(grouped(v, 2));
        // the utility report's amounts come from the service as numbers in text, or null
        if (v === null || v === undefined || (v !== "" && Number.isFinite(Number(v)))) {
          expect(huf(v as string | null | undefined), String(v)).toBe(oldHuf(v as string | null | undefined));
          expect(huf(v as string | null | undefined)).toBe(numText(v, 2));
        }
      }
    });
  }
});
