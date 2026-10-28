// 218 (plan P3 P3l; the owner's decisions of 2026-10-23): a workflow step built on an earlier step that was reopened
// is out of date: its card says so with a neutral mark (it waits for the earlier step) and names the steps it was built
// on; once the earlier step is approved again the step shows its package's own next step with the same note. When the
// chain reopens a version, its reason is the interface's own text, translated; a person's reason shows as written.
// The local service is replaced by spies; synthetic names only.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type OwnVersion, type WorkflowStep, type WorkflowView } from "../../api";
import { EarlierVersions } from "../../components/ApprovalPanel";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { Workflows } from "./Workflows";

const CHAIN_NOTE = "a step it builds on has a new result: check it and approve it again";

function step(over: Partial<WorkflowStep>): WorkflowStep {
  return { id: "invoices", kind: "documents", title: "Incoming invoices", kind_title: "Documents: extract their data", after: [],
    source: { kind: "folder", folder: "C:\\work\\invoices", recursive: false }, budget: {}, name: "October · invoices",
    state: "started", status: "approve", done: false, note: null, package: null, run_id: null, pull_id: null,
    updated_at: "2026-10-23T08:00:00+00:00", ...over };
}

function view(reconcile: Partial<WorkflowStep>): WorkflowView {
  return {
    workflow: { id: "wf-00000000000c", template: "monthly_reconciliation", template_title: "Monthly reconciliation",
      name: "Example Kft. 2026-10", party_id: "party-00000000000a", party: "Example Kft.", period_start: "2026-10-01",
      period_end: "2026-10-31", auto: false, status: "open", actor: "Synthetic reviewer", created_at: "2026-10-23T08:00:00+00:00",
      updated_at: "2026-10-23T08:00:00+00:00" },
    steps: [step({}), step({ id: "reconcile", kind: "reconcile", title: "Reconciliation", kind_title: "Reconciliation",
      after: ["invoices"], source: { kind: "none" }, name: "October · reconciliation", ...reconcile })],
    done: 0, total: 2, next: { step: "invoices", status: "approve" }, events: [], repeat_of: null, repeated_as: [],
  };
}

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("a step built on a reopened step", () => {
  it("is out of date with a neutral mark and names the steps it was built on", async () => {
    vi.spyOn(api, "workflowView").mockResolvedValue(view({ status: "stale", stale_of: ["invoices"] }));
    const { container } = render(<Workflows route={{ view: "workflows", wfId: "wf-00000000000c" }} />);
    expect(await screen.findByText("Built on an earlier result of Incoming invoices: approve it again after them.")).toBeTruthy();
    const marks = [...container.querySelectorAll(".wf-card .status")].map((s) => [s.textContent, s.className]);
    expect(marks).toEqual([["awaiting approval", "status s-review"], ["out of date", "status s-waiting"]]);
    expect(container.querySelectorAll(".wf-card button").length).toBe(0); // nothing to start: nothing runs by itself
  });

  it("keeps the note while it waits for its approval again, and a step not out of date has none", async () => {
    vi.spyOn(api, "workflowView").mockResolvedValue(view({ status: "pairing", stale_of: ["invoices"] }));
    render(<Workflows route={{ view: "workflows", wfId: "wf-00000000000c" }} />);
    expect(await screen.findAllByText(/^Built on an earlier result of/)).toHaveLength(1);
    expect(screen.getByText("pairing in its batch")).toBeTruthy();
  });
});

describe("the reason of a reopened version", () => {
  const version = (note: string): OwnVersion => ({ version: 1, fingerprint: "f", approved_by: "Synthetic reviewer",
    approved_at: "2026-10-23T08:00:00+00:00", reopened_by: "Synthetic reviewer (auto)", reopened_at: "2026-10-23T09:00:00+00:00",
    reopen_note: note });

  it("is translated when the chain gave it and shown as written when a person did", async () => {
    await setLanguage("hu");
    const chain = render(<EarlierVersions versions={[version(CHAIN_NOTE)]} />).container.textContent ?? "";
    expect(chain).toContain((hungarian as Record<string, string>)[CHAIN_NOTE]);
    expect(chain).not.toContain(CHAIN_NOTE);
    cleanup();
    const person = render(<EarlierVersions versions={[version("checked with the supplier")]} />).container.textContent ?? "";
    expect(person).toContain("checked with the supplier");
  });
});
