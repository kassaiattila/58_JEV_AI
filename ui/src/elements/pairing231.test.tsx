// 231 (plan stage C, C2d; DECISIONS 231): the reconciliation as a process pack's case - the wizard's general form asks
// for an own party and a period (the accounts take the party's by default), and the pairing element shows one part of
// the reconciliation on each tab, with each tab's line from its data. Synthetic data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type ReconcileWorkspace } from "../api";
import { setLanguage } from "../i18n";
import { Pairing } from "./Pairing";
import { PairingProposal, type ProposalData } from "./PairingProposal";
import { pairingLine, pairingSummary } from "./pairingStatus";
import { ProcessCreate } from "./ProcessStart";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ""; });

const CASE = "wp-000000000231";
const ACCOUNT = "11112223333444455556666";
const WS = {
  workpackage_id: CASE, lines: [], invoices: [], coverage: [], blockers: [], warnings: [], line_marks: ["private"], open: {},
  counts: { lines: {}, invoices: {}, open_lines: 0, statements: 1, own_invoices: 2 }, learned_names: [], fx_tolerance: null,
  engine_version: "1.17.0", config_hash: "x", approval: { active: null, versions: [] },
  scope: { workpackage_id: CASE, accounts: [ACCOUNT], period_start: "2026-04-01", period_end: "2026-04-30", revision: 1, updated_at: "",
    party_id: null, party: null },
} as unknown as ReconcileWorkspace;
const DATA = { scope: WS.scope, counts: { open_lines: 3, own_invoices: 2 }, approval: { active: null, versions: [] } };
const PAGE = {
  case: { id: CASE, pack: "reconciliation", version: "1.0.0", title: "Reconciliation", name: "April", status: "open" },
  steps: {}, next: null,
  tabs: ["invoices", "lines", "decide", "result"].map((show) => ({ id: show === "decide" ? "pairing" : `tab-${show}`, label: show,
    elements: [{ type: "pairing", step: "pair", show, data: DATA }] })),
} as unknown as CaseView;
const EMPTY = { dataset: { name: "reconcile_inputs", label: "Inputs", scope: [], optional_scope: [] }, columns: [], rows: [],
  total: 0, matched: 0, offset: 0, limit: 100, facets: {} } as never;
const element = (show: string) => ({ type: "pairing", step: "pair", show, data: DATA });
const props = (show: string) => ({ caseId: CASE, element: element(show), page: PAGE, onChanged: () => {} });

