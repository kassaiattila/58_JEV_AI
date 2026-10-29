// 231 (stage U, U2c; the owner's decision of 2026-10-28: a chain is a multi-step process): a step that runs a case of
// another process shows its sub-case, linked, with its state and its own next step; a step not started yet says what it
// waits for; a stopped one offers its retry; a sub-case's page leads back to the case it is part of. 261 (plan B, B1b;
// the owner's decision of 2026-10-29): a multi-step case's sub-cases are the rows of one sub-work table, each with its
// work (documents, open to-dos, its run). Synthetic data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type SubCaseData } from "../api";
import { setLanguage } from "../i18n";
import { CasePage } from "./CasePage";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const CHAIN = "wp-00000000c231";
const SUB = "wp-00000000d231";
const step = (title: string, state: string, extra: Partial<CaseView["steps"][string]> = {}) => ({
  title, uses: "run_case@1", start: "auto" as const, state, phase: null, waiting_for: state === "running" ? "case_closed" : null,
  awaiting_start: false, note: null, result: null, actions: [], ...extra,
});
const data = (over: Partial<SubCaseData>): SubCaseData => ({
  state: "running", pack: "documents", process: "Documents", case: null, earlier: [], ...over,
});

function chain(invoices: SubCaseData, reconcile: SubCaseData, over: Partial<CaseView["steps"][string]> = {}): CaseView {
  return {
    case: { id: CHAIN, pack: "monthly_reconciliation", version: "1.0.0", title: "Monthly reconciliation", name: "Invented March", status: "open" },
    steps: { invoices: step("Incoming invoices", invoices.state ?? "running", over), reconcile: step("Reconciliation", reconcile.state ?? "waiting") },
    tabs: [{ id: "overview", label: "Overview", elements: [
      { type: "sub_case", step: "invoices", data: invoices }, { type: "sub_case", step: "reconcile", data: reconcile }] }],
    next: { code: "case_sub_case", label: "Continue in its sub-case", stage: "process", tab: "overview" },
  };
}

