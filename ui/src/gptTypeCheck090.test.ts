// 090: the to-do of the type / issuer cross-check reads as a sentence, in Hungarian and in English, naming the type
// (the detailed one when that is the Hungarian one). Artificial data, no service.
import { afterEach, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import { reasonText } from "./labels";

afterEach(async () => { await setLanguage("hu"); });

it("the issuer contradiction names the type and asks for a check of the type", async () => {
  expect(reasonText("detect:issuer_mismatch:invoice_hu")).toMatch(/^A típus \(.+\) magyar kiállítót feltételez, de a felismerés szerint a kiállító nem magyar; ellenőrizd a típust$/);
  expect(reasonText("detect:issuer_mismatch:nav_receipt")).not.toContain("nav_receipt");  // the type's display name
  await setLanguage("en");
  expect(reasonText("detect:issuer_mismatch:invoice_hu")).toMatch(/^The type \(.+\) presumes a Hungarian issuer, but the recognition says the issuer is not Hungarian; check the type$/);
});
