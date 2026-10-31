// 263 (plan E, E2; the owner's decisions of 2026-10-30: one case, one track): a case's page shows its work left to
// right on one track - the pack's tabs, a multi-step case's steps, the log apart at the right end - with a step's
// sub-case and a step's batch under it, and one main action at the title row's right end. Synthetic data, a mocked
// service.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type DsPage, type SubCaseData, type WorkpackageView } from "../api";
import { setLanguage } from "../i18n";
import { caseUnder, batchOfCase, parseRoute, routeHash, wpHash } from "../route";
import { CasePage, nextAt } from "./CasePage";
import { caseTrack, defaultItem } from "./caseTrack";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ""; });

const MAIN = "wp-00000000a263";
const INVOICES = "wp-00000000b263";
const PAIRING = "wp-00000000c263";
const BATCH = "wp-00000000d263";
const EMPTY: DsPage = {
  dataset: { name: "items", label: "Items", scope: [], optional_scope: [] }, columns: [], rows: [], total: 0, matched: 0,
  offset: 0, limit: 50, facets: {},
};
const step = (title: string, state: string) => ({
  title, uses: "run_case@1", start: "auto" as const, state, phase: null, waiting_for: state === "running" ? "case_closed" : null,
  awaiting_start: false, note: null, result: null, actions: [],
});
const sub = (over: Partial<SubCaseData>): SubCaseData => ({ state: "running", pack: "documents", process: "Documents", case: null, earlier: [], ...over });
const LOG = { id: "history", label: "History", elements: [{ type: "timeline", step: null, data: { events: [] } }] };

function main(invoices: SubCaseData, reconcile: SubCaseData): CaseView {
  return {
    case: { id: MAIN, pack: "monthly_reconciliation", version: "1.0.0", title: "Monthly reconciliation", name: "Invented March", status: "open" },
    steps: { invoices: step("Incoming invoices", invoices.state ?? "running"), reconcile: step("Reconciliation", reconcile.state ?? "waiting") },
    tabs: [{ id: "overview", label: "Overview", elements: [
      { type: "blockers", step: null, data: { status: "open", items: [
        { step: "invoices", kind: "sub_case", note: null, waiting_for: "case_closed", tab: "overview" }] } },
      { type: "sub_case", step: "invoices", data: invoices }, { type: "sub_case", step: "reconcile", data: reconcile }] }, LOG],
    next: { code: "case_sub_case", label: "Continue in its sub-case", stage: "process", tab: "overview" },
  };
}

const PAIRING_PAGE: CaseView = {
  case: { id: PAIRING, pack: "reconciliation", version: "1.0.0", title: "Reconciliation", name: "Invented March · Reconciliation", status: "open",
    parent: { id: MAIN, name: "Invented March", title: "Monthly reconciliation", step: "reconcile", step_title: "Reconciliation", tab: "overview" } },
  steps: {},
  tabs: [{ id: "lines", label: "Lines", elements: [] }, { id: "pairing", label: "Pairing", elements: [] }, LOG],
  next: { code: "pair", label: "Pair the lines", stage: "review", tab: "pairing" },
};

function batch(): WorkpackageView {
  return {
    workpackage: { id: BATCH, name: "March invoices", source_kind: "folder", source_ref: null, revision: 1, status: "open",
      created_at: "2026-10-31T10:00:00Z", updated_at: "2026-10-31T10:00:00Z", items: [] },
    readiness: { workpackage_id: BATCH, ready: true, blockers: [], warnings: [], counts: { items: 0 }, budget: {},
      assignment_revision: 1, input_hash: "0123456789abcdef" },
    next: { code: "review", label: "Review", stage: "review" }, last_run: null, runs: 0,
    owner_case: { id: INVOICES, name: "Invented March · Incoming invoices", step: "process", step_title: "Processing", tab: "documents",
      parent: { id: MAIN, name: "Invented March", step: "invoices", step_title: "Incoming invoices", tab: "overview" } },
  } as unknown as WorkpackageView;
}

