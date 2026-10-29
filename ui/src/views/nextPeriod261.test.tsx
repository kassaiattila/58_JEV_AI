// 261 (backlog F-reszugy-kovetkezo-idoszak; the owner's decisions of 2026-10-29): a case of a process repeated by period
// offers its next period, open or closed: the button opens the new case's form filled in from it (the next period, the
// own party, each step's documents again taking only the new ones, a person may untick it), and the new case follows
// it; once started, the case links its next period's case, and that one the case it follows. Synthetic data, a mocked
// service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type ProcessRow } from "../api";
import { setLanguage } from "../i18n";
import { CasePage } from "./CasePage";
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
    { step: "invoices", title: "Incoming invoices", pack: "documents", process: "Documents", source_kinds: ["folder", "files"], examples: false,
      only_new: true },
    // the statements' survey takes only the statements not in the store anyway: no such box
    { step: "statements", title: "Bank statements", pack: "bank_statements", process: "Bank statements", source_kinds: ["folder", "files"], examples: false },
  ],
};
const NAME = "Monthly reconciliation · Example Party Kft. · 2026-04-01 – 2026-04-30";

const page = (over: Partial<CaseView> = {}, follows?: string): CaseView => ({
  case: { id: CASE, pack: "monthly_reconciliation", version: "1.1.0", title: "Monthly reconciliation", name: NAME,
          status: "open", ...(follows ? { follows } : {}) },
  steps: {}, tabs: [{ id: "overview", label: "Overview", elements: [] }], next: null, ...over,
});

describe("a case's next period (261)", () => {
  it("is offered by a case of a process repeated by period, which says the case it follows", async () => {
    vi.spyOn(api, "casePage").mockResolvedValue(page({ next_period: { case_id: null } }, PREV));
    render(<CasePage caseId={CASE} />);
    expect((await screen.findByRole("link", { name: `Follows: ${PREV}` })).getAttribute("href")).toBe(`#/cases/${PREV}`);
    fireEvent.click(screen.getByRole("button", { name: "Next period →" }));
    expect(window.location.hash).toBe(`#/cases/new/monthly_reconciliation?after=${CASE}`);
  });

  it("links the next period's case once one was started, and offers none for another process", async () => {
    vi.spyOn(api, "casePage").mockResolvedValue(page({ next_period: { case_id: "wp-000000000c03" } }));
    render(<CasePage caseId={CASE} />);
    expect(await screen.findByRole("link", { name: "Next period: wp-000000000c03" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Next period →" })).toBeNull();
    cleanup();
    vi.spyOn(api, "casePage").mockResolvedValue(page({ next_period: null }));
    render(<CasePage caseId={CASE} />);
    expect(await screen.findByRole("heading", { name: NAME })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Next period →" })).toBeNull();
  });

  it("opens the new case's form filled in from the case, and the new case follows it", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [MONTHLY] });
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
    vi.spyOn(api, "ownParties").mockResolvedValue({ parties: [{ id: PARTY, name: "Example Party Kft." }] });
    const next = vi.spyOn(api, "caseNext").mockResolvedValue({
      pack: "monthly_reconciliation", follows: PREV, party_id: PARTY, period_start: "2026-04-01", period_end: "2026-04-30", name: NAME,
      step_sources: { invoices: { kind: "folder", folder: "D:\\Invented\\invoices", recursive: false, only_new: true },
                      statements: { kind: "folder", folder: "D:\\Invented\\statements", recursive: false } } });
    const start = vi.spyOn(api, "startCase").mockResolvedValue({ case_id: CASE });
    render(<NewCase pack="monthly_reconciliation" after={PREV} />);
    const form = await screen.findByRole("form", { name: "Monthly reconciliation" });
    expect(next).toHaveBeenCalledWith(PREV);
    expect(within(form).getByText("Filled in from the previous period's case.")).toBeTruthy();
    expect((within(form).getByLabelText("Period from") as HTMLInputElement).value).toBe("2026-04-01");
    expect((within(form).getByLabelText("to") as HTMLInputElement).value).toBe("2026-04-30");
    await waitFor(() => expect((within(form).getByLabelText("Own party") as HTMLSelectElement).value).toBe(PARTY));
    const invoices = within(form).getByRole("group", { name: "Incoming invoices · Documents" });
    const statements = within(form).getByRole("group", { name: "Bank statements · Bank statements" });
    expect((within(invoices).getByLabelText("The folder's full path") as HTMLInputElement).value).toBe("D:\\Invented\\invoices");
    const onlyNew = within(invoices).getByRole("checkbox", { name: "Only the documents no live run has processed yet" }) as HTMLInputElement;
    expect(onlyNew.checked).toBe(true);
    expect(within(statements).queryByRole("checkbox", { name: "Only the documents no live run has processed yet" })).toBeNull();
    fireEvent.click(onlyNew);  // a person may take every document of the folder again
    fireEvent.click(within(form).getByRole("button", { name: "Create" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith({
      pack: "monthly_reconciliation", name: NAME, party_id: PARTY, period_start: "2026-04-01", period_end: "2026-04-30",
      step_sources: { invoices: { kind: "folder", folder: "D:\\Invented\\invoices", recursive: false },
                      statements: { kind: "folder", folder: "D:\\Invented\\statements", recursive: false } },
      follows: PREV }));
    await waitFor(() => expect(window.location.hash).toBe(`#/cases/${CASE}`));
  });

  it("offers no such box on a first case's form", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [MONTHLY] });
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
    vi.spyOn(api, "ownParties").mockResolvedValue({ parties: [] });
    render(<NewCase pack="monthly_reconciliation" />);
    const form = await screen.findByRole("form", { name: "Monthly reconciliation" });
    expect(within(form).queryByRole("checkbox", { name: "Only the documents no live run has processed yet" })).toBeNull();
    expect(within(form).queryByText("Filled in from the previous period's case.")).toBeNull();
  });
});
