// 274 (the engine registry in the interface; the owner's decision of 2026-11-01: an engine that cannot run in this
// installation is shown greyed with its reason, not offered): Settings › Processing lists every engine the service
// names, OpenAI Decisions greyed while it is under measurement; the processing path offers the registry's other
// judged engines the same way; the names come from the registries. The local service is replaced by spies.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import engineRegistry from "../../configs/engines.json";
import { api, setActor, type EngineChoice } from "./api";
import { setLanguage } from "./i18n";
import { BUDGET_PROVIDERS, ENGINE, engineReason, paramShort, pathChoices, PATH } from "./labels";
import { EnginePanel } from "./views/settings/EnginePanel";
import { budgetText } from "./views/workflows/labels";

const CHOICES: EngineChoice[] = [
  { engine: "jev", label: "JEV and GPT", available: true, reason: null, provider: null, judge_provider: "jev" },
  { engine: "decisions", label: "OpenAI Decisions and GPT", available: false, reason: "under_measurement",
    provider: "openai_decisions", judge_provider: "openai_decisions" },
  { engine: "gpt", label: "GPT only", available: true, reason: null, provider: null, judge_provider: null },
];

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the engines by the registry", () => {
  it("names every engine of configs/engines.json as the registry does", () => {
    const registry = engineRegistry.engines as Record<string, { label: string }>;
    expect(Object.keys(ENGINE).sort()).toEqual(Object.keys(registry).sort());
    for (const [id, e] of Object.entries(registry)) expect(ENGINE[id]).toBe(e.label);
  });

  it("says why an engine cannot run here", () => {
    expect(engineReason("under_measurement", "openai_decisions")).toMatch(/^Under measurement/);
    expect(engineReason("missing_key", "jev")).toBe("This installation has no JEV key");
    expect(engineReason("switched_off", "openai_decisions")).toBe("OpenAI Decisions is switched off in this installation");
    expect(engineReason(null)).toBe("");
  });

  it("lists the budgets calls reserve from, without OpenAI Decisions, which spends OpenAI's", () => {
    expect(BUDGET_PROVIDERS).toEqual(["jev", "openai", "azure_di"]);
    expect(budgetText({ jev: "0.10", azure_di: "0.02" })).toBe("JEV 0.10 USD + Azure DI 0.02 USD");
  });
});

describe("Settings › Processing: the AI engine", () => {
  it("shows OpenAI Decisions greyed with its reason, the others selectable", async () => {
    vi.spyOn(api, "engine").mockResolvedValue({ engine: "jev", actor: null, updated_at: null, choices: CHOICES });
    render(<EnginePanel />);
    const decisions = await screen.findByRole("radio", { name: /OpenAI Decisions and GPT/ }) as HTMLInputElement;
    expect(decisions.disabled).toBe(true);
    expect(screen.getByText(/^Under measurement: it can be chosen after its measurement/)).toBeTruthy();
    expect((screen.getByRole("radio", { name: /JEV and GPT \(recommended\)/ }) as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByRole("radio", { name: /GPT only, without JEV/ }) as HTMLInputElement).disabled).toBe(false);
  });

  it("keeps a saved engine that can no longer run here shown as chosen", async () => {
    vi.spyOn(api, "engine").mockResolvedValue({ engine: "decisions", actor: "Synthetic reviewer", updated_at: null, choices: CHOICES });
    render(<EnginePanel />);
    const decisions = await screen.findByRole("radio", { name: /OpenAI Decisions and GPT/ }) as HTMLInputElement;
    expect(decisions.checked).toBe(true);
    expect(decisions.disabled).toBe(false);
  });
});

describe("the processing path", () => {
  it("offers another judged engine after JEV's paths, greyed with its reason while it cannot run", () => {
    const choices = pathChoices(["auto", "S", "G"], ["document"], CHOICES);
    expect(choices.map((c) => c.value)).toEqual(["auto", "S", "G", "engine:decisions", "gpt"]);
    const decisions = choices[3];
    expect(decisions.disabled).toBe(true);
    expect(decisions.detail).toMatch(/^Under measurement/);
    expect(decisions.group).toBeUndefined();  // no groups while JEV's are the only judged paths
    const on = CHOICES.map((c) => ({ ...c, available: true, reason: null }));
    const emails = pathChoices(["auto", "S", "G"], ["email"], on);
    expect(emails.map((c) => [c.value, Boolean(c.disabled)])).toEqual([["jev", false], ["engine:decisions:with", false], ["gpt", false]]);
    expect(paramShort(PATH, "engine:decisions:with")).toBe("With OpenAI Decisions");
    expect(pathChoices(["auto", "S", "G"], ["document"]).map((c) => c.value)).toEqual(["auto", "S", "G", "gpt"]);  // an older service
  });

  it("275: offers a selectable judge's own paths, each choice under its engine's name", () => {
    const on = CHOICES.map((c) => ({ ...c, available: true, reason: null }));
    const docs = pathChoices(["auto", "S", "G"], ["document"], on);
    expect(docs.map((c) => [c.value, c.group])).toEqual([
      ["auto", "JEV and GPT"], ["S", "JEV and GPT"], ["G", "JEV and GPT"],
      ["engine:decisions", "OpenAI Decisions and GPT"], ["engine:decisions:S", "OpenAI Decisions and GPT"],
      ["engine:decisions:G", "OpenAI Decisions and GPT"], ["gpt", "GPT only"]]);
    expect(paramShort(PATH, "engine:decisions")).toBe("Automatic (recommended) — OpenAI Decisions and GPT");
    expect(paramShort(PATH, "engine:decisions:S")).toBe("OpenAI Decisions where possible — cheaper, no line items; GPT elsewhere (S)");
    expect(paramShort(PATH, "engine:decisions:G")).toBe("GPT + OpenAI Decisions — with line items (G)");
  });
});
