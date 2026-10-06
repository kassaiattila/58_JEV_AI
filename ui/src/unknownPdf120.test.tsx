// 120: the unknown-PDF setting has a name and readable values, and acts on documents only.
// Hungarian expectations use explicit codepoints for the language guard.
import { describe, expect, it } from "vitest";
import { PARAM_LABEL, paramApplies, paramShort } from "./labels";

describe("unknown PDFs setting (120)", () => {
  it("is named and its values are everyday words", () => {
    expect(PARAM_LABEL.unknown_documents).toBe("Ismeretlen PDF-ek");
    expect(paramShort("unknown_documents", "facts")).toBe("\u00e1ltal\u00e1nos adatjavaslat (GPT + JEV)");
    expect(paramShort("unknown_documents", "review")).toBe("meg\u00e1ll, k\u00e9zi ellen\u0151rz\u00e9s");
  });

  it("acts on documents, not on emails", () => {
    expect(paramApplies("unknown_documents", ["document"])).toBe(true);
    expect(paramApplies("unknown_documents", ["email"])).toBe(false);
  });
});
