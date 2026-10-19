// 160-D (plan F-csak-gpt Sz4; DECISIONS 160): the AI engine in the interface. Settings › Processing chooses the
// application's engine (JEV and GPT, or GPT only), and its save is solid only while the choice differs from the saved
// one; a workflow step may choose its own engine, which the estimate, the overview, the created workflow and the
// control view carry. The local service is replaced by spies; synthetic names only.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import workflowConfig from "./views/workflows/workflowTemplates181.fixture.json";  // 181: the service's templates
import { api, setActor, type OwnParty, type PartiesOverview, type WorkflowTemplates, type WorkflowView } from "./api";
import { setLanguage } from "./i18n";
import { EnginePanel } from "./views/settings/EnginePanel";
import { NewWork } from "./views/workflows/NewWork";
import { Workflows } from "./views/workflows/Workflows";

const PARTY: OwnParty = {
  id: "party-00000000000a", name: "Example Kft.", invoices: 3, first: null, last: null, statements_first: null,
  statements_last: null, accounts: [], identities: [], updated_at: "",
};
const OVERVIEW: PartiesOverview = {
  parties: [PARTY], suggestions: [], unassigned: [], dismissed: [], invoices: 0, unclaimed_invoices: 0, ambiguous_invoices: 0,
  buyer_is_supplier: 0, no_buyer: 0, config_hash: "x",
};

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the application's AI engine (Settings › Processing)", () => {
  it("shows the default and saves a changed choice, solid only while it differs", async () => {
    vi.spyOn(api, "engine").mockResolvedValueOnce({ engine: "jev", actor: null, updated_at: null })
      .mockResolvedValue({ engine: "gpt", actor: "Synthetic reviewer", updated_at: "2026-10-17T10:00:00+00:00" });
    const save = vi.spyOn(api, "saveEngine").mockResolvedValue({ engine: "gpt", actor: "Synthetic reviewer", updated_at: "2026-10-17T10:00:00+00:00" });
    render(<EnginePanel />);
    const jev = await screen.findByRole("radio", { name: /JEV and GPT \(recommended\)/ }) as HTMLInputElement;
    expect(jev.checked).toBe(true);
    expect(screen.getByText("The default; nobody has changed it")).toBeTruthy();
    const button = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.classList.contains("primary")).toBe(false);
    fireEvent.click(screen.getByRole("radio", { name: /GPT only, without JEV/ }));
    expect(button.disabled).toBe(false);
    expect(button.classList.contains("primary")).toBe(true);
    expect(screen.getByText(/Packages with saved settings keep their engine/)).toBeTruthy();
    fireEvent.click(button);
    await waitFor(() => expect(save).toHaveBeenCalledWith("gpt"));
    expect(await screen.findByText("Saved. New processing settings use: GPT only.")).toBeTruthy();
    expect(await screen.findByText(/Set by Synthetic reviewer/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("a workflow step's AI engine (the new work wizard)", () => {
  it("follows the application by default and carries a step's own choice to the estimate, the overview and the workflow", async () => {
    vi.spyOn(api, "workflowTemplates").mockResolvedValue(workflowConfig as unknown as WorkflowTemplates);
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    vi.spyOn(api, "engine").mockResolvedValue({ engine: "jev", actor: null, updated_at: null });
    const estimate = vi.spyOn(api, "workflowEstimate").mockResolvedValue({ items: 3, usd: { openai: "0.66" }, note: null });
    const create = vi.spyOn(api, "createWorkflow").mockRejectedValue(new Error("stop here"));
    render(<NewWork onPackage={vi.fn()} onWorkflow={vi.fn()} />);
    fireEvent.click(await screen.findByRole("radio", { name: "A whole period's work" }));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    fireEvent.click(await screen.findByRole("radio", { name: /Example Kft\./ }));
    fireEvent.change(screen.getByLabelText("Folder of Incoming invoices"), { target: { value: "C:\\work\\invoices" } });
    fireEvent.change(screen.getByLabelText("Folder of Bank statements"), { target: { value: "C:\\work\\statements" } });
    const invoices = screen.getByRole("radiogroup", { name: "AI engine of Incoming invoices" });
    const asApp = await within(invoices).findByRole("radio", { name: "As the application (JEV and GPT)" }) as HTMLInputElement;
    expect(asApp.checked).toBe(true);
    expect(screen.queryByRole("radiogroup", { name: "AI engine of Reconciliation" })).toBeNull();  // no engine of its own
    fireEvent.click(within(invoices).getByRole("radio", { name: "GPT only" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Estimate" })[0]);
    await waitFor(() => expect(estimate).toHaveBeenCalledWith(expect.objectContaining({ kind: "documents", engine: "gpt" })));
    await waitFor(() => expect((screen.getByLabelText("OpenAI budget of Incoming invoices") as HTMLInputElement).value).toBe("0.66"));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    const overview = screen.getByLabelText("Overview");
    expect(overview.textContent).toContain("AI engine: GPT only");
    expect(overview.textContent).toContain("AI engine: as the application (JEV and GPT)");
    fireEvent.click(screen.getByRole("button", { name: "Create the workflow" }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    const body = create.mock.calls[0][0];
    expect(body.steps.invoices.engine).toBe("gpt");
    expect("engine" in body.steps.statements).toBe(false);  // follows the application when it starts
    expect("engine" in body.steps.reconcile).toBe(false);
  });

  it("drops an estimate when the engine changes, as for a source change", async () => {
    vi.spyOn(api, "workflowTemplates").mockResolvedValue(workflowConfig as unknown as WorkflowTemplates);
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    vi.spyOn(api, "engine").mockResolvedValue({ engine: "gpt", actor: "Synthetic reviewer", updated_at: null });
    vi.spyOn(api, "workflowEstimate").mockResolvedValue({ items: 3, usd: { jev: "0.21", openai: "0.45" }, note: null });
    render(<NewWork onPackage={vi.fn()} onWorkflow={vi.fn()} />);
    fireEvent.click(await screen.findByRole("radio", { name: "A whole period's work" }));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    fireEvent.change(screen.getByLabelText("Folder of Incoming invoices"), { target: { value: "C:\\work\\invoices" } });
    const invoices = screen.getByRole("radiogroup", { name: "AI engine of Incoming invoices" });
    expect(await within(invoices).findByRole("radio", { name: "As the application (GPT only)" })).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Estimate" })[0]);
    expect(await screen.findByText(/3 item\(s\), at most/)).toBeTruthy();
    fireEvent.click(within(invoices).getByRole("radio", { name: "JEV and GPT" }));
    expect(screen.queryByText(/3 item\(s\), at most/)).toBeNull();
  });
});

describe("a workflow's control view", () => {
  it("names a step's own AI engine and nothing for a step that follows the application", async () => {
    const step = { kind: "documents" as const, after: [] as string[], budget: {}, name: "June · step", state: "started",
      status: "running" as const, done: false, note: null, package: null, run_id: null, pull_id: null,
      updated_at: "2026-10-17T10:00:00+00:00", source: { kind: "folder" as const, folder: "C:\work\invoices" } };
    const view: WorkflowView = {
      workflow: { id: "wf-00000000000a", template: "documents_pair", template_title: "Two folders", name: "June", party_id: PARTY.id,
        party: PARTY.name, period_start: "2026-06-01", period_end: "2026-06-30", auto: true, status: "open", actor: "Synthetic reviewer",
        created_at: "2026-10-17T10:00:00+00:00", updated_at: "2026-10-17T10:00:00+00:00" },
      steps: [{ ...step, id: "own", title: "Own engine", kind_title: "Documents", engine: "gpt" },
        { ...step, id: "app", title: "Application's engine", kind_title: "Documents", engine: null }],
      done: 0, total: 2, next: null, events: [],
    };
    vi.spyOn(api, "workflowView").mockResolvedValue(view);
    render(<Workflows route={{ view: "workflows", wfId: "wf-00000000000a" }} />);
    const steps = within(await screen.findByRole("list", { name: "Steps" })).getAllByRole("listitem").filter((li) => li.className.includes("wf-step"));
    expect(steps[0].textContent).toContain("AI engine: GPT only");
    expect(steps[1].textContent).not.toContain("AI engine");
  });
});
