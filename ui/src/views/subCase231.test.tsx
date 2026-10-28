// 231 (stage U, U2c; the owner's decision of 2026-10-28: a chain is a multi-step process): a step that runs a case of
// another process shows its sub-case, linked, with its state and its own next step; a step not started yet says what it
// waits for; a stopped one offers its retry; a sub-case's page leads back to the case it is part of. Synthetic data, a
// mocked service.
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
    const card = await screen.findByRole("region", { name: "Incoming invoices" });
    expect(within(card).getByText("Its case is in progress")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "Invented March" }).getAttribute("href")).toBe(`#/cases/${SUB}`);
    expect(within(card).getByRole("link", { name: "Start the live run" }).getAttribute("href")).toBe(`#/cases/${SUB}/documents`);
    const later = screen.getByRole("region", { name: "Reconciliation" });
    expect(within(later).getByText("Not started yet")).toBeTruthy();
    expect(within(later).getByText(/A case of the process Reconciliation starts once the steps before it are done/)).toBeTruthy();
  });

  it("offers a stopped step's retry, with the earlier sub-case linked", async () => {
    const invoices = data({ state: "failed", earlier: [{ case_id: SUB, outcome: "cancelled" }] });
    vi.spyOn(api, "casePage").mockResolvedValue(chain(invoices, data({ state: "waiting" }),
      { state: "failed", note: "the sub-case closed as cancelled", actions: [{ name: "retry", label: "Try again" }] }));
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue(chain(data({}), data({ state: "waiting" })));
    render(<CasePage caseId={CHAIN} tab="overview" />);
    const card = await screen.findByRole("region", { name: "Incoming invoices" });
    expect(within(card).getByText("Did not finish")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "cancelled" }).getAttribute("href")).toBe(`#/cases/${SUB}`);
    fireEvent.click(within(card).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith(CHAIN, "invoices", "retry"));
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