describe("a step that runs a sub-case (231 U2c)", () => {
  it("links the sub-case with its state and its own next step, and says what a later step waits for", async () => {
    const invoices = data({ case: { id: SUB, name: "Invented March", status: "open", outcome: null,
      next: { code: "case_package_start", label: "Start the live run", stage: "process", tab: "documents" } } });
    const reconcile = data({ state: "waiting", pack: "reconciliation", process: "Reconciliation" });
    vi.spyOn(api, "casePage").mockResolvedValue(chain(invoices, reconcile));
    render(<CasePage caseId={CHAIN} tab="overview" />);
    const table = await screen.findByRole("table", { name: "Sub-work" });
    expect(screen.getAllByRole("table", { name: "Sub-work" })).toHaveLength(1);  // one table, a row each
    const card = within(table).getByRole("row", { name: "Incoming invoices" });
    expect(within(card).getByText("Its case is in progress")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "Invented March" }).getAttribute("href")).toBe(`#/cases/${SUB}`);
    expect(within(card).getByRole("link", { name: "Start the live run" }).getAttribute("href")).toBe(`#/cases/${SUB}/documents`);
    const later = within(table).getByRole("row", { name: "Reconciliation" });
    expect(within(later).getByText("Not started yet")).toBeTruthy();
    expect(within(later).getByText("Starts once the steps before it are done.")).toBeTruthy();
  });

  it("offers a stopped step's retry, with the earlier sub-case linked", async () => {
    const invoices = data({ state: "failed", earlier: [{ case_id: SUB, outcome: "cancelled" }] });
    vi.spyOn(api, "casePage").mockResolvedValue(chain(invoices, data({ state: "waiting" }),
      { state: "failed", note: "the sub-case closed as cancelled", actions: [{ name: "retry", label: "Try again" }] }));
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue(chain(data({}), data({ state: "waiting" })));
    render(<CasePage caseId={CHAIN} tab="overview" />);
    const card = await screen.findByRole("row", { name: "Incoming invoices" });
    expect(within(card).getByText("Did not finish")).toBeTruthy();
    expect(within(card).getByText("the sub-case closed as cancelled")).toBeTruthy();  // why it stopped
    expect(within(card).getByRole("link", { name: "cancelled" }).getAttribute("href")).toBe(`#/cases/${SUB}`);
    fireEvent.click(within(card).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith(CHAIN, "invoices", "retry"));
  });

  it("shows a sub-case closed a moment ago as done, and names the case's next step in Hungarian", async () => {
    const invoices = data({ case: { id: SUB, name: "Invented March", status: "closed", outcome: "done", next: null } });
    vi.spyOn(api, "casePage").mockResolvedValue(chain(invoices, data({ state: "waiting" })));
    await setLanguage("hu");
    render(<CasePage caseId={CHAIN} tab="overview" />);
    const card = await screen.findByRole("row", { name: "Beérkező számlák" });
    expect(within(card).getByText("A részügy kész")).toBeTruthy();
    expect(screen.getByText("Következő lépés: Tovább a részügyben")).toBeTruthy();
  });

  it("says each sub-case's work: its documents, open to-dos and its live run", async () => {
    const invoices = data({ case: { id: SUB, name: "Invented March", status: "open", outcome: null, next: null,
      work: [{ step: "process", title: "Process the documents", tab: "documents", batch: "wp-00000000e231", documents: 4, todos: 3,
               run: { mode: "apply", status: "needs_review", approved: false } }] } });
    vi.spyOn(api, "casePage").mockResolvedValue(chain(invoices, data({ state: "waiting" })));
    render(<CasePage caseId={CHAIN} tab="overview" />);
    const card = await screen.findByRole("row", { name: "Incoming invoices" });
    expect(within(card).getAllByRole("cell")[1].textContent).toBe("4 documents · To-dos: 3 · Live: to-dos pending");
    // 261 (B1c): the open to-dos lead to their review, under the sub-case's address
    expect(within(card).getByRole("link", { name: "To-dos: 3" }).getAttribute("href")).toBe(`#/cases/${SUB}/batches/wp-00000000e231/review`);
    const [, work] = within(screen.getByRole("row", { name: "Reconciliation" })).getAllByRole("cell");
    expect(work.textContent).toBe("–");  // a step not started yet has no work to say
  });

  it("says a step a closed case never reached did not run", async () => {
    const view = chain(data({ state: "done", case: { id: SUB, name: "Invented March", status: "closed", outcome: "done", next: null } }),
      data({ state: "waiting" }), { state: "done", waiting_for: null });
    vi.spyOn(api, "casePage").mockResolvedValue({ ...view, case: { ...view.case, status: "closed" }, next: null });
    render(<CasePage caseId={CHAIN} tab="overview" />);
    const later = await screen.findByRole("row", { name: "Reconciliation" });
    expect(within(later).getByText("Did not run")).toBeTruthy();
    expect(within(later).getByText("The case closed before this step ran.")).toBeTruthy();
  });

  it("leads a sub-case's page back to the case it is part of", async () => {
    const view: CaseView = {
      case: { id: SUB, pack: "documents", version: "1.4.0", title: "Documents", name: "Invented March", status: "open",
        parent: { id: CHAIN, name: "Invented March", title: "Monthly reconciliation", step: "invoices", step_title: "Incoming invoices" } },
      steps: {}, tabs: [{ id: "history", label: "History", elements: [] }], next: null,
    };
    vi.spyOn(api, "casePage").mockResolvedValue(view);
    render(<CasePage caseId={SUB} />);
    const crumbs = await screen.findByRole("navigation", { name: "Location" });
    expect(within(crumbs).getByRole("link", { name: "Invented March · Incoming invoices" }).getAttribute("href")).toBe(`#/cases/${CHAIN}`);
  });
});
