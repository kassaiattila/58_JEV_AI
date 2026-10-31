// 261 (plan B, B1c; the owner's decision of 2026-10-29: the review opens under the case's address): a case's step's
// batch - its processing, review and result - opens under its case's address, an older address of it leads there. 263
// (plan E, E2; one case, one track): a sub-case's batch opens on the main case's page, under the step that runs the
// sub-case, and the sub-case's own address leads there too. Synthetic data, a mocked service.
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

  it("leads a sub-case's batch to the main case's page, under the main case's address", async () => {
    vi.spyOn(api, "workpackage").mockResolvedValue(batch());
    render(<WorkpackageDetail wpId={BATCH} route={{ view: "workpackages", wpId: BATCH, stage: "process", inCase: SUB }} />);
    await waitFor(() => expect(window.location.hash).toBe(`#/cases/${MAIN}/batches/${BATCH}/process`));
  });

  it("leads an older address of a case's batch to its address under the main case", async () => {
    vi.spyOn(api, "workpackage").mockResolvedValue(batch());
    render(<WorkpackageDetail wpId={BATCH} route={{ view: "workpackages", wpId: BATCH, stage: "review", itemId: "item-2" }} />);
    await waitFor(() => expect(window.location.hash).toBe(`#/cases/${MAIN}/batches/${BATCH}/review/item-2`));
  });

  it("shows the batch's stages under the step on the main case's page, their addresses under the main case", async () => {
    const pages: Record<string, CaseView> = {
      [MAIN]: {
        case: { id: MAIN, pack: "monthly_reconciliation", version: "1.0.0", title: "Monthly reconciliation", name: "Invented March", status: "open" },
        steps: { invoices: { title: "Incoming invoices", uses: "run_case@1", start: "auto", state: "running", phase: null,
          waiting_for: "case_closed", awaiting_start: false, note: null, result: null } },
        tabs: [{ id: "overview", label: "Overview", elements: [{ type: "sub_case", step: "invoices", data: {
          state: "running", pack: "documents", process: "Documents", earlier: [],
          case: { id: SUB, name: "Invented March · Incoming invoices", status: "open", outcome: null, next: null,
            work: [{ step: "process", title: "Process the documents", tab: "documents", batch: BATCH, documents: 2, todos: 0, run: null }] } } }] },
          { id: "history", label: "History", elements: [{ type: "timeline", step: null, data: { events: [] } }] }],
        next: null,
      },
      [SUB]: {
        case: { id: SUB, pack: "documents", version: "1.4.0", title: "Documents", name: "Invented March · Incoming invoices", status: "open" },
        steps: {}, next: null,
        tabs: [{ id: "documents", label: "Documents", elements: [{ type: "package_work", step: "process",
          data: { package: { id: BATCH, name: "March invoices", items: 2 }, runs: [], can_start: false } }] },
          { id: "history", label: "History", elements: [{ type: "timeline", step: null, data: { events: [] } }] }],
      },
    };
    vi.spyOn(api, "casePage").mockImplementation(async (id: string) => pages[id]);
    vi.spyOn(api, "workpackage").mockImplementation(async (id: string) => (id === BATCH ? batch()
      : { ...batch(), workpackage: { ...batch().workpackage, id, name: "Invented March" }, owner_case: undefined }));
    vi.spyOn(api, "users").mockResolvedValue({ users: [] });
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<CasePage caseId={MAIN} batch={{ wpId: BATCH, route: { view: "workpackages", wpId: BATCH, stage: "process", inCase: MAIN } }} />);
    const track = await screen.findByRole("tablist", { name: "The case's steps" });
    expect(within(track).getByRole("tab", { name: /Incoming invoices/ }).getAttribute("aria-selected")).toBe("true");
    expect(within(track).getByRole("tab", { name: /Overview/ }).getAttribute("href")).toBe(`#/cases/${MAIN}/overview`);
    const stages = await screen.findByRole("tablist", { name: "Document batch stages" });
    expect(within(stages).getAllByRole("tab").map((a) => a.getAttribute("href"))).toEqual(
      ["process", "review", "result"].map((s) => `#/cases/${MAIN}/batches/${BATCH}/${s}`));
    expect(within(stages).getByRole("tab", { name: /Processing/ }).getAttribute("aria-selected")).toBe("true");
    // the log stands apart at the track's right end, the step's own beside the stages
    expect(screen.getAllByRole("link", { name: /^Log/ }).map((a) => a.getAttribute("href"))).toEqual(
      [`#/cases/${MAIN}/history`, `#/cases/${MAIN}/invoices/history`]);
    // one page, one title: the main case's; no button back
    expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual(["Invented March"]);
    expect(screen.queryByRole("link", { name: /Back/ })).toBeNull();
  });

  it("leads a sub-case's page to the main case's step that runs it", async () => {
    const view: CaseView = {
      case: { id: SUB, pack: "documents", version: "1.4.0", title: "Documents", name: "Invented March", status: "open",
        parent: { id: MAIN, name: "Invented March", title: "Monthly reconciliation", step: "invoices", step_title: "Incoming invoices", tab: "overview" } },
      steps: {}, tabs: [{ id: "history", label: "History", elements: [] }], next: null,
    };
    vi.spyOn(api, "casePage").mockResolvedValue(view);
    render(<CasePage caseId={SUB} />);
    await waitFor(() => expect(window.location.hash).toBe(`#/cases/${MAIN}/invoices?of=${SUB}`));
  });
});
