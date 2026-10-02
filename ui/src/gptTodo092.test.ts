// 092: without JEV, an accounting field GPT is not sure enough of gets a to-do named in everyday words, on its field.
import { describe, expect, it } from "vitest";
import { reasonText } from "./labels";

describe("092 GPT low-confidence to-do", () => {
  it("names the field and the probability", () => {
    expect(reasonText("gpt:low_conf:invoice_number:0.91")).toBe("A GPT nem elég biztos az értékben: Számlaszám (valószínűség 0,91)");
  });
});
