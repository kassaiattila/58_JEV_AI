// 082 (the owner's request of 2026-10-01): the cost view — per provider on the run's page what the pre-start overview
// expected and what the run actually called (with the models, the answers reused from earlier, and the reserved amount
// of the calls without a known cost apart), the budget bars under the providers' names, and the package's cost over
// all its runs. Artificial data, no service.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsPage, type ProviderCost, type RunCostView } from "./api";
import { BudgetBars, PlanVsActual, providerCostLines } from "./views/Runs";
import { PackageCosts } from "./views/PackageCosts";

afterEach(() => vi.restoreAllMocks());

const row = (over: Partial<ProviderCost>): ProviderCost => ({ provider: "jev", expected: "yes", limit_usd: "0.10", committed_usd: "0.002",
  calls: 2, failed: 0, open: 0, usd: "0.002000", held_usd: "0", reused: 12, models: ["jev-1.13.0"], unexpected: false, ...over });
const view = (providers: ProviderCost[], plan_saved = true): RunCostView => ({ run_id: "run-1", plan_saved, plan: null, providers });

describe("082 planned and actual", () => {
  it("each provider shows the overview's expectation, the paid calls, the cost and the answers reused from earlier", () => {
    expect(providerCostLines(row({}))).toEqual([
      "Terv: várható · keret 0,10 USD",
      "2 fizetős hívás · 0,0020 USD",
      "12 kérdés korábbi válaszból (ingyenes)",
    ]);
    expect(providerCostLines(row({ provider: "azure_di", expected: "maybe", calls: 3, failed: 3, usd: "0", held_usd: "0.0600", reused: 0, models: ["prebuilt-read"] }))).toEqual([
      "Terv: lehetséges · keret 0,10 USD",
      "3 fizetős hívás (ebből 3 sikertelen) · 0,0000 USD",
      "Lefoglalt, ismeretlen kimenetelű: 0,0600 USD (nem költség, a keret ennyivel számol)",
    ]);
    expect(providerCostLines(row({ expected: null, limit_usd: null, calls: 0, usd: "0", reused: 0 }))).toEqual(["Nem volt fizetős hívás."]);
  });

  it("a provider called against the overview is flagged, and an old run says the overview was not saved", () => {
    render(<PlanVsActual costs={view([row({}), row({ provider: "openai", expected: "no", unexpected: true, models: ["gpt-4.1-mini"], reused: 0 })], false)} />);
    expect(screen.getByRole("alert").textContent).toBe("Az indítás előtti áttekintés nem számolt ezzel a szolgáltatóval, mégis volt hívás.");
    expect(screen.getByText("Ennél a futásnál az indítás előtti áttekintés még nem mentődött; csak a tényleges költés látszik.")).toBeTruthy();
    expect(screen.getByText("OpenAI")).toBeTruthy();
    expect(screen.getByText("gpt-4.1-mini")).toBeTruthy();
  });

  it("the budget bars name the providers", () => {
    render(<BudgetBars budget={{ scope: "run-1", committed_usd: "0.08", providers: { azure_di: { limit_usd: "2.74", committed_usd: "0.0855" } } }} />);
    expect(screen.getByText("Azure DI")).toBeTruthy();
    expect(screen.queryByText("AZURE_DI")).toBeNull();
  });
});

describe("082 package cost", () => {
  it("the package's cost is listed per provider and model, with the total over every run", async () => {
    const pg: DsPage = {
      dataset: { name: "package_costs", label: "A csomag költsége", scope: ["workpackage_id"], optional_scope: [], natural_sort: [] },
      columns: [{ key: "provider", label: "AI-szolgáltató", kind: "enum", hidden: false, labels: { jev: "JEV", openai: "OpenAI" } },
        { key: "usd", label: "Költség (USD)", kind: "number", hidden: false, labels: null }],
      rows: [{ _key: "jev:jev-1.13.0", provider: "jev", usd: "0.005000", reused: 4 }, { _key: "openai:gpt", provider: "openai", usd: "0.001000", reused: 0 }],
      total: 2, matched: 2, offset: 0, limit: 100, facets: {},
    };
    const query = vi.spyOn(api, "datasetQuery").mockResolvedValue(pg);
    render(<PackageCosts wpId="wp-1" />);
    await waitFor(() => expect(screen.getByText("Összesen: 0,0060 USD, 4 kérdés korábbi válaszból (ingyenes).")).toBeTruthy());
    expect(query).toHaveBeenCalledWith("package_costs", { workpackage_id: "wp-1" }, expect.anything());
  });
});
