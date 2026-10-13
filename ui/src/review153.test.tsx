// 153 (review): Review says what an invoice's VAT check found (it shared its code with a statement's totals check and
// showed the statement's sentence). Artificial data, no service.
import { describe, expect, it } from "vitest";
import { checkText } from "./labels";

describe("153 an invoice's VAT check", () => {
  it("reads as the invoice's check, with the difference", () => {
    expect(checkText("totals.mismatch", "net+vat-gross=-100.00 (HUF)")).toMatch(/^A nettó összeg és az ÁFA nem adja ki a bruttó összeget \(eltérés: /);
  });

  it("leaves a statement's totals check as it was", () => {
    expect(checkText("totals.mismatch", "debit total 100.00 vs 90.00")).toBe("Az összesített terhelés / jóváírás nem egyezik a tranzakciókkal");
  });
});
