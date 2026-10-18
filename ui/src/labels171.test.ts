// 171 (plan 170, K20): the "no record" to-do (`no_invoice`, raised when no data could be extracted from a document)
// showed its raw code on the review page; it now reads as a sentence in both interface languages.
import { afterEach, describe, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import { reasonText } from "./labels";

afterEach(async () => { await setLanguage("hu"); });

describe("171 the no-record to-do", () => {
  it("reads as a sentence in Hungarian, not as its code", () => {
    expect(reasonText("no_invoice")).toBe(
      "Az iratból egyetlen adat sem lett kinyerve, ezért nincs ellenőrizhető vagy letölthető értéke; az okot az irat többi teendője mutatja");
  });

  it("reads as a sentence in English", async () => {
    await setLanguage("en");
    expect(reasonText("no_invoice")).toBe(
      "No data was extracted from the document, so it has no values to check or download; its other to-dos show why");
  });
});
