// 153 (review A1, A2): the pairing page reads a typed amount by the rules of the service's number reader. In Hungarian
// it dropped every point, so "60.50" became 6050 and a pair could be saved a hundred times too large; a form that reads
// two ways is now refused and the panel says why. A panel whose selection grew read an amount that was never typed
// (undefined) and replaced the whole page with the error page; the "near the amount" percent box did the same on ",".
import { afterEach, describe, expect, it } from "vitest";
import type { ReconcileInvoice, ReconcileLine } from "../../api";
import { setLanguage } from "../../i18n";
import { invoiceMatches, NO_INVOICE_FILTERS } from "./filters";
import { canonical, parseInput } from "./money";
import { check } from "./pairing";

afterEach(async () => { await setLanguage("hu"); });

const read = (text: string | undefined) => {
  const v = parseInput(text);
  return v === null ? null : canonical(v);
};

describe("153 a typed amount in Hungarian", () => {
  it.each([
    ["12 345,67", "12345.67"], ["12.345,67", "12345.67"], ["12,345.67", "12345.67"], ["28,5", "28.50"],
    ["28.000", "28000.00"], ["1.234.567", "1234567.00"], ["-12,5", "-12.50"], ["0.00", "0.00"], ["0,000", "0.00"],
  ])("reads %s as %s", (typed, want) => {
    expect(read(typed)).toBe(want);
  });

  it.each(["60.50", "12345.67", "28.5", "28,000", "1,2,3", "12.34.5", "abc", "", "1-2"])("refuses %s, which reads two ways or is no number", (typed) => {
    expect(read(typed)).toBeNull();
  });

  it("refuses an amount that was never typed instead of failing", () => {
    expect(read(undefined)).toBeNull();
  });
});

describe("167 a typed amount has at most two decimals and no lone 0 group (review 160 U-10)", () => {
  it.each(["12,3456", "12,345", "0,125", "0.125"])("refuses %s in Hungarian", (typed) => {
    expect(read(typed)).toBeNull();
  });

  it.each(["0,125", "0.125", "12.3456"])("refuses %s in English", async (typed) => {
    await setLanguage("en");
    expect(read(typed)).toBeNull();
  });

  it("still reads two decimals and grouped thousands", async () => {
    expect(read("1.234,50")).toBe("1234.50");
    await setLanguage("en");
    expect(read("1,234.50")).toBe("1234.50");
  });
});

describe("153 a typed amount in English", () => {
  it.each([["60.50", "60.50"], ["28,000", "28000.00"], ["12,345.67", "12345.67"], ["1,234,567", "1234567.00"]])("reads %s as %s", async (typed, want) => {
    await setLanguage("en");
    expect(read(typed)).toBe(want);
  });

  it.each(["28.000", "60,5", "1,23"])("refuses %s", async (typed) => {
    await setLanguage("en");
    expect(read(typed)).toBeNull();
  });
});

const LINE = { id: "l1", amount: "-100.00", rest: "100.00", currency: "HUF" } as unknown as ReconcileLine;
const INVOICE = { id: "i1", amount: "100.00", rest: "100.00", currency: "HUF", candidates: [] } as unknown as ReconcileInvoice;

describe("153 the pairing panel and the filters do not break the page", () => {
  it("says an amount cannot be read instead of asking for a selection", () => {
    expect(check([{ line: LINE, invoice: INVOICE, amount: parseInput("60.50") }])).toEqual({ ok: false, why: "amount_unreadable" });
  });

  it.each([",", "abc", "1e999", "-5"])("the near-amount box takes %s without failing", (pct) => {
    expect(() => invoiceMatches({ ...NO_INVOICE_FILTERS, near: true, nearPct: pct }, INVOICE, LINE)).not.toThrow();
  });
});
