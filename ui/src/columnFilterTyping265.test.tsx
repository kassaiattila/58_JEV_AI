// 265 (code review UI-02): a column filter's form keeps what is being typed while the list renders again. It was reset
// from the active filters on every render while open, so on a list that refreshes every few seconds the text being
// typed was wiped. Artificial data, no service.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, type DsColumn, type DsPage, type DsQuery } from "./api";
import { DataTable } from "./components/DataTable";
import { setLanguage } from "./i18n";

const COLS: DsColumn[] = [{ key: "file", label: "Irat", kind: "text", hidden: false, labels: null }];

function page(query: DsQuery): DsPage {
  return {
    dataset: { name: "datapoints", label: "Adatpontok", scope: ["run_id"], optional_scope: [] }, columns: COLS,
    rows: [{ _key: "a", file: "a.pdf" }], total: 1, matched: 1, offset: query.offset ?? 0, limit: query.limit ?? 100, facets: {},
  };
}

beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

it("the text typed into an open column filter survives a render of the list", async () => {
  vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
  const { rerender } = render(<DataTable dataset="datapoints" scope={{ run_id: "run-1" }} label="Adatpontok" />);
  expect(await screen.findByText("a.pdf")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: /^Filter: / }));
  const box = screen.getAllByRole("textbox").at(-1) as HTMLInputElement;
  await userEvent.type(box, "szam");
  rerender(<DataTable dataset="datapoints" scope={{ run_id: "run-1" }} label="Adatpontok " />);  // the list renders again
  expect((screen.getAllByRole("textbox").at(-1) as HTMLInputElement).value).toBe("szam");
});