describe("one case, one track (263 E2)", () => {
  it("makes a multi-step case's track of its overview and its numbered steps, the log apart", () => {
    const view = main(sub({ state: "done" }), sub({ state: "running", pack: "reconciliation" }));
    const { items, log } = caseTrack(view);
    expect(items.map((x) => [x.id, x.kind, x.n])).toEqual([["overview", "tab", undefined], ["invoices", "step", 1], ["reconcile", "step", 2]]);
    expect(log?.id).toBe("history");
    expect(defaultItem({ ...view, steps: { ...view.steps, invoices: step("Incoming invoices", "done") } }, items)?.id).toBe("reconcile");
  });

  it("names a running sub-case's own next step as the case's, done under its step", () => {
    const view = main(sub({ case: { id: INVOICES, name: "x", status: "open", outcome: null,
      next: { code: "case_package_review", label: "Review the to-dos", stage: "review", tab: "documents" } } }), sub({ state: "waiting" }));
    expect(nextAt(view, caseTrack(view).items)).toEqual({ item: "invoices", sub: "documents", label: "Review the to-dos" });
  });

  it("reads and writes a step's part and an earlier sub-case in the address; a sub-case's batch opens under the main case", () => {
    const at = `#/cases/${MAIN}/reconcile/pairing?of=${PAIRING}`;
    expect(parseRoute(at)).toEqual({ view: "cases", caseId: MAIN, tab: "reconcile", sub: "pairing", of: PAIRING });
    expect(routeHash(parseRoute(at))).toBe(at);
    batchOfCase("wp-00000000e263", "wp-00000000f263");
    caseUnder("wp-00000000f263", MAIN);
    expect(wpHash("wp-00000000e263", "review")).toBe(`#/cases/${MAIN}/batches/wp-00000000e263/review`);
  });

  it("opens the step's sub-case under it: its own track, its next step as the title row's main action", async () => {
    const pages: Record<string, CaseView> = {
      [MAIN]: main(sub({ state: "done" }), sub({ state: "running", pack: "reconciliation", process: "Reconciliation",
        case: { id: PAIRING, name: "Invented March · Reconciliation", status: "open", outcome: null,
          next: { code: "pair", label: "Pair the lines", stage: "review", tab: "pairing" } } })),
      [PAIRING]: PAIRING_PAGE,
    };
    pages[MAIN].steps.invoices = step("Incoming invoices", "done");
    vi.spyOn(api, "casePage").mockImplementation(async (id: string) => pages[id]);
    render(<CasePage caseId={MAIN} tab="reconcile" sub="lines" />);
    const steps = await screen.findByRole("tablist", { name: "The case's steps" });
    expect(within(steps).getByRole("tab", { name: /Reconciliation/ }).getAttribute("aria-selected")).toBe("true");
    const parts = await screen.findByRole("tablist", { name: "The step's parts" });
    expect(within(parts).getAllByRole("tab").map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["1Lines", `#/cases/${MAIN}/reconcile/lines`], ["2Pairing", `#/cases/${MAIN}/reconcile/pairing`]]);
    expect(within(parts).getByRole("tab", { name: "Lines" }).getAttribute("aria-selected")).toBe("true");
    const head = screen.getByRole("heading", { level: 1, name: "Invented March" }).closest("header")!;
    fireEvent.click(await within(head).findByRole("button", { name: "Pair the lines →" }));
    expect(window.location.hash).toBe(`#/cases/${MAIN}/reconcile/pairing`);
    expect(screen.getAllByRole("button", { name: /→$/ })).toHaveLength(1);  // one main action
  });

  it("leads from the overview to the step whose sub-case waits, by its own next step's name", async () => {
    vi.spyOn(api, "casePage").mockResolvedValue(main(sub({ case: { id: INVOICES, name: "x", status: "open", outcome: null,
      next: { code: "case_package_review", label: "Review the to-dos", stage: "review", tab: "documents" } } }), sub({ state: "waiting" })));
    render(<CasePage caseId={MAIN} tab="overview" />);
    const head = (await screen.findByRole("heading", { level: 1, name: "Invented March" })).closest("header")!;
    fireEvent.click(await within(head).findByRole("button", { name: "Review the to-dos →" }));
    expect(window.location.hash).toBe(`#/cases/${MAIN}/invoices/documents`);
    // what holds the case leads to the step on the track, not to the overview it is shown on
    const holds = await screen.findByRole("region", { name: "What holds the case" });
    expect(within(holds).getByRole("link", { name: "Incoming invoices" }).getAttribute("href")).toBe(`#/cases/${MAIN}/invoices`);
  });

  it("shows a case that is only its batch with the batch's stages as its track, and its log and settings apart", async () => {
    const docs: CaseView = {
      case: { id: INVOICES, pack: "documents", version: "1.4.0", title: "Documents", name: "Invented April", status: "open" },
      steps: {}, next: null,
      tabs: [{ id: "documents", label: "Documents", elements: [{ type: "package_work", step: "process",
        data: { package: { id: BATCH, name: "April invoices", items: 2, kind: "folder" }, runs: [], can_start: false,
          budget: { usd: { openai: "0.10" }, approved_by: "Synthetic Owner", decision: "start", over: {} } } }] }, LOG],
    };
    vi.spyOn(api, "casePage").mockResolvedValue(docs);
    vi.spyOn(api, "workpackage").mockImplementation(async (id: string) => (id === BATCH ? { ...batch(), owner_case: undefined }
      : { ...batch(), workpackage: { ...batch().workpackage, id, name: "Invented April" }, owner_case: undefined }));
    vi.spyOn(api, "users").mockResolvedValue({ users: [] });
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<CasePage caseId={INVOICES} batch={{ wpId: BATCH, route: { view: "workpackages", wpId: BATCH, stage: "process", inCase: INVOICES } }} />);
    const stages = await screen.findByRole("tablist", { name: "Document batch stages" });
    expect(screen.queryByRole("tablist", { name: "The case's steps" })).toBeNull();
    expect(within(stages).getByRole("tab", { name: /Processing/ }).getAttribute("aria-selected")).toBe("true");
    // the cost cap a person approved for the run, above the processing
    expect(screen.getByText(/Started by itself within the cap Synthetic Owner approved/)).toBeTruthy();
    // the batch's own next step is the title row's main action
    const head = screen.getByRole("heading", { level: 1, name: "Invented April" }).closest("header")!;
    expect(await within(head).findByRole("button", { name: /→$/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /^Log/ }).getAttribute("href")).toBe(`#/cases/${INVOICES}/history`);
    expect(screen.queryByRole("region", { name: "The case's settings" })).toBeNull();  // the case's settings are with its log
    cleanup();
    render(<CasePage caseId={INVOICES} tab="history" />);
    expect(await screen.findByRole("region", { name: "The case's settings" })).toBeTruthy();
    expect((await screen.findByRole("link", { name: /^Log/ })).getAttribute("aria-current")).toBe("page");
    expect(within(await screen.findByRole("tablist", { name: "Document batch stages" })).getAllByRole("tab")
      .map((a) => a.getAttribute("aria-selected"))).toEqual(["false", "false", "false"]);
  });
});
