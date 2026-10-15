// 155: every button that starts a run carries the run's cost cap (a trial spends from the same budget as a live run);
// the mark is visual only, so the buttons keep their names, and a run that can spend nothing carries no mark.
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsPage, type WorkpackageView } from "./api";
import { t } from "./i18n";
import { usdBudget } from "./labels";
import { WorkpackageDetail } from "./views/WorkpackageDetail";

function view(budget: Record<string, string>): WorkpackageView {
  return {
    workpackage: {
      id: "wp-1", name: "Utility sample", source_kind: "manual", source_ref: null, revision: 1, status: "open", created_at: "2026-09-28T10:00:00Z",
      updated_at: "2026-09-28T10:00:00Z", items: [{ item_id: "a", kind: "document", source_path: "C:/x/a.pdf", sha256: "a", added_revision: 1 }],
      assignment: { workpackage_id: "wp-1", revision: 1, recipe_id: "document-processing", recipe_version: 2, recipe_hash: "h", params: { arm: "auto" },
        actor: "Test User", note: null, created_at: "2026-09-28T10:00:00Z" },
    },
    readiness: { workpackage_id: "wp-1", ready: true, blockers: [], warnings: [], counts: { items: 1 }, budget, assignment_revision: 1, input_hash: "0123456789abcdef" },
    next: { code: "start", label: "start", stage: "process" }, last_run: null, runs: 0,
  } as WorkpackageView;
}

const EMPTY: DsPage = {
  dataset: { name: "runs", label: "Runs", scope: [], optional_scope: ["workpackage_id"] }, columns: [], rows: [], total: 0, matched: 0,
  offset: 0, limit: 50, facets: {},
};

afterEach(() => vi.restoreAllMocks());

async function renderWith(budget: Record<string, string>) {
  vi.spyOn(api, "workpackage").mockResolvedValue(view(budget));
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
  const r = render(<WorkpackageDetail wpId="wp-1" route={{ view: "workpackages", wpId: "wp-1", stage: "process" }} />);
  await vi.waitFor(() => expect(r.container.querySelectorAll(".button-row [data-run]").length).toBe(3));
  return r.container;
}

describe("run buttons show what a run may spend (155)", () => {
  it("puts the summed cap on each start button, hidden from the name and given in the tooltip", async () => {
    const page = await renderWith({ jev: "2.03", openai: "2.9" });
    const cap = usdBudget(4.93);
    for (const run of ["shadow", "apply", "rerun"]) {
      const button = page.querySelector(`.button-row [data-run="${run}"]`)!;
      const mark = button.querySelector(".spend")!;
      expect(mark.textContent).toBe(`≤ ${cap}`);
      expect(mark.getAttribute("aria-hidden")).toBe("true");
      expect(button.getAttribute("title")).toContain(t("Starts a run that can spend up to {{usd}}", { usd: cap }));
    }
  });

  it("leaves the buttons unmarked when the run can spend nothing", async () => {
    const page = await renderWith({ jev: "0", openai: "0" });
    expect(page.querySelectorAll(".spend").length).toBe(0);
    expect(page.querySelector('.button-row [data-run="shadow"]')!.hasAttribute("title")).toBe(false);
  });
});
