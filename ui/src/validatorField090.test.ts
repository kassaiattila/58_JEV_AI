// 090: a failed field check's to-do names its field, and the sentence says which field (Hungarian and English); a
// check of the whole record reads as before. Artificial data, no service.
import { afterEach, expect, it } from "vitest";
import { setLanguage } from "./i18n";
import { reasonText } from "./labels";

afterEach(async () => { await setLanguage("hu"); });

it("a field check's to-do names the field by its label", async () => {
  expect(reasonText("validator:taxid.unrecognized:supplier_tax_id")).toBe("Az adószám alakja nem ismerhető fel: Szállító adószáma");
  expect(reasonText("validator:taxid.unrecognized")).toBe("Az adószám alakja nem ismerhető fel");
  await setLanguage("en");
  expect(reasonText("validator:taxid.unrecognized:supplier_tax_id")).toBe("The tax ID format is not recognised: Supplier tax ID");
});
