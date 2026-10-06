// 120: the role-pair check's to-do names the field it stands at, in everyday words.
// Hungarian expectations use explicit codepoints for the language guard.
import { describe, expect, it } from "vitest";
import { checkText, reasonText } from "./labels";

describe("party in two roles (120)", () => {
  it("is an everyday sentence with the field's label", () => {
    expect(reasonText("validator:parties.same_entity:employer_name"))
      .toBe("Ugyanaz a szerepl\u0151 k\u00e9t k\u00fcl\u00f6nb\u00f6z\u0151 szerepben: Munk\u00e1ltat\u00f3 neve");
  });

  it("is a known check, not the unknown-check fallback", () => {
    expect(checkText("parties.same_entity")).toBe("Ugyanaz a szerepl\u0151 k\u00e9t k\u00fcl\u00f6nb\u00f6z\u0151 szerepben");
  });
});
