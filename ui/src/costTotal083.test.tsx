// 083 (the owner's trial of 2026-10-01): the run's total cost was hard to read, and the budget bars on top drew the eye.
// Now the total comes first, then each provider; the planned-and-actual part compares the plan with the actual cost; the
// budget bars sit in a closed "Budget" part that opens by itself when a budget is at least 80% used or the budget
// stopped something. Artificial data, no service.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { type ProviderCost, type RunCostView, type RunView } from "./api";
import { setLanguage } from "./i18n";
import { budgetSummary, planLine, providerCostLines, RunCost } from "./views/Runs";

afterEach(async () => { await setLanguage("hu"); });

const row = (over: Partial<ProviderCost>): ProviderCost => ({ provider: "jev", expected: "yes", limit_usd: "0.40", committed_usd: "0.052676",
  calls: 120, failed: 0, open: 0, usd: "0.052676", held_usd: "0", reused: 295, models: ["jev-1.13.0"], unexpected: false, ...over });
const costs: RunCostView = {
  run_id: "run-1", plan_saved: true, plan: null,
  providers: [row({}), row({ provider: "openai", expected: "no", limit_usd: "0.15", committed_usd: "0", calls: 0, usd: "0", reused: 0, models: [] }),
    row({ provider: "azure_di", expected: "maybe", limit_usd: "0.10", committed_usd: "0.04", calls: 2, failed: 2, usd: "0", held_usd: "0.04", reused: 0, models: ["prebuilt-read"] })],
  total: { usd: "0.052676", calls: 122, failed: 2, held_usd: "0.04", reused: 295 },
};
const budget = (jev: string): RunView["budget"] => ({ scope: "run-1", committed_usd: jev, providers: {
  jev: { limit_usd: "0.40", committed_usd: jev }, openai: { limit_usd: "0.15", committed_usd: "0" } } });

describe("083 the run's total cost", () => {
  it("comes first, then each provider's calls and cost, and the answers reused from earlier once", () => {
    render(<RunCost costs={costs} budget={budget("0.052676")} budgetBlocked={false} />);
    const total = screen.getByText("A futás költsége").parentElement!;
    expect(total.textContent).toContain("0,052676 USD");
    expect(screen.getByText("120 fizetős hívás · 0,052676 USD")).toBeTruthy();
    expect(screen.getByText("2 fizetős hívás (ebből 2 sikertelen) · 0,0000 USD")).toBeTruthy();
    expect(screen.getAllByText("295 kérdés korábbi válaszból (ingyenes)")).toHaveLength(1);
    // the total comes before the budget in the page
    const budgetPart = screen.getByText("Keret (JEV 13%, OpenAI 0%)");
    expect(total.compareDocumentPosition(budgetPart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("a provider's lines carry the actual calls and the reserved amount, not the plan", () => {
    expect(providerCostLines(row({}))).toEqual(["120 fizetős hívás · 0,052676 USD"]);
    expect(providerCostLines(row({ calls: 0, usd: "0", reused: 12 }))).toEqual(["Nem volt fizetős hívás."]);
    expect(providerCostLines(row({ calls: 3, failed: 3, usd: "0", held_usd: "0.06" }))).toEqual([
      "3 fizetős hívás (ebből 3 sikertelen) · 0,0000 USD",
      "Lefoglalt, ismeretlen kimenetelű: 0,0600 USD (nem költség, a keret ennyivel számol)",
    ]);
  });

  it("planned and actual sets the plan against the actual cost", () => {
    expect(planLine(row({}))).toBe("Terv: várható · tényleges: 0,052676 USD");
    expect(planLine(row({ expected: "no", usd: "0" }))).toBe("Terv: nem várt · tényleges: 0,0000 USD");
    expect(planLine(row({ expected: null, usd: "0.001" }))).toBe("Terv nélkül · tényleges: 0,0010 USD");
  });
});

describe("083 the budget part", () => {
  it("is closed while the budgets are far from used up", () => {
    const k = budgetSummary(budget("0.052676"), false)!;
    expect(k).toEqual({ text: "Keret (JEV 13%, OpenAI 0%)", open: false });
    render(<RunCost costs={costs} budget={budget("0.052676")} budgetBlocked={false} />);
    expect((screen.getByText("Keret (JEV 13%, OpenAI 0%)").closest("details") as HTMLDetailsElement).open).toBe(false);
  });

  it("opens by itself at 80% use or when the budget stopped something", () => {
    expect(budgetSummary(budget("0.32"), false)!.open).toBe(true);
    expect(budgetSummary(budget("0.01"), true)!.open).toBe(true);
    render(<RunCost costs={costs} budget={budget("0.36")} budgetBlocked={false} />);
    expect((screen.getByText("Keret (JEV 90%, OpenAI 0%)").closest("details") as HTMLDetailsElement).open).toBe(true);
  });

  it("names the providers in the order of the cost list", () => {
    const b: RunView["budget"] = { scope: "run-1", committed_usd: "0", providers: {
      azure_di: { limit_usd: "1", committed_usd: "0.01" }, openai: { limit_usd: "1", committed_usd: "0" }, jev: { limit_usd: "1", committed_usd: "0.02" } } };
    expect(budgetSummary(b, false)!.text).toBe("Keret (JEV 2%, OpenAI 0%, Azure DI 1%)");
  });

  it("is left out when the run has no budget, and the new labels have an English translation", async () => {
    expect(budgetSummary({ scope: "run-1", committed_usd: "0", providers: {} }, false)).toBeNull();
    await setLanguage("en");
    render(<RunCost costs={costs} budget={budget("0.052676")} budgetBlocked={false} />);
    expect(screen.getByText("Cost of the run")).toBeTruthy();
    expect(screen.getByText("Budget (JEV 13%, OpenAI 0%)")).toBeTruthy();
    expect(planLine(row({}))).toBe("Plan: expected · actual: 0.052676 USD");
  });
});
