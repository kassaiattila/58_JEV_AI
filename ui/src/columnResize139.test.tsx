// 139 (the owner's request of 2026-10-10): column widths set by dragging or with the arrow keys, kept per table; the
// reset returns the automatic layout. Expectations use the English interface; the last test checks that every new
// label has a Hungarian translation.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type DsColumn, type DsPage, type DsQuery, type ListColumn } from "./api";
import { DataTable } from "./components/DataTable";
import { loadWidths, MIN_WIDTH } from "./components/ColumnResize";
import hungarian from "./i18n/hu-native.json";
import { setLanguage } from "./i18n";
import { ListTable } from "./review/ListTable";

const COLS: DsColumn[] = [
  { key: "file", label: "File", kind: "text", hidden: false, labels: null },
  { key: "value", label: "Value", kind: "money", hidden: false, labels: null },
];

function page(query: DsQuery): DsPage {
  return {
    dataset: { name: "datapoints", label: "Data points", scope: [], optional_scope: [] }, columns: COLS,
    rows: [{ _key: "a", file: "a_very_long_file_name_without_any_space.pdf", value: "12583.00" }],
    total: 1, matched: 1, offset: query.offset ?? 0, limit: query.limit ?? 100, facets: {},
  };
}

const colWidths = (table: HTMLElement) => [...table.querySelectorAll("col")].map((c) => (c as HTMLElement).style.width);

beforeEach(async () => { localStorage.clear(); await setLanguage("en"); });
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe("column widths in the shared table", () => {
  it("starts in the automatic layout; an arrow key fixes the widths, which are kept per table", async () => {
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
    const { unmount } = render(<DataTable dataset="datapoints" label="Data" />);
    const table = await screen.findByRole("table", { name: "Data" });
    expect(table.classList.contains("sized")).toBe(false);
    expect(table.querySelector("colgroup")).toBeNull();

    screen.getByRole("separator", { name: "Column width: File" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(table.classList.contains("sized")).toBe(true);
    // jsdom lays nothing out, so the measured width is the minimum; the key adds 16 pixels
    expect(colWidths(table)).toEqual([`${MIN_WIDTH + 16}px`, `${MIN_WIDTH}px`]);
    expect(table.style.width).toBe(`${2 * MIN_WIDTH + 16}px`);
    expect(loadWidths("datapoints")).toEqual({ file: MIN_WIDTH + 16, value: MIN_WIDTH });
    unmount();

    render(<DataTable dataset="datapoints" label="Data" />);
    const again = await screen.findByRole("table", { name: "Data" });
    expect(colWidths(again)).toEqual([`${MIN_WIDTH + 16}px`, `${MIN_WIDTH}px`]);
  });

  it("follows a drag and never goes below the minimum width", async () => {
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
    render(<DataTable dataset="datapoints" label="Data" />);
    const table = await screen.findByRole("table", { name: "Data" });
    const edge = screen.getByRole("separator", { name: "Column width: Value" });
    fireEvent.pointerDown(edge, { button: 0, clientX: 100, pointerId: 1 });
    fireEvent.pointerMove(edge, { clientX: 220, pointerId: 1 });
    fireEvent.pointerUp(edge, { clientX: 220, pointerId: 1 });
    expect(colWidths(table)).toEqual([`${MIN_WIDTH}px`, `${MIN_WIDTH + 120}px`]);
    expect(loadWidths("datapoints").value).toBe(MIN_WIDTH + 120);

    fireEvent.pointerDown(edge, { button: 0, clientX: 300, pointerId: 1 });
    fireEvent.pointerMove(edge, { clientX: 0, pointerId: 1 });
    fireEvent.pointerUp(edge, { clientX: 0, pointerId: 1 });
    expect(loadWidths("datapoints").value).toBe(MIN_WIDTH);
  });

  it("the column menu resets the widths; its button shows only while a width is set", async () => {
    localStorage.setItem("jav.table.datapoints.widths", JSON.stringify({ file: 300, value: 120, bogus: "x" }));
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
    render(<DataTable dataset="datapoints" label="Data" />);
    const table = await screen.findByRole("table", { name: "Data" });
    expect(colWidths(table)).toEqual(["300px", "120px"]);

    await userEvent.click(screen.getByRole("button", { name: /Columns/ }));
    await userEvent.click(screen.getByRole("button", { name: "Reset column widths" }));
    await waitFor(() => expect(table.classList.contains("sized")).toBe(false));
    expect(localStorage.getItem("jav.table.datapoints.widths")).toBeNull();
    expect(screen.queryByRole("button", { name: "Reset column widths" })).toBeNull();
  });
});

describe("column widths in a line-item list", () => {
  const COLUMNS = [{ name: "description", kind: "text" }, { name: "amount", kind: "money" }] as ListColumn[];
  const props = {
    field: "transactions", columns: COLUMNS, rows: [{ description: "Card purchase", amount: "-44970" }], badRows: [],
    focusRow: null, edited: false, corrected: false, readOnly: false, onChange: () => {}, onRevert: () => {},
  };

  it("keeps the widths per list field, and the list header resets them", async () => {
    render(<ListTable {...props} />);
    const table = screen.getByRole("table");
    const edges = within(table).getAllByRole("separator");
    expect(edges).toHaveLength(2);
    edges[0].focus();
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    expect(table.classList.contains("sized")).toBe(true);
    expect(loadWidths("list.transactions")).toEqual({ _n: MIN_WIDTH, description: MIN_WIDTH + 32, amount: MIN_WIDTH, _delete: MIN_WIDTH });

    await userEvent.click(screen.getByRole("button", { name: "Reset column widths" }));
    expect(table.classList.contains("sized")).toBe(false);
    expect(loadWidths("list.transactions")).toEqual({});
  });
});

it("every new label has a Hungarian translation", () => {
  const hu = hungarian as Record<string, string>;
  for (const key of ["Column width: {{label}}", "Drag to change the column width (or use the arrow keys)", "Reset column widths"]) {
    expect(hu[key], key).toBeTruthy();
    expect(hu[key]).not.toBe(key);
  }
});
