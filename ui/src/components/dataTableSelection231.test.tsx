// 231 (stage D0, D0-f; the reassessment of 2026-10-26, F14, P11): an action on the selected rows acts on every row the
// count names. The shared table kept a selection across its pages, and its count named every selected row, but an
// action got only the selected rows of the page on screen: two rows picked on the first page and three on the second
// showed "5 selected" while the action took three. The table now hands an action every selected row, as it last saw
// it on any page, and says how many of them are not on the page shown. Synthetic data, a mocked service.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type DsColumn, type DsPage, type DsQuery, type DsRow } from "../api";
import { setLanguage } from "../i18n";
import { DataTable } from "./DataTable";

const COLS: DsColumn[] = [{ key: "name", label: "Name", kind: "text", hidden: false, labels: null }];
const ALL = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"].map((name, i) => ({ _key: `k${i + 1}`, name }));

function page(query: DsQuery, rows = ALL): DsPage {
  const needle = (query.q ?? "").toLowerCase();
  const matched = rows.filter((r) => r.name.toLowerCase().includes(needle));
  const offset = query.offset ?? 0;
  return {
    dataset: { name: "invented", label: "Invented", scope: [], optional_scope: [] }, columns: COLS,
    rows: matched.slice(offset, offset + (query.limit ?? 100)), total: rows.length, matched: matched.length, offset,
    limit: query.limit ?? 100, facets: {},
  };
}

beforeEach(async () => { await setLanguage("en"); });
afterEach(() => { vi.restoreAllMocks(); });

function Table({ onAct }: { onAct: (rows: DsRow[]) => void }) {
  return (
    <DataTable dataset="invented" label="Invented rows" selectable initial={{ limit: 2 }}
      selectionActions={(rows) => <button type="button" onClick={() => onAct(rows)}>{`Act on ${rows.length}`}</button>} />
  );
}

const pick = async (name: string) => {
  const row = (await screen.findByText(name)).closest("tr")!;
  await userEvent.click(within(row).getByRole("checkbox"));
};

describe("the selection across pages", () => {
  it("hands an action every selected row the count names", async () => {
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
    const onAct = vi.fn();
    render(<Table onAct={onAct} />);
    await pick("Alpha");
    await pick("Bravo");
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    await pick("Charlie");
    expect(screen.getByText(/3 rows selected/)).toBeTruthy();
    expect(screen.getByText(/2 of them not on this page/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Act on 3" }));
    expect(onAct.mock.calls[0][0].map((r: DsRow) => r._key).sort()).toEqual(["k1", "k2", "k3"]);
  });

  it("keeps a row selected before a search narrowed the list, and says it is not shown", async () => {
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
    const onAct = vi.fn();
    render(<Table onAct={onAct} />);
    await pick("Alpha");
    await userEvent.type(screen.getByRole("searchbox"), "Bravo");
    await waitFor(() => expect(screen.queryByText("Alpha")).toBeNull());  // the search asks the service after a pause
    await pick("Bravo");
    expect(screen.getByText(/2 rows selected/)).toBeTruthy();
    expect(screen.getByText(/1 of them not on this page/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Act on 2" }));
    expect(onAct.mock.calls[0][0].map((r: DsRow) => r.name).sort()).toEqual(["Alpha", "Bravo"]);
  });

  it("hands an action the row as it was last seen on its page", async () => {
    let rows = ALL;
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q, rows));
    const onAct = vi.fn();
    render(<Table onAct={onAct} />);
    await pick("Alpha");
    rows = ALL.map((r) => (r._key === "k1" ? { ...r, name: "Alpha renamed" } : r));
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    await userEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await screen.findByText("Alpha renamed");
    await userEvent.click(screen.getByRole("button", { name: "Act on 1" }));
    expect(onAct.mock.calls[0][0][0].name).toBe("Alpha renamed");
  });

  it("clears the selection with its count", async () => {
    vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q));
    render(<Table onAct={vi.fn()} />);
    await pick("Alpha");
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    await pick("Charlie");
    await userEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.queryByText(/rows selected/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Act on/ })).toBeNull();
  });
});
