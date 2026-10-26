// 181 (plan 170 L5; DECISIONS 181: a general scope): a template whose steps need no party and no period makes a
// workflow without them, and a work package's party, period and role are shown and given by hand. Synthetic names
// only; the local service is replaced by spies.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import workflowConfig from "./workflows/workflowTemplates181.fixture.json";
import {
  api, setActor, type OwnParty, type PartiesOverview, type WorkflowTemplates, type WorkflowView, type WorkpackageView,
} from "../api";
import { setLanguage } from "../i18n";
import { NewWork } from "./workflows/NewWork";
import { ScopeForm, scopeEditable, scopeText } from "./PackageScope";

const TEMPLATES = workflowConfig as unknown as WorkflowTemplates;
const PARTY: OwnParty = {
  id: "party-00000000000a", name: "Example Kft.", invoices: 3, first: null, last: null, statements_first: null,
  statements_last: null, accounts: [], identities: [], updated_at: "",
};
const OVERVIEW: PartiesOverview = {
  parties: [PARTY], suggestions: [], unassigned: [], dismissed: [], invoices: 0, unclaimed_invoices: 0, ambiguous_invoices: 0,
  buyer_is_supplier: 0, no_buyer: 0, config_hash: "x",
};
const ROLES = { roles: [
  { name: "incoming_invoices", title: "Incoming invoices", package_kinds: ["folder", "manual", "watch", "upload"] },
  { name: "outgoing_invoices", title: "Outgoing invoices", package_kinds: ["folder", "manual", "watch", "upload"] },
  { name: "statements", title: "Bank statements", package_kinds: ["statements"] },
] };

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("181 a workflow without party or period", () => {
  it("asks for neither when its steps need neither, and makes the workflow without them", async () => {
    const extra = { id: "inbox_and_folder", group: "documents", title: "Inbox and folder", description: "Test only.",
      steps: [{ id: "documents", kind: "documents" }, { id: "emails", kind: "emails" }] };
    vi.spyOn(api, "workflowTemplates").mockResolvedValue({ ...TEMPLATES, templates: [...TEMPLATES.templates, extra] } as WorkflowTemplates);
    const parties = vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    const create = vi.spyOn(api, "createWorkflow").mockResolvedValue({ workflow: { id: "wf-00000000000b" } } as unknown as WorkflowView);
    const onWorkflow = vi.fn();
    render(<NewWork onPackage={vi.fn()} onWorkflow={onWorkflow} initialTemplate="inbox_and_folder" />);
    fireEvent.change(await screen.findByLabelText("Folder of Documents: extract their data"), { target: { value: "C:\\work\\in" } });
    fireEvent.change(await screen.findByLabelText(/Mailbox address/), { target: { value: "office@example.com" } });
    expect(screen.queryByLabelText("Period from")).toBeNull();
    expect(screen.queryByText("The emails received in the workflow's period")).toBeNull(); // by a number of days
    expect(parties).not.toHaveBeenCalled();
    const next = screen.getByRole("button", { name: "Next →" }) as HTMLButtonElement;
    expect(next.disabled).toBe(false);
    fireEvent.click(next);
    fireEvent.click(screen.getByRole("button", { name: "Create the workflow" }));
    await waitFor(() => expect(onWorkflow).toHaveBeenCalledWith("wf-00000000000b"));
    const body = create.mock.calls[0][0];
    expect(body.party_id).toBeUndefined();
    expect(body.period_start).toBeUndefined();
    expect(body.name).toBe("Inbox and folder");
    expect(body.steps.emails.source).toEqual({ kind: "mailbox", request: { accounts: ["office@example.com"], folders: ["Inbox"], max_items: 0, since_days: 31 } });
  });
});

function packageView(over: Partial<WorkpackageView> = {}): WorkpackageView {
  return { workpackage: { id: "wp-00000000000a", name: "June invoices", source_kind: "folder", status: "open", items: [] },
    ...over } as unknown as WorkpackageView;
}

describe("181 a package's scope", () => {
  it("is said in words, with where it comes from", () => {
    expect(scopeText({ party_id: PARTY.id, party: "Example Kft.", period_start: "2026-06-01", period_end: "2026-06-30",
      role: "incoming_invoices", role_title: "Incoming invoices", from: "workflow" }))
      .toBe("Example Kft. · 2026-06-01 – 2026-06-30 · Incoming invoices (from its workflow)");
    expect(scopeText({ party_id: null, party: null, period_start: null, period_end: null, role: "outgoing_invoices",
      role_title: "Outgoing invoices", from: "own" })).toBe("Outgoing invoices");
    expect(scopeEditable(packageView())).toBe(true);
    expect(scopeEditable(packageView({ scope: { party_id: PARTY.id, party: "Example Kft.", period_start: "2026-06-01",
      period_end: "2026-06-30", role: "statements", role_title: "Bank statements", from: "logic_pack" } }))).toBe(false);
  });

  it("is given by hand: the party, the period and a role the package's kind can hold", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    vi.spyOn(api, "packageRoles").mockResolvedValue(ROLES);
    const onSave = vi.fn();
    render(<ScopeForm view={packageView()} busy={false} onSave={onSave} onClear={vi.fn()} onCancel={vi.fn()} />);
    const role = await screen.findByRole("combobox", { name: "Role" });
    await screen.findByRole("option", { name: "Outgoing invoices" });
    expect([...role.querySelectorAll("option")].map((o) => o.textContent)).toEqual(["No role", "Incoming invoices", "Outgoing invoices"]);
    fireEvent.change(await screen.findByRole("combobox", { name: "Own party" }), { target: { value: PARTY.id } });
    fireEvent.change(screen.getByLabelText("Period from"), { target: { value: "2026-06-01" } });
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true); // half a period
    fireEvent.change(screen.getByLabelText("to"), { target: { value: "2026-06-30" } });
    fireEvent.change(role, { target: { value: "incoming_invoices" } });
    fireEvent.click(save);
    expect(onSave).toHaveBeenCalledWith({ party_id: PARTY.id, period_start: "2026-06-01", period_end: "2026-06-30", role: "incoming_invoices" });
    expect(screen.queryByRole("button", { name: "Remove the package's own scope" })).toBeNull();
  });
});
