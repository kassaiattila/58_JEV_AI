// 177 (plan 170 E6): every to-do kind of the registry (configs/todo_kinds.json) gets a label, not its raw code.
import { describe, expect, it } from "vitest";
import registry from "../../configs/todo_kinds.json";
import { reasonText } from "./labels";

// the kinds that still show their raw code (the owner's decision of 2026-10-19: they get their labels in 177)
const UNLABELLED = new Set([
  "jev:absence_wrong", "jev:off_target", "jev:wrong_kind", "jev:incomplete", "jev:parties_swapped",
  "jev:line_items_missing_rows", "jev:line_items_extra_rows", "signal:prompt_injection", "*:unparseable",
  "ocr:unavailable", "detect:no_result",
]);

describe("every to-do kind has a label (177)", () => {
  it("the registry lists the kinds", () => {
    expect(registry.kinds.length).toBeGreaterThan(80);
  });
  for (const kind of registry.kinds) {
    it(kind.code, () => {
      const text = reasonText(kind.example);
      if (UNLABELLED.has(kind.code)) {
        expect(text).toBe(kind.example);
        return;
      }
      expect(text).not.toBe(kind.example);
      // the label does not show the code itself (a family's code varies: its example is checked above)
      if (!kind.code.includes("*")) expect(text).not.toContain(kind.code.replace(/:$/, ""));
    });
  }
});
