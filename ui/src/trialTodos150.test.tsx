// 150 (the owner's decision of 2026-10-12): the to-dos of trial runs. A trial run cannot be approved, so its to-dos
// never close by themselves. After a trial with to-dos the package's next step is the live run (the trial's count only
// as information); on the review page the earlier to-dos left by trial runs are hidden by default and a switch shows
// them. Artificial data, no service.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DsPage, type ItemResult, type Reason, type RunView, type Workpackage } from "./api";
import { setLanguage } from "./i18n";
import { stepLabel } from "./labels";
import { resetDrafts } from "./review/drafts";
import { FieldPanel } from "./review/FieldPanel";
import { setShowTrialReasons, visibleEarlier } from "./review/trialReasons";
import { ReviewWorkspace } from "./views/ReviewWorkspace";

const RUN = "run-000000000150";
const ITEM = "d".repeat(64);
const trialReason = (id: number, field: string | null): Reason =>
  ({ id, reason: field ? `pick:low_conf:${field}:0.40` : "parties:same_name", producer: "flow", run_id: "run-trial:x", field, trial: true });
const liveReason = (id: number, field: string | null): Reason =>
  ({ id, reason: field ? `pick:low_conf:${field}:0.45` : "detect:low_conf:invoice_hu", producer: "flow", run_id: "run-live:x", field, trial: false });

beforeEach(() => setActor("Test User"));
afterEach(async () => { resetDrafts(); setShowTrialReasons(false); setActor(""); vi.restoreAllMocks(); await setLanguage("hu"); });

describe("150 the next step after a trial", () => {
  it("is the live run, with the trial's to-dos as information", async () => {
    expect(stepLabel("go_live", { trial_reasons: 462 }, "fallback")).toBe("Próba kész: éles futás (462 teendő a próbában)");
    expect(stepLabel("go_live", {}, "fallback")).toBe("Próba rendben: éles futás"); // a trial without to-dos: as before
    await setLanguage("en");
    expect(stepLabel("go_live", { trial_reasons: 462 }, "fallback")).toBe("Trial finished: live run (462 to-dos in the trial)");
  });
});

describe("150 trial runs' earlier to-dos", () => {
  it("are left out unless the switch is on", () => {
    const reasons = [trialReason(1, null), liveReason(2, null)];
    expect(visibleEarlier(reasons, false).map((r) => r.id)).toEqual([2]);
    expect(visibleEarlier(reasons, true).map((r) => r.id)).toEqual([1, 2]);
  });

  it("the item list counts them only with the switch, which appears when there are any", async () => {
    const runs: DsPage = { dataset: { name: "runs", label: "Runs", scope: ["workpackage_id"], optional_scope: [], natural_sort: [] },
      columns: [], rows: [{ _key: RUN, run_id: RUN }], total: 1, matched: 1, offset: 0, limit: 1, facets: {} };
    vi.spyOn(api, "datasetQuery").mockResolvedValue(runs);
    vi.spyOn(api, "run").mockResolvedValue({
      run: { run_id: RUN, approval: null, items: [{ item_id: "a", status: "done", final_status: "done" }, { item_id: "b", status: "done", final_status: "done" }],
        input: { items: [{ item_id: "a", source_path: "C:/x/a.pdf" }, { item_id: "b", source_path: "C:/x/b.pdf" }] } },
      titles: {}, open_reasons: {},
      earlier_open_reasons: { a: [trialReason(1, null), liveReason(2, null)], b: [trialReason(3, null)] },
    } as unknown as RunView);
    vi.spyOn(api, "item").mockReturnValue(new Promise(() => {}));
    await setLanguage("en");
    render(<ReviewWorkspace wp={{ id: "wp-t" } as Workpackage} itemId="a" />);
    const toggle = await screen.findByRole("checkbox", { name: "trial runs' to-dos too" });
    expect((toggle as HTMLInputElement).checked).toBe(false);
    expect(screen.getAllByText(/earlier to-do/).map((e) => e.textContent)).toEqual(["1 earlier to-dos"]);
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getAllByText(/earlier to-do/).map((e) => e.textContent)).toEqual(["2 earlier to-dos", "1 earlier to-dos"]));
  });

  it("the switch is not offered when no trial run left a to-do", async () => {
    const runs: DsPage = { dataset: { name: "runs", label: "Runs", scope: ["workpackage_id"], optional_scope: [], natural_sort: [] },
      columns: [], rows: [{ _key: RUN, run_id: RUN }], total: 1, matched: 1, offset: 0, limit: 1, facets: {} };
    vi.spyOn(api, "datasetQuery").mockResolvedValue(runs);
    vi.spyOn(api, "run").mockResolvedValue({
      run: { run_id: RUN, approval: null, items: [{ item_id: "a", status: "done", final_status: "done" }],
        input: { items: [{ item_id: "a", source_path: "C:/x/a.pdf" }] } },
      titles: {}, open_reasons: {}, earlier_open_reasons: { a: [liveReason(2, null)] },
    } as unknown as RunView);
    vi.spyOn(api, "item").mockReturnValue(new Promise(() => {}));
    await setLanguage("en");
    render(<ReviewWorkspace wp={{ id: "wp-t" } as Workpackage} itemId="a" />);
    await screen.findByText("1 earlier to-dos");
    expect(screen.queryByRole("checkbox", { name: "trial runs' to-dos too" })).toBeNull();
  });

  it("the field panel shows them at the field and at the bottom only with the switch", async () => {
    const res = {
      run_id: RUN, item_id: ITEM,
      extraction: { doc_type: "invoice_hu", arm: "S", datapoints: { payment_iban: "HU00 1111" }, field_conf: {}, validation: [], final_status: "done", review_reasons: [] },
      correction: { run_id: RUN, item_id: ITEM, revision: 0, fields: {}, sources: {}, confirmed: {}, actor: null, note: null, created_at: null },
      effective: { payment_iban: "HU00 1111" }, open_reasons: [],
      earlier_open_reasons: [trialReason(1, "payment_iban"), trialReason(3, null)],
      provenance: { payment_iban: { status: "located", method: "pick", alternatives: [], confidence: 0.9 } },
      source: null,
    } as unknown as ItemResult;
    await setLanguage("en");
    render(<FieldPanel result={res} fields={["payment_iban"]} bandOf={() => "check"} activeField="payment_iban" onActivate={() => {}}
      selection={{ ids: [], text: "" }} onClearSelection={() => {}} selectMode={false} onSaved={() => {}} onResolved={() => {}}
      onChooseAlternative={() => {}} readOnly={false} hasWords={false} />);
    expect(screen.queryByRole("list", { name: /earlier to-dos/ })).toBeNull();
    expect(screen.queryByText(/Earlier to-dos about the whole document/)).toBeNull();
    act(() => setShowTrialReasons(true));
    expect(await screen.findByRole("list", { name: /earlier to-dos/ })).toBeTruthy();
    expect(screen.getByText(/Earlier to-dos about the whole document \(1\)/)).toBeTruthy();
  });
});
