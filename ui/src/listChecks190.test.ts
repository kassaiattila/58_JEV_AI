// 190 (plan 189 A2c): the checks of any list field (jav/validators.py list_rows, list_values, list_positive) read as
// everyday sentences, their rows named once each.
import { describe, expect, it } from "vitest";
import { checkText } from "./labels";

describe("the list checks (190)", () => {
  it("too few rows", () => {
    expect(checkText("lines.too_few", "rows=0 min=1")).toBe("A listában a vártnál kevesebb sor van (például egyetlen kért tétel sincs)");
  });
  it("a missing value names its rows once", () => {
    expect(checkText("lines.value_missing", "line 2: description; line 2: quantity; line 4: quantity"))
      .toBe("Egy listasorból hiányzik egy szükséges érték (2., 4. sor)");
  });
  it("a quantity of zero", () => {
    expect(checkText("lines.not_positive", "line 1: quantity=0")).toBe("Egy listasor mennyisége nulla vagy kevesebb (1. sor)");
  });
});
