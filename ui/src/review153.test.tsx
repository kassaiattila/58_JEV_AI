// 153 (review): Review says what an invoice's VAT check found (it shared its code with a statement's totals check and
// showed the statement's sentence). Artificial data, no service.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsPage, type RunView, type Workpackage } from "./api";
import { checkText } from "./labels";
import { itemChanged, ReviewWorkspace } from "./views/ReviewWorkspace";

afterEach(() => { vi.restoreAllMocks(); window.location.hash = ""; });

describe("153 an invoice's VAT check", () => {
  it("reads as the invoice's check, with the difference", () => {
    expect(checkText("totals.mismatch", "net+vat-gross=-100.00 (HUF)")).toMatch(/^A nettó összeg és az ÁFA nem adja ki a bruttó összeget \(eltérés: /);
  });

  it("leaves a statement's totals check as it was", () => {
    expect(checkText("totals.mismatch", "debit total 100.00 vs 90.00")).toBe("Az összesített terhelés / jóváírás nem egyezik a tranzakciókkal");
  });
});

describe("153 Review keeps its place and tells the package page", () => {
  it("an item the queue chose stays chosen after a change, and the package page reloads", () => {
    const reloadRun = vi.fn();
    const onChanged = vi.fn();
    itemChanged("wp-1", true, "b".repeat(64), reloadRun, onChanged);
    expect(window.location.hash).toBe(`#/workpackages/wp-1/review/${"b".repeat(64)}`);
    expect(reloadRun).toHaveBeenCalledTimes(1);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("an item named in the address stays as it is", () => {
    window.location.hash = "#/workpackages/wp-1/review/a";
    itemChanged("wp-1", false, "a", () => {});
    expect(window.location.hash).toBe("#/workpackages/wp-1/review/a");
  });

  it("the queue scrolls the active item into view", async () => {
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    const runs: DsPage = { dataset: { name: "runs", label: "Runs", scope: ["workpackage_id"], optional_scope: [], natural_sort: [] },
      columns: [], rows: [{ _key: "run-1", run_id: "run-1" }], total: 1, matched: 1, offset: 0, limit: 1, facets: {} };
    vi.spyOn(api, "datasetQuery").mockResolvedValue(runs);
    vi.spyOn(api, "run").mockResolvedValue({
      run: { run_id: "run-1", approval: null, items: [{ item_id: "a", status: "done" }, { item_id: "b", status: "done" }],
        input: { items: [{ item_id: "a", source_path: "C:/x/a.pdf" }, { item_id: "b", source_path: "C:/x/b.pdf" }] } },
      titles: {}, open_reasons: { b: [{ id: 1, reason: "detect:low_conf:invoice_hu", producer: "flow", run_id: "run-1:b", field: null }] },
      earlier_open_reasons: {},
    } as unknown as RunView);
    vi.spyOn(api, "item").mockReturnValue(new Promise(() => {}));
    render(<ReviewWorkspace wp={{ id: "wp-1" } as Workpackage} />);
    const active = await screen.findByRole("button", { pressed: true });
    expect(active.textContent).toContain("b.pdf");
    // 158: the scroll runs in an effect after the render; on a busy machine it may come after the button shows
    await waitFor(() => expect(scrolled).toHaveBeenCalled());
  });
});