describe("the reconciliation's case (231 C2d)", () => {
  it("is started for an own party and a period from the wizard's general form", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [{ id: "reconciliation", title: "Reconciliation", version: "1.0.0",
      scope: ["party", "period", "accounts"], asks: ["party", "period"], package_kinds: [] }] });
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
    vi.spyOn(api, "parties").mockResolvedValue({ parties: [{ id: "party-0000000000a1", name: "Example Home" }] } as never);
    const start = vi.spyOn(api, "startCase").mockResolvedValue({ case_id: CASE });
    const done = vi.fn();
    render(<ProcessCreate pack="reconciliation" onDone={done} />);
    const create = await screen.findByRole("button", { name: "Create" });
    expect(screen.queryByText("The packages the case reads")).toBeNull();
    expect((create as HTMLButtonElement).disabled).toBe(true);
    await screen.findByRole("option", { name: "Example Home" });
    fireEvent.change(screen.getByLabelText("Own party"), { target: { value: "party-0000000000a1" } });
    fireEvent.change(screen.getByLabelText("Period from"), { target: { value: "2026-04-01" } });
    fireEvent.change(screen.getByLabelText("to"), { target: { value: "2026-04-30" } });
    fireEvent.click(create);
    await waitFor(() => expect(start).toHaveBeenCalledWith({ pack: "reconciliation", name: "Reconciliation · Example Home · 2026-04-01 – 2026-04-30",
      party_id: "party-0000000000a1", period_start: "2026-04-01", period_end: "2026-04-30" }));
    await waitFor(() => expect(done).toHaveBeenCalledWith(CASE));
  });

  it("shows the scope and the coverage with the statements, and opens the pairing on the case's tab", async () => {
    vi.spyOn(api, "reconcileWorkspace").mockResolvedValue(WS);
    vi.spyOn(api, "reconcileAccounts").mockResolvedValue({ accounts: [] } as never);
    vi.spyOn(api, "parties").mockResolvedValue({ parties: [] } as never);
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<Pairing {...props("lines")} />);
    expect(await screen.findByRole("region", { name: "Scope" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Coverage" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "What blocks the approval" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Go to pairing/ }));
    expect(window.location.hash).toContain("pairing");
  });

  it("shows the invoices with what blocks the approval, without the scope", async () => {
    vi.spyOn(api, "reconcileWorkspace").mockResolvedValue(WS);
    vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
    render(<Pairing {...props("invoices")} />);
    expect(await screen.findByRole("region", { name: "What blocks the approval" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Scope" })).toBeNull();
  });

  it("gives each tab its line and the case its summary", () => {
    expect(["invoices", "lines", "decide", "result"].map((show) => pairingLine(props(show)))).toEqual([
      "2 invoices", "1 bank accounts", "3 open lines", "not approved yet"]);
    expect(pairingSummary(props("decide"))).toBe("Reconciliation of 1 accounts or cards, 2026-04-01 – 2026-04-30");
  });
});

// --- 231 (C2c): the AI pairing proposal a person starts ---------------------------------------------------------------------

const proposalPage = (step: Record<string, unknown>) => ({ ...PAGE, steps: { propose: { title: "AI proposal", uses: "pairing_proposal@1",
  start: "person", state: "running", phase: null, waiting_for: "task_closed", awaiting_start: false, note: null, result: null,
  actions: [], ...step } } }) as unknown as CaseView;
const proposal = (data: Partial<ProposalData>, step: Record<string, unknown>) => ({ caseId: CASE, onChanged: vi.fn(),
  element: { type: "pairing_proposal", step: "propose", data: { run: null, engines: ["jev"], cap_usd: { jev: "0.20" }, ...data } },
  page: proposalPage(step) });

describe("the AI pairing proposal (231 C2c)", () => {
  it("is started by a person, the button showing the run's cost cap", async () => {
    const start = vi.spyOn(api, "startCaseStep").mockResolvedValue(PAGE);
    const p = proposal({}, { awaiting_start: true });
    render(<PairingProposal {...p} />);
    const button = screen.getByRole("button", { name: /Ask the AI for proposals/ });
    expect(button.textContent).toContain("≤ 0.20 USD");
    expect(button.getAttribute("title")).toContain("0.20 USD");
    fireEvent.click(button);
    await waitFor(() => expect(start).toHaveBeenCalledWith(CASE, "propose"));
    await waitFor(() => expect(p.onChanged).toHaveBeenCalled());
  });

  it("says when it is answering and what it answered", () => {
    const running = proposal({ run: { round: 1, state: "running", lines: null, error: null, counts: null, usage: null } }, {});
    render(<PairingProposal {...running} />);
    expect(screen.getByRole("status").textContent).toBe("The AI is answering…");
    expect(screen.queryByRole("button")).toBeNull();
    cleanup();
    const done = proposal({ run: { round: 1, state: "done", lines: 3, error: null, usage: null,
      counts: { jev: { asked: 2, inherited: 1, pays: 1, failed: 0 } } } }, { state: "done" });
    render(<PairingProposal {...done} />);
    expect(screen.getByRole("status").textContent).toBe("The AI answered 3 line(s); its proposals are on the pairing cards.");
  });

  it("shows a failed run and asks again with a new cap", async () => {
    const again = vi.spyOn(api, "caseStepAction").mockResolvedValue(PAGE);
    const failed = proposal({ run: { round: 1, state: "failed", lines: 3, error: "every line's question failed", counts: null, usage: null } },
      { state: "failed", actions: [{ name: "retry", label: "Try again" }] });
    render(<PairingProposal {...failed} />);
    expect(screen.getByRole("alert").textContent).toContain("every line's question failed");
    fireEvent.click(screen.getByRole("button", { name: /Ask the AI again/ }));
    await waitFor(() => expect(again).toHaveBeenCalledWith(CASE, "propose", "retry"));
  });
});
