// 160-D (plan F-csak-gpt Sz4; DECISIONS 160): the AI engine in the interface. Settings › Processing chooses the
// application's engine (JEV and GPT, or GPT only), and its save is solid only while the choice differs from the saved
// one; a workflow step may choose its own engine, which the control view carries (until 231 U2c the wizard's estimate,
// overview and created workflow did too). The local service is replaced by spies; synthetic names only.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type OwnParty, type WorkflowView } from "./api";
import { setLanguage } from "./i18n";
import { EnginePanel } from "./views/settings/EnginePanel";
import { Workflows } from "./views/workflows/Workflows";

const PARTY: OwnParty = {
  id: "party-00000000000a", name: "Example Kft.", invoices: 3, first: null, last: null, statements_first: null,
  statements_last: null, accounts: [], identities: [], updated_at: "",
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
    expect(screen.getByText(/Batches with saved settings keep their engine/)).toBeTruthy();
    fireEvent.click(button);
    await waitFor(() => expect(save).toHaveBeenCalledWith("gpt"));
    expect(await screen.findByText("Saved. New processing settings use: GPT only.")).toBeTruthy();
    expect(await screen.findByText(/Set by Synthetic reviewer/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
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
