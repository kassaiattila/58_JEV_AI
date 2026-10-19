// 147 (DECISIONS 147): a workflow repeated for the next period. The control view offers the repeat and shows the link
// between the two; the wizard opens at the details filled in from the draft (the next period, the sources, the budgets,
// a documents step only with the new documents) and makes the new workflow linked to the earlier one. The overview names
// an existing package chosen as a step's source. The local service is replaced by spies; synthetic names only.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import workflowConfig from "./workflowTemplates181.fixture.json";  // 181: the service's templates
import {
  api, setActor, type OwnParty, type PartiesOverview, type WorkflowDraft, type WorkflowTemplates, type WorkflowView,
  type WorkpackageBrief,
} from "../../api";
import { setLanguage } from "../../i18n";
import { parseRoute, routeHash } from "../../route";
import { stepNote } from "./labels";
import { NewWork } from "./NewWork";
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
const DRAFT: WorkflowDraft = {
  template: "monthly_reconciliation", party_id: PARTY.id, period_start: "2026-10-01", period_end: "2026-10-31",
  name: "Example Kft. 2026-10-01 – 2026-10-31", auto: true, previous: "wf-00000000000a",
  steps: {
    invoices: { source: { kind: "folder", folder: "C:\\work\\invoices", recursive: false, only_new: true }, budget: { jev: "0.5" } },
    statements: { source: { kind: "folder", folder: "C:\\work\\statements", recursive: false }, budget: {} },
    reconcile: { source: { kind: "none" }, budget: {} },
  },
};

