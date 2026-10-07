// 121: a pair of parties standing the other way round than on the earlier documents of the same type: the to-do
// stands at the buyer's tax number, in everyday words. Hungarian expectations use explicit codepoints.
import { describe, expect, it } from "vitest";
import { checkText, reasonText } from "./labels";

describe("party pair against earlier documents (121)", () => {
  it("is a known check, not the unknown-check fallback", () => {
    expect(checkText("parties.orientation_reversed")).toBe("A k\u00e9t f\u00e9l szerepe ford\u00edtott ahhoz k\u00e9pest, ahogy a kor\u00e1bbi, azonos t\u00edpus\u00fa iratokon \u00e1lltak");
  });

  it("names the field it stands at", () => {
    expect(reasonText("validator:parties.orientation_reversed:buyer_tax_id")).toMatch(/^A k\u00e9t f\u00e9l szerepe ford\u00edtott .+: /);
  });
});
