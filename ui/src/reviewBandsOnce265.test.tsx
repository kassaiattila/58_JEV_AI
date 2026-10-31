// 265 (code review UI-04): the confidence bands load once for the review, and an item's first field filter waits for
// them. They were loaded again for every item, and the first drawing used the defaults, without the GPT path's band,
// so an item opened on the wrong filter. Artificial data, no service.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsPage, type ItemResult, type RunView, type Workpackage } from "./api";
import { setLanguage } from "./i18n";
import { ReviewWorkspace } from "./views/ReviewWorkspace";

const RUN = "run-000000000265";

function item(id: string): ItemResult {
  return {
    run_id: RUN, item_id: id,
    extraction: { doc_type: "invoice_hu", arm: "G", datapoints: { invoice_number: "INV-1" }, field_conf: {}, validation: [],
      final_status: "done", review_reasons: [] },
    correction: { run_id: RUN, item_id: id, revision: 0, fields: {}, sources: {}, confirmed: {}, actor: null, note: null, created_at: null },
    effective: { invoice_number: "INV-1" },
    open_reasons: [], earlier_open_reasons: [],
    // a GPT field at 0.85: certain on the GPT band (0.8), uncertain on the shared one (0.9)
    provenance: { invoice_number: { status: "located", method: "gpt", alternatives: [], confidence: 0.85,
      confidence_basis: { source: "gpt" } } },
    source: null,
  } as unknown as ItemResult;
}

function runView(): RunView {
  const items = ["a", "b"].map((id) => ({ item_id: id, source_path: `C:/invented/${id}.pdf` }));
  return {
    run: { run_id: RUN, workpackage_id: "wp-b", input: { items }, items: items.map((i) => ({ item_id: i.item_id, status: "done", final_status: "done" })),
      approval: null },
    open_reasons: {}, earlier_open_reasons: {}, titles: {}, engine: "gpt",
  } as unknown as RunView;
}

afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

describe("265 the review's confidence bands", () => {
  it("are asked once, and an item's filter waits for them", async () => {
    await setLanguage("en");
    vi.spyOn(api, "datasetQuery").mockResolvedValue({ rows: [{ _key: RUN }], total: 1 } as unknown as DsPage);
    vi.spyOn(api, "run").mockResolvedValue(runView());
    vi.spyOn(api, "item").mockImplementation(async (_run, id) => item(id));
    let answer: (v: { confidence_bands: Record<string, unknown> }) => void = () => {};
    const settings = vi.spyOn(api, "settings").mockReturnValue(new Promise((ok) => { answer = ok; }) as never);
    const { rerender } = render(<ReviewWorkspace wp={{ id: "wp-b" } as Workpackage} itemId="a" />);
    await waitFor(() => expect(document.getElementById("fv-invoice_number")).not.toBeNull());
    // no filter chosen on the defaults (the GPT field would count as uncertain on them)
    expect(screen.queryByRole("group", { name: "Filter the fields" })).toBeNull();
    answer({ confidence_bands: { confident: 0.9, check: 0.5, gpt: { confident: 0.8, check: 0.4 } } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Uncertain (0)" })).toBeTruthy());
    rerender(<ReviewWorkspace wp={{ id: "wp-b" } as Workpackage} itemId="b" />);
    await waitFor(() => expect(api.item).toHaveBeenCalledWith(RUN, "b"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Uncertain (0)" })).toBeTruthy());
    expect(settings).toHaveBeenCalledTimes(1);
  });
});
