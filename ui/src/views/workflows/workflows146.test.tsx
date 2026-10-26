// 146 (DECISIONS 146): the new work wizard makes a workflow (the party, the period, each step's source and budget, an
// overview), the control view shows the chain and starts a step that waits for a budget, and the list filters. The
// local service is replaced by spies; synthetic names only. Expectations use the English interface; a separate check
// makes sure every text of the templates has a Hungarian translation.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import workflowConfig from "./workflowTemplates181.fixture.json";  // 181: the service's templates
import {
  api, setActor, type OwnParty, type PartiesOverview, type WorkflowRow, type WorkflowTemplates, type WorkflowView,
} from "../../api";
import hungarian from "../../i18n/hu-native.json";
import { setLanguage } from "../../i18n";
import { lastClosedMonth, NewWork } from "./NewWork";
import { Workflows } from "./Workflows";

const PARTY: OwnParty = {
  id: "party-00000000000a", name: "Example Kft.", invoices: 3, first: null, last: null, statements_first: null,
  statements_last: null, accounts: [], identities: [], updated_at: "",
};
const OVERVIEW: PartiesOverview = {
  parties: [PARTY], suggestions: [], unassigned: [], dismissed: [], invoices: 0, unclaimed_invoices: 0, ambiguous_invoices: 0,
  buyer_is_supplier: 0, no_buyer: 0, config_hash: "x",
};
const TEMPLATES = workflowConfig as unknown as WorkflowTemplates;

function view(over: Partial<WorkflowView> = {}): WorkflowView {
  const base = { source: { kind: "folder" as const, folder: "C:\\work\\invoices" }, budget: {}, name: "June · step", after: [] as string[],
    run_id: null, pull_id: null, updated_at: "2026-10-11T20:00:00+00:00", note: null, package: null, done: false };
  return {
    workflow: { id: "wf-00000000000a", template: "monthly_reconciliation", template_title: "Monthly reconciliation", name: "June",
      party_id: PARTY.id, party: PARTY.name, period_start: "2026-06-01", period_end: "2026-06-30", auto: true, status: "open",
      actor: "Synthetic reviewer", created_at: "2026-10-11T20:00:00+00:00", updated_at: "2026-10-11T20:00:00+00:00" },
    steps: [
      { ...base, id: "invoices", kind: "documents", title: "Incoming invoices", kind_title: "Documents: extract their data",
        state: "needs_budget", status: "needs_budget", package: { id: "wp-00000000000a", name: "June · invoices", next: null },
        note: { estimate: { jev: "0.447741", openai: "0.0787" }, budget: {}, over: { jev: "0.447741", openai: "0.0787" } } },
      { ...base, id: "statements", kind: "statements", title: "Bank statements", kind_title: "Bank statements", state: "started",
        status: "approved", done: true, package: { id: "wp-00000000000b", name: "June · statements",
          next: { code: "done", label: "Kiadva", stage: "result" } } },
      { ...base, id: "reconcile", kind: "reconcile", title: "Reconciliation", kind_title: "Reconciliation of statements and invoices",
        source: { kind: "none" }, after: ["invoices", "statements"], state: "waiting", status: "waiting" },
    ],
    done: 1, total: 3, next: { step: "invoices", status: "needs_budget" },
    events: [{ step: null, action: "create", actor: "Synthetic reviewer", detail: {}, created_at: "2026-10-11T20:00:00+00:00" }],
    ...over,
  };
}

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the new work wizard", () => {
  it("makes a monthly reconciliation: the party, the period, each step's source and budget, then the overview", async () => {
    vi.spyOn(api, "workflowTemplates").mockResolvedValue(TEMPLATES);
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    const estimate = vi.spyOn(api, "workflowEstimate").mockResolvedValue({ items: 3, usd: { jev: "0.0612", openai: "0.0301" }, note: null });
    const create = vi.spyOn(api, "createWorkflow").mockResolvedValue(view());
    const onWorkflow = vi.fn();
    render(<NewWork onPackage={vi.fn()} onWorkflow={onWorkflow} />);
    fireEvent.click(await screen.findByRole("radio", { name: "A whole period's work" }));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    expect((screen.getByRole("radio", { name: "Monthly reconciliation" }) as HTMLInputElement).checked).toBe(true);
    const chain = screen.getAllByLabelText("Steps")[0];
    expect(within(chain).getAllByText(/Incoming invoices|Bank statements|Reconciliation/).map((e) => e.textContent))
      .toEqual(["Incoming invoices", "Bank statements", "Reconciliation"]);
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    const next = screen.getByRole("button", { name: "Next →" }) as HTMLButtonElement;
    expect(next.disabled).toBe(true);
    fireEvent.click(await screen.findByRole("radio", { name: /Example Kft\./ }));
    fireEvent.change(screen.getByLabelText("Folder of Incoming invoices"), { target: { value: "C:\\work\\invoices" } });
    fireEvent.change(screen.getByLabelText("Folder of Bank statements"), { target: { value: "C:\\work\\statements" } });
    expect(next.disabled).toBe(false);
    fireEvent.click(screen.getAllByRole("button", { name: "Estimate" })[0]);
    await waitFor(() => expect((screen.getByLabelText("JEV budget of Incoming invoices") as HTMLInputElement).value).toBe("0.07"));
    expect(estimate).toHaveBeenCalledWith(expect.objectContaining({ kind: "documents", source: { kind: "folder", folder: "C:\\work\\invoices", recursive: false } }));
    expect((screen.getByLabelText("OpenAI budget of Incoming invoices") as HTMLInputElement).value).toBe("0.04");
    expect(screen.getByText(/3 item\(s\), at most JEV 0.0612 USD \+ OpenAI 0.0301 USD/)).toBeTruthy();
    fireEvent.click(next);
    const overview = screen.getByLabelText("Overview");
    expect(overview.textContent).toContain("starts once these are approved: Incoming invoices, Bank statements");
    expect(overview.textContent).toContain("Budget for an automatic start: JEV 0.07 USD + OpenAI 0.04 USD");
    fireEvent.click(screen.getByRole("button", { name: "Create the workflow" }));
    await waitFor(() => expect(onWorkflow).toHaveBeenCalledWith("wf-00000000000a"));
    const [from, to] = lastClosedMonth();
    const body = create.mock.calls[0][0];
    expect(body).toMatchObject({ template: "monthly_reconciliation", party_id: PARTY.id, period_start: from, period_end: to, auto: true });
    expect(body.steps.invoices).toEqual({ source: { kind: "folder", folder: "C:\\work\\invoices", recursive: false }, budget: { jev: "0.07", openai: "0.04" } });
    expect(body.steps.reconcile).toEqual({ source: { kind: "none" }, budget: {} });
    expect(body.names?.reconcile).toBe(`Example Kft. · Monthly reconciliation · ${from} – ${to} · Reconciliation`);
  });

  it("a single template opens its process pack's general form (231 C3d: the mailbox download's asks for the download)", async () => {
    vi.spyOn(api, "workflowTemplates").mockResolvedValue(TEMPLATES);
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [{ id: "mailbox", title: "Emails from a mailbox", version: "1.0.0",
      scope: ["source"], asks: ["source"], package_kinds: [], source_kinds: ["mailbox"] }] });
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
    vi.spyOn(api, "parties").mockResolvedValue({ parties: [] } as never);
    vi.spyOn(api, "mailbox").mockResolvedValue({ accounts: [], schedules: [], pulls: [], bridge_available: true } as never);
    render(<NewWork onPackage={vi.fn()} onWorkflow={vi.fn()} />);
    expect((await screen.findByRole("radio", { name: "Documents and emails" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    fireEvent.click(screen.getByRole("radio", { name: "Emails from a mailbox" }));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    expect(await screen.findByRole("form", { name: "Emails from a mailbox" })).toBeTruthy();
    expect(screen.getByLabelText(/Mailbox address/)).toBeTruthy();
  });
});

