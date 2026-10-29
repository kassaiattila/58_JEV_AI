// 261 (backlog F-reszugy-koltsegkeret; the owner's decisions of 2026-10-29): a multi-step case's form shows each step's
// estimate once its documents are given and, where the cost can be told ahead, a cap per provider within which its
// sub-case's live run starts by itself: unticked until a person approves it, the start button carrying the caps' sum; a
// next period's caps come filled in and ticked. The documents step's element says what the gate decided. Synthetic data,
// a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type PackageWorkView, type ProcessRow } from "../api";
import { elementOf } from "../elements/registry";
import { setLanguage } from "../i18n";
import { NewCase } from "./NewCase";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ""; });

const PREV = "wp-000000000c01";
const CASE = "wp-000000000c02";
const PARTY = "party-000000000001";
const MONTHLY: ProcessRow = {
  id: "monthly_reconciliation", title: "Monthly reconciliation", version: "1.1.0", scope: ["party", "period", "step_sources"],
  asks: ["party", "period", "step_sources"], package_kinds: [], manual: true, examples: false, missing_at_start: [],
  summary: "An own party's period in one case.",
  step_sources: [
    { step: "invoices", title: "Incoming invoices", pack: "documents", process: "Documents", source_kinds: ["folder", "files"], examples: false },
    { step: "statements", title: "Bank statements", pack: "bank_statements", process: "Bank statements", source_kinds: ["folder", "files"], examples: false },
  ],
};
const ESTIMATES = { steps: {
  invoices: { items: 2, usd: { openai: "0.40", jev: "0.10" }, note: null },
  statements: { items: null, usd: {}, note: null },
} };

function mockForm() {
  vi.spyOn(api, "processes").mockResolvedValue({ processes: [MONTHLY] });
  vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
  vi.spyOn(api, "ownParties").mockResolvedValue({ parties: [{ id: PARTY, name: "Example Party Kft." }] });
  return { estimate: vi.spyOn(api, "processEstimate").mockResolvedValue(ESTIMATES),
           start: vi.spyOn(api, "startCase").mockResolvedValue({ case_id: CASE }) };
}

describe("a multi-step case's run budgets (261)", () => {
  it("shows each step's estimate and starts the case with the caps a person approved", async () => {
    const { estimate, start } = mockForm();
    render(<NewCase pack="monthly_reconciliation" />);
    const form = await screen.findByRole("form", { name: "Monthly reconciliation" });
    fireEvent.change(within(form).getByLabelText("Own party"), { target: { value: PARTY } });
    fireEvent.change(within(form).getByLabelText("Period from"), { target: { value: "2026-04-01" } });
    fireEvent.change(within(form).getByLabelText("to"), { target: { value: "2026-04-30" } });
    const invoices = within(form).getByRole("group", { name: "Incoming invoices · Documents" });
    const statements = within(form).getByRole("group", { name: "Bank statements · Bank statements" });
    fireEvent.change(within(invoices).getByLabelText("The folder's full path"), { target: { value: "D:\\Invented\\invoices" } });
    fireEvent.change(within(statements).getByLabelText("The folder's full path"), { target: { value: "D:\\Invented\\statements" } });
    expect(await within(invoices).findByText("Estimate: 2 documents, up to 0.50 USD")).toBeTruthy();
    expect(estimate).toHaveBeenLastCalledWith("monthly_reconciliation", expect.objectContaining({ party_id: PARTY,
      period_start: "2026-04-01", period_end: "2026-04-30" }));
    expect(within(statements).getByText("The cost cannot be told ahead: a person starts its run.")).toBeTruthy();
    const create = within(form).getByRole("button", { name: /^Create/ });
    expect(create.textContent).toBe("Create");  // nothing approved yet: no cap on the button
    const openai = within(invoices).getByLabelText("OpenAI cap, USD") as HTMLInputElement;
    expect(openai.value).toBe("0.40");
    expect(openai.disabled).toBe(true);
    fireEvent.click(within(invoices).getByRole("checkbox", { name: "Start its live run by itself, up to:" }));
    fireEvent.change(openai, { target: { value: "0.30" } });
    expect(create.textContent).toBe("Create≤ 0.40 USD");
    fireEvent.click(create);
    await waitFor(() => expect(start).toHaveBeenCalledWith(expect.objectContaining({
      step_budgets: { invoices: { openai: "0.30", jev: "0.10" } } })));
  });

  it("fills in and ticks a next period's caps for a person to approve again", async () => {
    const { start } = mockForm();
    vi.spyOn(api, "caseNext").mockResolvedValue({
      pack: "monthly_reconciliation", follows: PREV, party_id: PARTY, period_start: "2026-04-01", period_end: "2026-04-30", name: "April",
      step_sources: { invoices: { kind: "folder", folder: "D:\\Invented\\invoices", recursive: false, only_new: true },
                      statements: { kind: "folder", folder: "D:\\Invented\\statements", recursive: false, only_new: true } },
      step_budgets: { invoices: { openai: "0.25", jev: "0.10" } } });
    render(<NewCase pack="monthly_reconciliation" after={PREV} />);
    const form = await screen.findByRole("form", { name: "Monthly reconciliation" });
    const invoices = within(form).getByRole("group", { name: "Incoming invoices · Documents" });
    const box = await within(invoices).findByRole("checkbox", { name: "Start its live run by itself, up to:" }) as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect((within(invoices).getByLabelText("OpenAI cap, USD") as HTMLInputElement).value).toBe("0.25");
    fireEvent.click(within(form).getByRole("button", { name: /^Create/ }));
    await waitFor(() => expect(start).toHaveBeenCalledWith(expect.objectContaining({
      follows: PREV, step_budgets: { invoices: { openai: "0.25", jev: "0.10" } } })));
  });
});

describe("the documents step's element (261)", () => {
  const view = (budget: PackageWorkView["budget"]): PackageWorkView => ({
    package: { id: "wp-000000000d01", name: "Invented invoices", items: 2, kind: "folder" }, runs: [], can_start: true,
    estimate: { openai: "0.40", jev: "0.10" }, blockers: [], budget });
  const show = (data: PackageWorkView) => {
    const page = { case: { id: CASE, pack: "documents", version: "1.4.0", title: "Documents", name: "Invented", status: "open" },
      steps: { process: { title: "Processing", uses: "process_documents@1", start: "auto", state: "running", phase: null,
        waiting_for: "run_start", awaiting_start: false, note: null, result: null, actions: [] } },
      tabs: [{ id: "documents", label: "Documents", elements: [{ type: "package_work", step: "process", data }] }], next: null } as unknown as CaseView;
    render(<>{elementOf("package_work")!.render({ caseId: CASE, element: page.tabs[0].elements[0], page, onChanged: () => {} })}</>);
  };

  it("says a run over its approved cap waits for a person's start", async () => {
    show(view({ usd: { openai: "0.10" }, approved_by: "anna", decision: "needs_budget", over: { openai: "0.40", jev: "0.10" } }));
    expect(await screen.findByText("Over the cap anna approved: the estimate is 0.50 USD, the cap 0.10 USD. Start the run yourself if it is right.")).toBeTruthy();
  });

  it("says a run started by itself within its cap", async () => {
    show({ ...view({ usd: { openai: "0.40", jev: "0.10" }, approved_by: "anna", decision: "start", over: {} }), can_start: false });
    expect(await screen.findByText("Started by itself within the cap anna approved (0.50 USD).")).toBeTruthy();
  });
});
