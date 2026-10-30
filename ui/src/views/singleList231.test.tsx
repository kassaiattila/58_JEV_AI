// 231 (stage U, U2a; the owner's decision of 2026-10-28: one work list, the cases): the rail holds the cases and the
// settings; a case step's document batch leads back to its case and step, any other batch to the list of every batch
// (under Settings › System); a case in a list opens at its own address. Synthetic data, a mocked service.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { api, setActor, type DsPage, type WorkpackageView } from "../api";
import { linkOf } from "../components/DataTable";
import { setLanguage } from "../i18n";
import { WorkpackageDetail } from "./WorkpackageDetail";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ""; });

const EMPTY: DsPage = {
  dataset: { name: "cases", label: "Cases", scope: [], optional_scope: [] }, columns: [], rows: [], total: 0, matched: 0,
  offset: 0, limit: 50, facets: {},
};

function batch(over: Partial<WorkpackageView> = {}): WorkpackageView {
  return {
    workpackage: { id: "wp-00000000b001", name: "April invoices", source_kind: "folder", source_ref: null, revision: 1, status: "open",
      created_at: "2026-10-28T10:00:00Z", updated_at: "2026-10-28T10:00:00Z", items: [] },
    readiness: { workpackage_id: "wp-00000000b001", ready: true, blockers: [], warnings: [], counts: { items: 0 }, budget: {},
      assignment_revision: 1, input_hash: "0123456789abcdef" },
    next: { code: "start", label: "Start", stage: "process" }, last_run: null, runs: 0, ...over,
  } as unknown as WorkpackageView;
}

describe("one work list (231 U2a)", () => {
  it("has the cases and the settings in the rail, and opens the cases by default", async () => {
    vi.spyOn(api, "users").mockResolvedValue({ users: [] });
    vi.spyOn(api, "worker").mockResolvedValue({ running: true, stop_requested: false, jobs: {} });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<App />);
    const rail = screen.getByRole("navigation", { name: "Main menu" });
    expect(within(rail).getAllByRole("link").map((a) => a.textContent)).toEqual(["Cases", "Settings"]);
    expect(within(rail).getByRole("link", { name: "Cases" }).getAttribute("aria-current")).toBe("page");
  });

  it("leads a case step's batch back to its case and step", async () => {
    vi.spyOn(api, "workpackage").mockResolvedValue(batch({ owner_case: { id: "wp-00000000c001", name: "April case", step: "process",
      step_title: "Processing", tab: "documents" } }));
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    // 261 (B1c): a case's step's batch is shown under its case's address
    render(<WorkpackageDetail wpId="wp-00000000b001" route={{ view: "workpackages", wpId: "wp-00000000b001", inCase: "wp-00000000c001" }} />);
    const crumbs = await screen.findByRole("navigation", { name: "Location" });
    expect(within(crumbs).getByRole("link", { name: "Cases" }).getAttribute("href")).toBe("#/cases");
    expect(within(crumbs).getByRole("link", { name: "April case" }).getAttribute("href")).toBe("#/cases/wp-00000000c001/documents");
    expect(crumbs.textContent).toContain("Processing");
  });

  it("leads any other batch to the list of every batch, and a case row to the case's own address", async () => {
    vi.spyOn(api, "workpackage").mockResolvedValue(batch());
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<WorkpackageDetail wpId="wp-00000000b001" route={{ view: "workpackages", wpId: "wp-00000000b001" }} />);
    const crumbs = await screen.findByRole("navigation", { name: "Location" });
    expect(within(crumbs).getByRole("link", { name: "All document batches" }).getAttribute("href")).toBe("#/workpackages");
    expect(linkOf({ key: "name", label: "Case", kind: "text", link: "case" } as never, { _wp: "wp-00000000c001" } as never))
      .toBe("#/cases/wp-00000000c001");
  });
});
