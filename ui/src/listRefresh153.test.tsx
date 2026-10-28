// 153 (the owner's questions of 2026-10-13): the package list answers at once while it is rebuilt behind and says so,
// links its count of older runs to supersede to the processing section, and the package's tabs follow the run the next
// step is about. The human work left on a run names only the parts that are not zero. Artificial data, no service.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsColumn, type DsPage, type WorkpackageView } from "./api";
import { DataTable, linkOf } from "./components/DataTable";
import { REFRESHING_RETRY_MS } from "./hooks";
import { setLanguage } from "./i18n";
import { OlderRunsOffer } from "./views/ProcessStage";
import { SupersedeOffer } from "./views/Runs";
import { stageStatus } from "./views/WorkpackageDetail";

afterEach(async () => { vi.restoreAllMocks(); vi.useRealTimers(); await setLanguage("hu"); });

const COLS: DsColumn[] = [
  { key: "name", label: "Név", kind: "text", hidden: false, labels: null, link: "workpackage" },
  { key: "older_runs", label: "Older runs to supersede", kind: "number", hidden: false, labels: null, link: "process", alert: true },
];

function page(name: string, refreshing: boolean): DsPage {
  return {
    dataset: { name: "workpackages", label: "Iratkötegek", scope: [], optional_scope: [] }, columns: COLS,
    rows: [{ _key: "wp-1", _wp: "wp-1", name, older_runs: 2 }], total: 1, matched: 1, offset: 0, limit: 100, facets: {},
    ...(refreshing ? { refreshing: true } : {}),
  };
}

describe("153 the package list", () => {
  it("shows its last rows at once, says it is updating and asks again soon", async () => {
    const query = vi.spyOn(api, "datasetQuery")
      .mockResolvedValueOnce(page("Régi név", true))
      .mockResolvedValue(page("Új név", false));
    render(<DataTable dataset="workpackages" label="Iratkötegek" pollMs={60_000} />);
    await screen.findByText("Régi név");
    expect(screen.getByText("Frissül…")).toBeTruthy();
    // asked again after the short retry, long before the next poll
    await waitFor(() => expect(screen.getByText("Új név")).toBeTruthy(), { timeout: REFRESHING_RETRY_MS + 2000 });
    expect(query).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Frissül…")).toBeNull();
  });

  it("links the older runs to supersede to the package's processing section", () => {
    expect(linkOf(COLS[1], { _key: "wp-1", _wp: "wp-1" })).toBe("#/workpackages/wp-1/process");
  });
});

describe("153 the package's tabs follow the current run", () => {
  it("shows the to-dos of the earlier live run a later stopped run would hide", () => {
    const view = {
      workpackage: { id: "wp-1", items: [] }, readiness: { ready: true },
      last_run: { run_id: "run-2", mode: "apply", status: "cancelled", approval: null, open_reasons: 0, items: 3, items_done: 1 },
      current_run: { run_id: "run-1", mode: "apply", status: "needs_review", approval: null, open_reasons: 169, items: 3, items_done: 3 },
    } as unknown as WorkpackageView;
    const s = stageStatus(view);
    expect(s.review).toBe("169 teendő");
    expect(s.result).toBe("kiadásra vár"); // 172: the package's release
    expect(s.process).toMatch(/leállítva/); // the processing tab still says what happened last
  });
});

describe("153 the human work left on a run names only what is there", () => {
  const RUN = { run_id: "run-000000000001", created_at: "2026-10-01T07:12:06+00:00", by: "run-000000000003", open_reasons: 142 };

  it("on the package page", () => {
    const { rerender } = render(<OlderRunsOffer runs={[{ ...RUN, resolved_reasons: 0, corrected_items: 1 }]} busy={false} onSupersede={() => {}} />);
    expect(screen.getByText(/1 kézzel javított irata a régin marad/)).toBeTruthy();
    expect(screen.queryByText(/0 lezárt/)).toBeNull();
    rerender(<OlderRunsOffer runs={[{ ...RUN, resolved_reasons: 4, corrected_items: 0 }]} busy={false} onSupersede={() => {}} />);
    expect(screen.getByText(/4 lezárt teendője a régin marad/)).toBeTruthy();
    expect(screen.queryByText(/kézzel javított/)).toBeNull();
  });

  it("on the run page", () => {
    const offer = { by: "run-000000000003", open_reasons: 2 };
    const { rerender } = render(<SupersedeOffer offer={{ ...offer, resolved_reasons: 0, corrected_items: 1 }} busy={false} onConfirm={() => {}} />);
    expect(screen.getByText(/Ezen a futáson már 1 iratot kézzel javítottak;/)).toBeTruthy();
    expect(screen.queryByText(/0 teendőt/)).toBeNull();
    rerender(<SupersedeOffer offer={{ ...offer, resolved_reasons: 25, corrected_items: 0 }} busy={false} onConfirm={() => {}} />);
    expect(screen.getByText(/Ezen a futáson már 25 teendőt lezártak;/)).toBeTruthy();
    expect(screen.queryByText(/kézzel/)).toBeNull();
  });
});
