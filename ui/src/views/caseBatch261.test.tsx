// 261 (plan B, B1c; the owner's decision of 2026-10-29: the review opens under the case's address): a case's step's
// batch - its processing, review and result - opens under its case's address, an older address of it leads there, and
// a sub-case's batch and page lead back to the main case by its name and by a button. Synthetic data, a mocked service.
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type DsPage, type WorkpackageView } from "../api";
import { setLanguage } from "../i18n";
import { parseRoute, routeHash, wpHash } from "../route";
import { CasePage } from "./CasePage";
import { WorkpackageDetail } from "./WorkpackageDetail";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ""; });

const MAIN = "wp-00000000a261";
const SUB = "wp-00000000b261";
const BATCH = "wp-00000000c261";
const EMPTY: DsPage = {
  dataset: { name: "items", label: "Items", scope: [], optional_scope: [] }, columns: [], rows: [], total: 0, matched: 0,
  offset: 0, limit: 50, facets: {},
};
const OWNER = { id: SUB, name: "Invented March", step: "process", step_title: "Processing", tab: "documents",
  parent: { id: MAIN, name: "Invented March", step_title: "Incoming invoices", tab: "overview" } };

function batch(over: Partial<WorkpackageView> = {}): WorkpackageView {
  return {
    workpackage: { id: BATCH, name: "March invoices", source_kind: "folder", source_ref: null, revision: 1, status: "open",
      created_at: "2026-10-29T10:00:00Z", updated_at: "2026-10-29T10:00:00Z", items: [] },
    readiness: { workpackage_id: BATCH, ready: true, blockers: [], warnings: [], counts: { items: 0 }, budget: {},
      assignment_revision: 1, input_hash: "0123456789abcdef" },
    next: { code: "start", label: "Start", stage: "process" }, last_run: null, runs: 0, owner_case: OWNER, ...over,
  } as unknown as WorkpackageView;
}

describe("a case's step's batch under its case (261 B1c)", () => {
  it("reads and writes the batch's address under its case, and learns which case a batch is of", () => {
    const at = `#/cases/${MAIN}/batches/wp-00000000d261/review/item-1`;
    const route = parseRoute(at);
    expect(route).toEqual({ view: "workpackages", wpId: "wp-00000000d261", stage: "review", itemId: "item-1", inCase: MAIN });
    expect(routeHash(route)).toBe(at);
    // a link to the same batch's result, made anywhere, leads under the case too
    expect(wpHash("wp-00000000d261", "result")).toBe(`#/cases/${MAIN}/batches/wp-00000000d261/result`);
    // a batch of no case keeps its own address
    expect(wpHash("wp-00000000e261", "review")).toBe("#/workpackages/wp-00000000e261/review");
  });

  it("leads a sub-case's batch back to the main case by its name and by a button, its sections under the case", async () => {
    vi.spyOn(api, "workpackage").mockResolvedValue(batch());
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<WorkpackageDetail wpId={BATCH} route={{ view: "workpackages", wpId: BATCH, stage: "process", inCase: SUB }} />);
    const crumbs = await screen.findByRole("navigation", { name: "Location" });
    expect(within(crumbs).getByRole("link", { name: "Invented March" }).getAttribute("href")).toBe(`#/cases/${MAIN}/overview`);
    expect(within(crumbs).getByRole("link", { name: "Incoming invoices" }).getAttribute("href")).toBe(`#/cases/${SUB}/documents`);
    expect(screen.getByRole("link", { name: "← Back to the main case" }).getAttribute("href")).toBe(`#/cases/${MAIN}/overview`);
    const tabs = screen.getByRole("tablist", { name: "Document batch stages" });
    expect(within(tabs).getAllByRole("tab").map((a) => a.getAttribute("href"))).toEqual(
      ["process", "review", "result"].map((s) => `#/cases/${SUB}/batches/${BATCH}/${s}`));
  });

  it("leads an older address of a case's batch to its address under the case", async () => {
    vi.spyOn(api, "workpackage").mockResolvedValue(batch());
    render(<WorkpackageDetail wpId={BATCH} route={{ view: "workpackages", wpId: BATCH, stage: "review", itemId: "item-2" }} />);
    await waitFor(() => expect(window.location.hash).toBe(`#/cases/${SUB}/batches/${BATCH}/review/item-2`));
  });

  it("leads a sub-case's page back to the main case's tab that shows its step, by a button too", async () => {
    const view: CaseView = {
      case: { id: SUB, pack: "documents", version: "1.4.0", title: "Documents", name: "Invented March", status: "open",
        parent: { id: MAIN, name: "Invented March", title: "Monthly reconciliation", step: "invoices", step_title: "Incoming invoices", tab: "overview" } },
      steps: {}, tabs: [{ id: "history", label: "History", elements: [] }], next: null,
    };
    vi.spyOn(api, "casePage").mockResolvedValue(view);
    render(<CasePage caseId={SUB} />);
    const crumbs = await screen.findByRole("navigation", { name: "Location" });
    expect(within(crumbs).getByRole("link", { name: "Invented March · Incoming invoices" }).getAttribute("href")).toBe(`#/cases/${MAIN}/overview`);
    expect(screen.getByRole("link", { name: "← Back to the main case" }).getAttribute("href")).toBe(`#/cases/${MAIN}/overview`);
  });
});
