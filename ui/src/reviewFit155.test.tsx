// 155: the review panes end just above the bottom of the screen however tall the header above them is — the grid
// measures its own top and gives it to the panes as `--review-offset` (and measures again when the window is resized).
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsPage, type RunView, type Workpackage } from "./api";
import { ReviewWorkspace } from "./views/ReviewWorkspace";

afterEach(() => { vi.restoreAllMocks(); });

describe("review panes fit the screen (155)", () => {
  it("sets the panes' offset from where the grid starts, and again after a resize", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    const runs: DsPage = { dataset: { name: "runs", label: "Runs", scope: ["workpackage_id"], optional_scope: [], natural_sort: [] },
      columns: [], rows: [{ _key: "run-1", run_id: "run-1" }], total: 1, matched: 1, offset: 0, limit: 1, facets: {} };
    vi.spyOn(api, "datasetQuery").mockResolvedValue(runs);
    vi.spyOn(api, "run").mockResolvedValue({
      run: { run_id: "run-1", approval: null, items: [{ item_id: "a", status: "done" }],
        input: { items: [{ item_id: "a", source_path: "C:/x/a.pdf" }] } },
      titles: {}, open_reasons: {}, earlier_open_reasons: {},
    } as unknown as RunView);
    vi.spyOn(api, "item").mockReturnValue(new Promise(() => {}));
    let top = 280;
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(() => ({ top, bottom: top, left: 0, right: 0, width: 0, height: 0, x: 0, y: top, toJSON: () => ({}) }) as DOMRect);
    const { container } = render(<ReviewWorkspace wp={{ id: "wp-1" } as Workpackage} />);
    await screen.findByRole("button", { pressed: true });
    const grid = container.querySelector(".review-grid") as HTMLElement;
    expect(grid.style.getPropertyValue("--review-offset")).toBe("292px");
    top = 240;
    act(() => { window.dispatchEvent(new Event("resize")); });
    expect(grid.style.getPropertyValue("--review-offset")).toBe("252px");
  });
});
