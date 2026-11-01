// 265 (code review UI-10): the period grid says when it shows only part of the cases (it cut them silently above 1 000),
// and groups its cases by party and month once. Synthetic data, a mocked service.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DsPage, type DsRow } from "../api";
import { setLanguage } from "../i18n";
import { CaseList } from "./CaseList";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const row = (month: string, n: number): DsRow => ({
  name: `Invented ${month} ${n}`, process: "Monthly reconciliation", party: "Invented Consulting Ltd",
  period: `2026-${month}-01 – 2026-${month}-28`, steps: `${n}/3`, waits_for: "person_start", status: "open",
  _key: `wp-00000000b${month}${n}`, _wp: `wp-00000000b${month}${n}`, _track: [],
});
const page = (rows: DsRow[], matched: number): DsPage => ({
  dataset: { name: "cases", label: "Cases", scope: [], optional_scope: [] }, columns: [{ key: "name", label: "Case", kind: "text" }],
  rows, total: matched, matched, offset: 0, limit: 1000, facets: {},
} as unknown as DsPage);
const COUNTS = { views: { waiting: 0, mine: 0, open: 2, closed: 0 },
  processes: [{ pack: "monthly_reconciliation", title: "Monthly reconciliation", open: 2, all: 1500, repeats: true }] };

describe("265 the period grid", () => {
  it("names the part it shows and puts each case in its party's month", async () => {
    vi.spyOn(api, "caseViews").mockResolvedValue(COUNTS);
    vi.spyOn(api, "datasetQuery").mockImplementation(async (name) =>
      (name === "handovers" ? page([], 0) : page([row("03", 1), row("04", 2)], 1500)));
    render(<CaseList process="monthly_reconciliation" />);
    const grid = await screen.findByRole("region", { name: "Period grid" });
    expect(within(grid).getByRole("status").textContent).toBe("The grid shows 2 of 1500 cases.");
    expect(within(grid).getByRole("link", { name: "1/3" }).getAttribute("href")).toBe("#/cases/wp-00000000b031");
    expect(within(grid).getByRole("link", { name: "2/3" })).toBeTruthy();
  });
});
