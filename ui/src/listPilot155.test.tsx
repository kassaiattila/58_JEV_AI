// 155: the redesigned work package list — a date-time cell in two parts (the time drops under the date in a narrow
// column) and the stage track before the next step. Both are visual only: the text a person or a screen reader gets
// stays the same.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsColumn, type DsPage, type DsQuery } from "./api";
import { DataTable } from "./components/DataTable";
import { stepLabel, when } from "./labels";
import { Workpackages } from "./views/Workpackages";

const COLS: DsColumn[] = [
  { key: "name", label: "Name", kind: "text", hidden: false, labels: null, link: "workpackage" },
  { key: "next_label", label: "Next step", kind: "text", hidden: false, labels: null, link: "next" },
  { key: "created_at", label: "Created", kind: "datetime", hidden: false, labels: null },
];
const CREATED = "2026-10-13T17:01:00Z";
const REVIEW = stepLabel("review", { n: 26 }, "");
const DONE = stepLabel("done", {}, "released");

function page(query: DsQuery): DsPage {
  const rows = [
    { _key: "wp-1", _wp: "wp-1", _stage: "review", name: "Invoices 2026", next_label: "review", next_code: "review",
      _next_params: { n: 26 }, created_at: CREATED },
    { _key: "wp-2", _wp: "wp-2", _stage: "result", name: "Statements 2026", next_label: "released", next_code: "done",
      _next_params: {}, created_at: CREATED },
  ];
  return {
    dataset: { name: "workpackages", label: "Work packages", scope: [], optional_scope: [] }, columns: COLS, rows, total: rows.length,
    matched: rows.length, offset: query.offset ?? 0, limit: query.limit ?? 100, facets: {},
  };
}

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe("redesigned work package list (155)", () => {
  it("shows a date-time as its date and its time, while its text stays the formatted value", async () => {
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
    const { container } = render(<DataTable dataset="workpackages" label="Work packages" />);
    await waitFor(() => expect(container.querySelectorAll('td[data-col="created_at"]').length).toBe(2));
    const cell = container.querySelector('td[data-col="created_at"]')!;
    const parts = cell.querySelectorAll(".when > span");
    expect(parts.length).toBe(2);
    expect(parts[1].textContent).toMatch(/^\d{1,2}[:.]\d{2}/);
    expect(cell.textContent).toBe(when(CREATED));
    expect(container.querySelector("table")?.getAttribute("data-dataset")).toBe("workpackages");
  });

  it("puts the stage track before the next step, marking where the package stands, without changing the link's name", async () => {
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
    const { container } = render(<Workpackages route={{ view: "workpackages" }} />);
    const review = await screen.findByRole("link", { name: REVIEW });
    const track = review.querySelector(".track")!;
    expect(track.getAttribute("aria-hidden")).toBe("true");
    expect(track.classList.contains("t-todo")).toBe(true);
    expect([...track.querySelectorAll("i")].map((i) => i.className)).toEqual(["passed", "current", ""]);
    const done = screen.getByRole("link", { name: DONE }).querySelector(".track")!;
    expect(done.classList.contains("t-done")).toBe(true);
    expect(container.querySelectorAll(".track").length).toBe(2);
  });
});
