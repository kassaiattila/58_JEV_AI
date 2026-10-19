// 181 (plan 170 L5): the wizard and the control view take what a step kind accepts from the service's registry (the
// templates carry each kind's package kinds), not from a list of their own. Synthetic names only; the local service is
// replaced by spies.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import workflowConfig from "./workflowTemplates181.fixture.json";
import { api, setActor, type WorkflowTemplates, type WorkflowView, type WorkpackageBrief } from "../../api";
import { setLanguage } from "../../i18n";
import { Workflows } from "./Workflows";

const TEMPLATES = workflowConfig as unknown as WorkflowTemplates;

function brief(id: string, name: string, kind: string): WorkpackageBrief {
  return { id, name, source_kind: kind, status: "open", items: 1, owner: "Synthetic reviewer", created_at: "", updated_at: "" } as unknown as WorkpackageBrief;
}

const PACKAGES = [brief("wp-00000000000a", "June folder", "folder"), brief("wp-00000000000b", "June watch", "watch"),
  brief("wp-00000000000c", "June reconciliation", "reconcile"), brief("wp-00000000000d", "June mailbox", "mailbox")];

function view(): WorkflowView {
  const step = { budget: {}, after: [] as string[], run_id: null, pull_id: null, updated_at: "2026-10-19T20:00:00+00:00", note: null,
    package: null, done: false, engine: null };
  return {
    workflow: { id: "wf-00000000000a", template: "monthly_reconciliation", template_title: "Monthly reconciliation", name: "June",
      party_id: "party-00000000000a", party: "Example Kft.", period_start: "2026-06-01", period_end: "2026-06-30", auto: false,
      status: "open", actor: "Synthetic reviewer", created_at: "2026-10-19T20:00:00+00:00", updated_at: "2026-10-19T20:00:00+00:00" },
    steps: [
      { ...step, id: "invoices", kind: "documents", title: "Incoming invoices", kind_title: "Documents: extract their data",
        source: { kind: "folder", folder: "C:\\work\\invoices" }, name: "June · invoices", state: "waiting", status: "ready" },
    ],
    done: 0, total: 1, next: { step: "invoices", status: "ready" }, events: [],
  } as unknown as WorkflowView;
}

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("181 a step takes the packages its registered kind takes", () => {
  it("offers only the package kinds the service gives for the step's kind", async () => {
    // the service says a documents step takes only watched folders' packages (a changed registration)
    const templates = { ...TEMPLATES, kinds: { ...TEMPLATES.kinds, documents: { ...TEMPLATES.kinds.documents, package_kinds: ["watch"] } } };
    vi.spyOn(api, "workflowView").mockResolvedValue(view());
    vi.spyOn(api, "workflowTemplates").mockResolvedValue(templates);
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: PACKAGES });
    render(<Workflows route={{ view: "workflows", wfId: "wf-00000000000a" }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Use an existing package…" }));
    const chooser = await screen.findByRole("combobox", { name: "Work package for Incoming invoices" });
    await screen.findByRole("option", { name: "June watch" });
    expect([...chooser.querySelectorAll("option")].map((o) => o.textContent)).toEqual(["Choose…", "June watch"]);
  });

  it("gives each kind of the templates the packages, the cost and the scope from its registration", () => {
    expect(TEMPLATES.kinds.documents.package_kinds).toEqual(["folder", "manual", "watch", "upload"]);
    expect(TEMPLATES.kinds.reconcile.paid).toBe(false);
    expect(TEMPLATES.kinds.statements.needs).toEqual(["party", "period"]);
  });
});
