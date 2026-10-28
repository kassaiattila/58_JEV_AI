// 147 (DECISIONS 147): a workflow repeated for the next period. The control view shows the link between the two; until
// 231 U2c it offered the repeat, and the wizard opened filled in from the draft (since then a new workflow is a case of a
// multi-step process, and an earlier one is only read). The overview names an existing package chosen as a step's
// source. The local service is replaced by spies; synthetic names only.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type OwnParty, type WorkflowView } from "../../api";
import { setLanguage } from "../../i18n";
import { parseRoute, routeHash } from "../../route";
import { stepNote } from "./labels";
import { Workflows } from "./Workflows";

const PARTY: OwnParty = {
  id: "party-00000000000a", name: "Example Kft.", invoices: 3, first: null, last: null, statements_first: null,
  statements_last: null, accounts: [], identities: [], updated_at: "",
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
  it("the control view links the earlier workflow and offers no repeat (231 U2c)", async () => {
    vi.spyOn(api, "workflowView").mockResolvedValue(view());
    render(<Workflows route={{ view: "workflows", wfId: "wf-00000000000b" }} />);
    expect(await screen.findByText(/no new documents: 4 already processed by a live run/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Repeat for the next period" })).toBeNull();
    expect(screen.getByRole("link", { name: "Example Kft. 2026-09-01 – 2026-09-30" }).getAttribute("href")).toBe("#/workflows/wf-00000000000a");
    expect(screen.getByText(/no new documents: 4 already processed by a live run/)).toBeTruthy();
    expect(screen.getByText(/only the documents no live run has processed yet/)).toBeTruthy();
    expect(screen.getByText(/2 new document\(s\); 4 already processed by a live run, left out/)).toBeTruthy();
  });

  it("the repeat's old address shows the earlier workflow, and a new workflow's opens New case (231 U2c)", () => {
    expect(parseRoute("#/workflows/wf-00000000000b/repeat")).toEqual({ view: "workflows", wfId: "wf-00000000000b" });
    expect(parseRoute("#/workflows/new")).toEqual({ view: "case-list", create: true });
    expect(routeHash({ view: "workflows", wfId: "wf-00000000000b" })).toBe("#/workflows/wf-00000000000b");
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