function view(over: Partial<WorkflowView> = {}): WorkflowView {
  return {
    workflow: { id: "wf-00000000000b", template: "monthly_reconciliation", template_title: "Monthly reconciliation",
      name: "Example Kft. 2026-10-01 – 2026-10-31", party_id: PARTY.id, party: PARTY.name, period_start: "2026-10-01",
      period_end: "2026-10-31", auto: true, status: "open", actor: "Synthetic reviewer", created_at: "2026-10-12T08:00:00+00:00",
      updated_at: "2026-10-12T08:00:00+00:00" },
    steps: [{ id: "invoices", kind: "documents", title: "Incoming invoices", kind_title: "Documents: extract their data",
      after: [], source: { kind: "folder", folder: "C:\\work\\invoices", recursive: false, only_new: true }, budget: {},
      name: "October · invoices", state: "nothing_new", status: "nothing_new", done: true,
      note: "no new documents: 4 already processed", package: null, run_id: null, pull_id: null, updated_at: "2026-10-12T08:00:00+00:00" }],
    done: 1, total: 1, next: null,
    events: [{ step: "invoices", action: "left_out", actor: "Synthetic reviewer", detail: { new: 2, left_out: 4 }, created_at: "2026-10-12T08:00:00+00:00" }],
    repeat_of: { id: "wf-00000000000a", name: "Example Kft. 2026-09-01 – 2026-09-30", period_start: "2026-09-01", period_end: "2026-09-30" },
    repeated_as: [],
    ...over,
  };
}

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("repeating a workflow", () => {
  it("the control view offers the repeat and links the earlier workflow", async () => {
    vi.spyOn(api, "workflowView").mockResolvedValue(view());
    render(<Workflows route={{ view: "workflows", wfId: "wf-00000000000b" }} />);
    const repeat = await screen.findByRole("link", { name: "Repeat for the next period" });
    expect(repeat.getAttribute("href")).toBe("#/workflows/wf-00000000000b/repeat");
    expect(screen.getByRole("link", { name: "Example Kft. 2026-09-01 – 2026-09-30" }).getAttribute("href")).toBe("#/workflows/wf-00000000000a");
    expect(screen.getByText(/no new documents: 4 already processed by a live run/)).toBeTruthy();
    expect(screen.getByText(/only the documents no live run has processed yet/)).toBeTruthy();
    expect(screen.getByText(/2 new document\(s\); 4 already processed by a live run, left out/)).toBeTruthy();
  });

  it("the repeat route opens the wizard filled in", () => {
    expect(parseRoute("#/workflows/wf-00000000000b/repeat")).toEqual({ view: "workflows", create: true, repeat: "wf-00000000000b" });
    expect(routeHash({ view: "workflows", create: true, repeat: "wf-00000000000b" })).toBe("#/workflows/wf-00000000000b/repeat");
  });

  it("the wizard opens at the details from the draft and makes the repeat linked to the earlier workflow", async () => {
    vi.spyOn(api, "workflowTemplates").mockResolvedValue(TEMPLATES);
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    vi.spyOn(api, "workflowRepeat").mockResolvedValue(DRAFT);
    const create = vi.spyOn(api, "createWorkflow").mockResolvedValue(view());
    const onWorkflow = vi.fn();
    render(<NewWork repeatOf="wf-00000000000a" onPackage={vi.fn()} onWorkflow={onWorkflow} />);
    expect(await screen.findByText(/This repeats an earlier workflow for the next period/)).toBeTruthy();
    expect((await screen.findByRole("radio", { name: /Example Kft\./ }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText("Period from") as HTMLInputElement).value).toBe("2026-10-01");
    expect((screen.getByLabelText("to") as HTMLInputElement).value).toBe("2026-10-31");
    expect((screen.getByLabelText("Folder of Incoming invoices") as HTMLInputElement).value).toBe("C:\\work\\invoices");
    expect((screen.getByLabelText("Only the documents no live run has processed yet") as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText("JEV budget of Incoming invoices") as HTMLInputElement).value).toBe("0.5");
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    const overview = screen.getByLabelText("Overview");
    expect(overview.textContent).toContain("C:\\work\\invoices · only the documents no live run has processed yet");
    fireEvent.click(screen.getByRole("button", { name: "Create the workflow" }));
    await waitFor(() => expect(onWorkflow).toHaveBeenCalledWith("wf-00000000000b"));
    const body = create.mock.calls[0][0];
    expect(body).toMatchObject({ template: "monthly_reconciliation", party_id: PARTY.id, period_start: "2026-10-01",
      period_end: "2026-10-31", name: "Example Kft. 2026-10-01 – 2026-10-31", previous: "wf-00000000000a" });
    expect(body.steps.invoices).toEqual({ source: { kind: "folder", folder: "C:\\work\\invoices", recursive: false, only_new: true }, budget: { jev: "0.5" } });
  });
});

describe("the overview of a new workflow", () => {
  it("names the existing package chosen as a step's source", async () => {
    vi.spyOn(api, "workflowTemplates").mockResolvedValue(TEMPLATES);
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    const pkg: WorkpackageBrief = { id: "wp-00000000000c", name: "September invoices", source_kind: "folder", source_ref: null,
      revision: 1, created_at: "", items: 3, recipe_id: null, last_run_id: null };
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [pkg] });
    const full = vi.spyOn(api, "workpackages");  // 154: the picker does not ask for the full list
    render(<NewWork initialTemplate="monthly_reconciliation" onPackage={vi.fn()} onWorkflow={vi.fn()} />);
    fireEvent.click(await screen.findByRole("radio", { name: /Example Kft\./ }));
    const sources = screen.getByRole("radiogroup", { name: "Source of Incoming invoices" });
    fireEvent.click(sources.querySelectorAll("input")[2]);  // folder, files, an existing work package
    fireEvent.change(await screen.findByRole("combobox", { name: "Work package" }), { target: { value: "wp-00000000000c" } });
    fireEvent.change(screen.getByLabelText("Folder of Bank statements"), { target: { value: "C:\\work\\statements" } });
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    expect(screen.getByLabelText("Overview").textContent).toContain("An existing work package: September invoices");
    expect(full).not.toHaveBeenCalled();
  });
});

describe("Hungarian", () => {
  it("translates the step notes with numbers", async () => {
    await setLanguage("hu");
    expect(stepNote("no new documents: 4 already processed")).toBe("nincs új irat: 4 iratot egy éles futás már feldolgozott");
    expect(stepNote("no new statement: 36 statement(s) and 0 PDF(s) are in the store or outside the period"))
      .toBe("nincs új kivonat: 36 kivonat és 0 PDF már a tárban van, vagy az időszakon kívül esik");
    expect(stepNote("no new emails")).toBe("nincs új levél");
  });
});
