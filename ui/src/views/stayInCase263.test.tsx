// 263 (plan E, F2; the owner's decision of 2026-10-31: stay in the case): a run's page leads back to its case by its
// crumbs and names where the work goes on as its main action; an address no page has says so; the header marks the
// part a page belongs to. Synthetic data, a mocked service.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DsPage, type RunView, type WorkpackageView } from "../api";
import { setLanguage } from "../i18n";
import { parseRoute, routeHash } from "../route";
import { RunDetail } from "./Runs";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ""; });

const MAIN = "wp-00000000a264";
const SUB = "wp-00000000b264";
const BATCH = "wp-00000000c264";
const EMPTY: DsPage = {
  dataset: { name: "run_items", label: "Items", scope: [], optional_scope: [] }, columns: [], rows: [], total: 0, matched: 0,
  offset: 0, limit: 50, facets: {},
};

function run(open: number): RunView {
  return {
    run: { run_id: "run-00000000d264", workpackage_id: BATCH, mode: "apply", status: "needs_review", approval: null, actor: "Synthetic reviewer",
      created_at: "2026-10-31T10:00:00Z", finished_at: "2026-10-31T10:05:00Z", recipe_id: "processing", params: {}, items: 3, items_done: 3,
      jobs: { done: 3 } },
    budget: { providers: {} }, tables: [], review_version: "v1", earlier_open_reasons: {},
    open_reasons: open ? { "item-1": Array.from({ length: open }, (_, i) => ({ id: i, reason: "datapoint:invoice_number:uncertain" })) } : {},
  } as unknown as RunView;
}
const BATCH_VIEW = {
  workpackage: { id: BATCH, name: "Invented March invoices", revision: 1, items: [] },
  owner_case: { id: SUB, name: "Invented March · Incoming invoices", step: "process", step_title: "Processing", tab: "documents",
    parent: { id: MAIN, name: "Invented March", step: "invoices", step_title: "Incoming invoices", tab: "overview" } },
} as unknown as WorkpackageView;

describe("stay in the case (263 F2)", () => {
  it("leads a case's run back to its case and step, and names its to-dos as the main action", async () => {
    vi.spyOn(api, "run").mockResolvedValue(run(2));
    vi.spyOn(api, "workpackage").mockResolvedValue(BATCH_VIEW);
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<RunDetail runId="run-00000000d264" />);
    const crumbs = await screen.findByRole("navigation", { name: "Location" });
    expect(await within(crumbs).findByRole("link", { name: "Invented March" })).toBeTruthy();
    expect(within(crumbs).getByRole("link", { name: "Invented March" }).getAttribute("href")).toBe(`#/cases/${MAIN}/invoices`);
    expect(within(crumbs).getByRole("link", { name: "Cases" }).getAttribute("href")).toBe("#/cases");
    const review = await screen.findByRole("link", { name: "Review: 2 to-dos →" });
    expect(review.className).toContain("primary");
    expect(review.getAttribute("href")).toBe(`#/cases/${MAIN}/batches/${BATCH}/review`);
  });

  it("says when an address has no page, and still opens the cases with none", () => {
    expect(parseRoute("#/nothing-here/1")).toEqual({ view: "not-found", path: "nothing-here/1" });
    expect(routeHash(parseRoute("#/nothing-here/1"))).toBe("#/nothing-here/1");
    expect(parseRoute("#/")).toEqual({ view: "case-list" });
    expect(parseRoute("#/mailbox")).toEqual({ view: "settings", section: "mailboxes" });  // an older address still leads
  });
});
