// 264 (plan G, G1): a row's action buttons stay the same buttons when the page renders again with a new actions
// function (they used to be rebuilt, so a button could be swapped under a click or lose the keyboard focus); the
// newest function still answers the click. Synthetic rows.
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsPage } from "../api";
import { DataTable } from "./DataTable";

afterEach(() => vi.restoreAllMocks());

const PAGE: DsPage = { dataset: { name: "things", label: "Things", scope: [], optional_scope: [] },
  columns: [{ key: "name", label: "Name", kind: "text", hidden: false, labels: null }],
  rows: [{ _key: "a", name: "Alpha" }], total: 1, matched: 1, offset: 0, limit: 100, facets: {} };

describe("a row's actions", () => {
  it("keep their buttons when the page renders again, and answer with the newest function", async () => {
    vi.spyOn(api, "datasetQuery").mockResolvedValue(PAGE);
    const first = vi.fn();
    const second = vi.fn();
    const table = (fn: () => void) => (
      <DataTable dataset="things" label="Things" actions={(row) => <button type="button" onClick={fn}>Do {String(row.name)}</button>} />
    );
    const { rerender } = render(table(first));
    const button = await screen.findByRole("button", { name: "Do Alpha" });
    rerender(table(second));
    expect(screen.getByRole("button", { name: "Do Alpha" })).toBe(button);
    fireEvent.click(button);
    expect(second).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();
  });
});
