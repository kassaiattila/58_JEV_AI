// 183 (backlog Q-tenytabla-magas-sorok): a column that limits its lines shows at most that many lines of a cell, with
// the full value as the cell's tooltip; another column is drawn as before. Artificial data, no service.
import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, type DsColumn, type DsPage } from "./api";
import { DataTable } from "./components/DataTable";

afterEach(() => vi.restoreAllMocks());

const LONG = "01_Signed_Example_Person_cost_bearing_undertaking_statement_for_an_employee_v100.pdf";
const COLS: DsColumn[] = [
  { key: "file", label: "Document", kind: "text", hidden: false, labels: null, wrap: "anywhere", clamp: 2 },
  { key: "property", label: "Property", kind: "text", hidden: false, labels: null },
];

it("a column that limits its lines clamps its cells and keeps the full value as the tooltip", async () => {
  vi.spyOn(api, "datasetQuery").mockResolvedValue({
    dataset: { name: "native_facts", label: "Facts", scope: ["run_id"], optional_scope: [] }, columns: COLS,
    rows: [{ _key: "f1", file: LONG, property: "signed on" }],
    total: 1, matched: 1, offset: 0, limit: 100, facets: {},
  } as unknown as DsPage);
  render(<DataTable dataset="native_facts" scope={{ run_id: "run-1" }} label="Facts" />);
  const clamped = (await screen.findByText(LONG)).closest(".dt-clamp") as HTMLElement;
  expect(clamped.title).toBe(LONG);
  expect(clamped.style.webkitLineClamp).toBe("2");
  expect(clamped.closest("td")?.dataset.wrap).toBe("anywhere");
  expect(screen.getByText("signed on").closest(".dt-clamp")).toBeNull();
});
