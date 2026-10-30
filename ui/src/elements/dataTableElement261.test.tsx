// 261 (plan B, B1f; the owner's decision of 2026-10-29: the three shared elements now, each with a first user): the
// shared element `data_table` shows the dataset its pack's element names, scoped by the case, under the element's label.
// Synthetic data, a mocked service.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type DsPage } from "../api";
import { setLanguage } from "../i18n";
import { DataTableView } from "./DataTableElement";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const CASE = "wp-00000000f262";
const EMPTY: DsPage = {
  dataset: { name: "started_cases", label: "Started cases", scope: ["case_id"], optional_scope: [] }, columns: [], rows: [],
  total: 0, matched: 0, offset: 0, limit: 50, facets: {},
};

describe("the shared data table (261 B1f)", () => {
  it("shows the dataset its element names, scoped by the case, under the element's label", async () => {
    const query = vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<DataTableView caseId={CASE} page={{} as CaseView} onChanged={() => {}}
      element={{ type: "data_table", step: null, dataset: "started_cases", label: "Started cases", data: { scope: { case_id: CASE } } }} />);
    expect(screen.getByRole("heading", { name: "Started cases" })).toBeTruthy();
    await waitFor(() => expect(query).toHaveBeenCalled());
    expect(query.mock.calls[0][0]).toBe("started_cases");
    expect(query.mock.calls[0][1]).toEqual({ case_id: CASE });
    expect(await screen.findByText("Nothing to show yet.")).toBeTruthy();
  });
});
