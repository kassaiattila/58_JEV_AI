// 075: the Azure recipe switch in the UI — the per-document Azure budget mirrors the service (a missing parameter counts
// with the recipe's default), the switch has a short label, and the escalation to-do reads as a sentence.
import { describe, expect, it } from "vitest";
import type { Recipe } from "./api";
import { itemBudget, paramsText, reasonText } from "./labels";

const RECIPE: Recipe = {
  id: "document-processing", version: 3, title: "", description: "", steps: [], requirements: [], result: "", manual_action: "",
  params: { arm: { allowed: ["auto", "S", "G"], default: "auto" }, azure_ocr: { allowed: ["on", "off"], default: "on" } },
  max_item_usd: { auto: { jev: "0.07", openai: "0.10" } },
  param_item_usd: [{ param: "azure_ocr", value: "on", usd: { azure_di: "0.02" } }],
};

describe("075 Azure recipe switch", () => {
  it("adds the Azure budget per document when the switch is on, also for an older assignment without it", () => {
    expect(itemBudget(RECIPE, { arm: "auto", azure_ocr: "on" })).toEqual({ jev: 0.07, openai: 0.1, azure_di: 0.02 });
    expect(itemBudget(RECIPE, { arm: "auto" })).toEqual({ jev: 0.07, openai: 0.1, azure_di: 0.02 });
    expect(itemBudget(RECIPE, { arm: "auto", azure_ocr: "off" })).toEqual({ jev: 0.07, openai: 0.1 });
  });

  it("labels the switch and the escalation to-do", () => {
    expect(paramsText({ azure_ocr: "off" })).toBe("Azure-felismerés: kikapcsolva");
    expect(reasonText("ocr:escalation_blocked:budget_exceeded")).toMatch(/kerete miatt elmaradt/);
    expect(reasonText("ocr:escalation_blocked:uncertain_attempt")).toMatch(/bizonytalan/);
  });
});
