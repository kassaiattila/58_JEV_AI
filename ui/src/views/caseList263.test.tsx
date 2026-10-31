// 263 (plan E, F3; the owner's decisions of 2026-10-30: views, groups and a period grid): the case list's views stand in
// the left panel with their counts; a view filters the list, which is grouped by process at first; a case's steps are
// marks; a process repeated by period shows its period grid. Synthetic data, a mocked service.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DsPage, type DsRow } from "../api";
import { setLanguage } from "../i18n";
import { CaseList } from "./CaseList";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const ROW: DsRow = {
  name: "Invented March", process: "Monthly reconciliation", party: "Invented Consulting Ltd", period: "2026-03-01 – 2026-03-31",
  steps: "1/3", step: "Incoming invoices › Processing", waits_for: "person_start", owner: "Synthetic reviewer", status: "open",
  _key: "wp-00000000a265", _wp: "wp-00000000a265",
  _track: [{ title: "Incoming invoices", state: "running" }, { title: "Bank statements", state: "done" }, { title: "Reconciliation", state: "waiting" }],
};
const page = (rows: DsRow[]): DsPage => ({
  dataset: { name: "cases", label: "Cases", scope: [], optional_scope: [] },
  columns: [{ key: "name", label: "Case", kind: "text", link: "case" }, { key: "steps", label: "Steps", kind: "text" },
    { key: "step", label: "Current step", kind: "text" }, { key: "waits_for", label: "Waits for", kind: "enum", labels: { person_start: "A person's start" } }],
  rows, total: rows.length, matched: rows.length, offset: 0, limit: 50, facets: {},
} as unknown as DsPage);
const COUNTS = { views: { waiting: 1, mine: 2, open: 3, closed: 4 },
  processes: [{ pack: "monthly_reconciliation", title: "Monthly reconciliation", open: 3, all: 5, repeats: true }] };

describe("the case list (263 F3)", () => {
  it("shows the views with their counts and filters the list by the chosen one for the person", async () => {
    vi.spyOn(api, "caseViews").mockResolvedValue(COUNTS);
    const query = vi.spyOn(api, "datasetQuery").mockImplementation(async (name) => (name === "handovers" ? page([]) : page([ROW])));
    render(<CaseList shown="waiting" />);
    const views = await screen.findByRole("navigation", { name: "Views" });
    expect(await within(views).findByText("Cases waiting for me")).toBeTruthy();
    expect(views.textContent).toContain("Monthly reconciliation");
    expect(await screen.findByRole("heading", { level: 1, name: "Cases waiting for me" })).toBeTruthy();
    expect(query).toHaveBeenCalledWith("cases", { view: "waiting", actor: "Synthetic reviewer" }, expect.objectContaining({ group: "process" }));
    // a case's steps as marks, each named; a sub-case's step in its main case's row
    expect(await screen.findByLabelText("Incoming invoices: in progress; Bank statements: done; Reconciliation: not started")).toBeTruthy();
    expect(screen.getByText("Incoming invoices › Processing")).toBeTruthy();
  });

  it("shows a process repeated by period with its period grid, a case in its party's month", async () => {
    vi.spyOn(api, "caseViews").mockResolvedValue(COUNTS);
    vi.spyOn(api, "datasetQuery").mockImplementation(async (name) => (name === "handovers" ? page([]) : page([ROW])));
    render(<CaseList process="monthly_reconciliation" />);
    const grid = await screen.findByRole("region", { name: "Period grid" });
    expect(within(grid).getByRole("columnheader", { name: "2026-03" })).toBeTruthy();
    const cell = await within(grid).findByRole("link", { name: "1/3" });
    expect(cell.getAttribute("href")).toBe("#/cases/wp-00000000a265");
    expect(within(grid).getByRole("rowheader", { name: "Invented Consulting Ltd" })).toBeTruthy();
  });
});