describe("a workflow's control view", () => {
  it("a double click on Start sends one request (167, review 160 U-7)", async () => {
    vi.spyOn(api, "workflowView").mockResolvedValue(view());
    let answer: (v: WorkflowView) => void = () => {};
    const start = vi.spyOn(api, "startWorkflowStep").mockReturnValue(new Promise((r) => { answer = r; }));
    render(<Workflows route={{ view: "workflows", wfId: "wf-00000000000a" }} />);
    const button = await screen.findByRole("button", { name: "Start with this budget" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(start).toHaveBeenCalledTimes(1);
    expect((button as HTMLButtonElement).disabled).toBe(true);
    answer(view({ next: null }));
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
  });

  it("shows the chain, what comes next, and starts a step with the budget a person gives", async () => {
    vi.spyOn(api, "workflowView").mockResolvedValue(view());
    const start = vi.spyOn(api, "startWorkflowStep").mockResolvedValue(view({ next: null }));
    render(<Workflows route={{ view: "workflows", wfId: "wf-00000000000a" }} />);
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Next: Incoming invoices");
    const steps = within(screen.getByRole("list", { name: "Steps" })).getAllByRole("listitem").filter((li) => li.className.includes("wf-step"));
    expect(steps.map((s) => s.querySelector("strong")?.textContent)).toEqual(["Incoming invoices", "Bank statements", "Reconciliation"]);
    expect(steps[1].textContent).toContain("approved");
    expect(steps[2].textContent).toContain("Waits for: Incoming invoices");
    expect(steps[0].textContent).toContain("Its run would reserve at most JEV 0.447741 USD + OpenAI 0.0787 USD");
    expect((screen.getByLabelText("JEV budget of Incoming invoices") as HTMLInputElement).value).toBe("0.45");
    fireEvent.change(screen.getByLabelText("JEV budget of Incoming invoices"), { target: { value: "0.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Start with this budget" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("wf-00000000000a", "invoices", { jev: "0.5", openai: "0.08" }));
    expect(screen.getByRole("link", { name: "June · statements" }).getAttribute("href")).toBe("#/workpackages/wp-00000000000b/result");
  });
});

describe("153 the wizard's estimate", () => {
  it("keeps a cap typed while it runs", async () => {
    vi.spyOn(api, "workflowTemplates").mockResolvedValue(TEMPLATES);
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    let answer!: (v: { items: number; usd: Record<string, string>; note: null }) => void;
    vi.spyOn(api, "workflowEstimate").mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    render(<NewWork onPackage={vi.fn()} onWorkflow={vi.fn()} />);
    fireEvent.click(await screen.findByRole("radio", { name: "A whole period's work" }));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    fireEvent.click(await screen.findByRole("radio", { name: /Example Kft\./ }));
    fireEvent.change(screen.getByLabelText("Folder of Incoming invoices"), { target: { value: "C:\work\invoices" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Estimate" })[0]);
    fireEvent.change(screen.getByLabelText("OpenAI budget of Incoming invoices"), { target: { value: "0.10" } }); // typed meanwhile
    answer({ items: 3, usd: { jev: "0.0612", openai: "0.73" }, note: null });
    await waitFor(() => expect((screen.getByLabelText("JEV budget of Incoming invoices") as HTMLInputElement).value).toBe("0.07"));
    expect((screen.getByLabelText("OpenAI budget of Incoming invoices") as HTMLInputElement).value).toBe("0.10"); // before: 0.73
  });
});

describe("153 the control view after an action", () => {
  it("follows the states loaded after it, though the workflow's update time stays the same", async () => {
    const waiting = view();
    const running = view({ steps: view().steps.map((s) => (s.id === "invoices" ? { ...s, state: "started", status: "running", note: null } : s)) });
    const approved = view({ steps: view().steps.map((s) => (s.id === "invoices" ? { ...s, state: "started", status: "approved", done: true, note: null } : s)),
      done: 2 });
    const load = vi.spyOn(api, "workflowView").mockResolvedValueOnce(waiting).mockResolvedValue(approved);
    vi.spyOn(api, "startWorkflowStep").mockResolvedValue(running); // the action's answer, same `updated_at`
    render(<Workflows route={{ view: "workflows", wfId: "wf-00000000000a" }} />);
    await screen.findByRole("button", { name: "Start with this budget" });
    fireEvent.click(screen.getByRole("button", { name: "Start with this budget" }));
    await waitFor(() => expect(load.mock.calls.length).toBeGreaterThanOrEqual(2));
    const steps = () => within(screen.getByRole("list", { name: "Steps" })).getAllByRole("listitem").filter((li) => li.className.includes("wf-step"));
    await waitFor(() => expect(steps()[0].textContent).toContain("approved")); // before: frozen on the action's "running"
  });
});

describe("the workflows list", () => {
  it("filters by state and search", async () => {
    const row = (id: string, name: string, done: number, next: WorkflowRow["next"]): WorkflowRow => ({
      ...view().workflow, id, name, done, total: 3, next,
      steps: [{ id: "invoices", title: "Incoming invoices", status: done ? "approved" : "needs_budget" },
        { id: "statements", title: "Bank statements", status: "approved" }, { id: "reconcile", title: "Reconciliation", status: done === 3 ? "approved" : "waiting" }],
    });
    vi.spyOn(api, "workflows").mockResolvedValue({ workflows: [
      row("wf-00000000000a", "June", 1, { step: "invoices", status: "needs_budget" }), row("wf-00000000000b", "May", 3, null)] });
    render(<Workflows route={{ view: "workflows" }} />);
    expect(await screen.findByRole("link", { name: "June" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "May" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "attention" } });
    expect(screen.queryByRole("link", { name: "May" })).toBeNull();
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "may" } });
    expect(screen.queryByRole("link", { name: "June" })).toBeNull();
  });
});

describe("Hungarian", () => {
  it("has a translation for every text of the templates", () => {
    const texts = [TEMPLATES.intro, ...TEMPLATES.groups.flatMap((g) => [g.title, g.description]),
      ...Object.values(TEMPLATES.kinds).flatMap((k) => [k.title, k.description, k.cost]),
      ...TEMPLATES.templates.flatMap((x) => [x.title, x.description, ...x.steps.map((s) => s.title).filter(Boolean)])];
    for (const text of texts) expect((hungarian as Record<string, string>)[text as string], text as string).toBeTruthy();
  });
});
