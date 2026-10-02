// 086: the processing setting "without JEV". The run gets no JEV budget, GPT recognises the type and every document
// runs on the G path; since 089 GPT recognises an email's intent too. Artificial data, no service.
import { describe, expect, it } from "vitest";
import { type Recipe, type RunPlan } from "./api";
import { itemBudget, itemBudgetLines, paramShort, planLines, reasonText } from "./labels";

const RECIPE: Recipe = {
  id: "processing", version: 1, status: "active", title: "Feldolgozás", description: "Leírás.", steps: [], requirements: [],
  result: "Eredmény.", manual_action: "Teendők.",
  params: { arm: { allowed: ["auto", "S", "G"], default: "auto" }, jev: { allowed: ["on", "off"], default: "on" } },
  max_item_usd: { auto: { jev: "0.07", openai: "0.15" } },
  max_item_usd_by_kind: { email: { "*": { jev: "0.05" } }, document: { auto: { jev: "0.07", openai: "0.15" } } },
  param_item_usd: [
    { param: "jev", value: "off", kind: "document", usd: { openai: "0.07" }, drop: ["jev"] },
    { param: "jev", value: "off", kind: "email", usd: {}, drop: ["jev"] },
  ],
};

const PLAN: RunPlan = { documents: 2, emails: 1, attachments: 0, paths: { S: 0, G: 2, unknown: 0 }, tasks_emails: 0, azure: false,
  jev_reuse: true, arm: "auto", jev: false };

describe("086 processing without JEV", () => {
  it("switched off, there is no JEV budget and type recognition gets an OpenAI budget", () => {
    expect(itemBudget(RECIPE, { arm: "auto", jev: "on" }, "document")).toEqual({ jev: 0.07, openai: 0.15 });
    expect(itemBudget(RECIPE, { arm: "auto", jev: "off" }, "document")).toEqual({ openai: 0.22 });
    expect(itemBudget(RECIPE, { arm: "auto", jev: "off" }, "email")).toEqual({});
    expect(itemBudgetLines(RECIPE, { arm: "auto", jev: "off" })).toEqual(["levelenként: nincs", "PDF-iratonként: OpenAI legfeljebb 0,22 USD"]);
  });

  it("the pre-start overview says that JEV is not called", () => {
    const lines = planLines(PLAN, { openai: "0.44" });
    expect(lines).toContain("JEV: nem hívódik (kikapcsolva).");
    // 089: GPT recognises the emails' intent too
    expect(lines).toContain("OpenAI legfeljebb 0,44 USD: 2 irat típusfelismerése és adatkinyerése a G-úton, kódos ellenőrzéssel; 1 levél szándékfelismerése.");
    expect(lines.some((l) => l.startsWith("JEV legfeljebb"))).toBe(false);
  });

  it("the setting and the to-dos get plain names", () => {
    expect(paramShort("jev", "off")).toBe("kikapcsolva — csak GPT (OpenAI)");
    expect(reasonText("intent:jev_off")).toMatch(/JEV nélküli feldolgozás/);
    expect(reasonText("detect:gpt_failed:BudgetExceeded")).toMatch(/GPT-s típusfelismerés nem sikerült \(BudgetExceeded\)/);
    expect(reasonText("detect:confidence_unavailable:invoice_hu")).toMatch(/bizonyossága nem mérhető/);
    // 089: the intent recognised by GPT
    expect(reasonText("intent:gpt_failed:BudgetExceeded")).toMatch(/GPT-s szándékfelismerés nem sikerült \(BudgetExceeded\)/);
    expect(reasonText("intent:confidence_unavailable")).toMatch(/levél-szándék bizonyossága nem mérhető/);
  });
});
