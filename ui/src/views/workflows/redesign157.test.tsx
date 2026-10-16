// 157 (redesign): the workflows' screens follow the design system. A step's state is a state mark in its own colour
// (running blue, a person's turn orange, failed red, done green), never the action colour; the step that needs a person
// first has a firm border and the view's one solid button; a button that starts a run shows what it may spend. The
// local service is replaced by spies; synthetic names only.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type WorkflowRow, type WorkflowStep, type WorkflowView } from "../../api";
import { setLanguage } from "../../i18n";
import { Workflows } from "./Workflows";

type Status = WorkflowStep["status"];

function view(statuses: [Status, Status, Status], next: WorkflowView["next"]): WorkflowView {
  const base = { source: { kind: "folder" as const, folder: "C:\\work\\in" }, budget: {}, name: "June · step", after: [] as string[],
    run_id: null, pull_id: null, updated_at: "2026-10-16T08:00:00+00:00", note: null, package: null, state: "waiting" };
  const done = (s: Status) => s === "approved" || s === "nothing_new";
  return {
    workflow: { id: "wf-00000000000c", template: "monthly_reconciliation", template_title: "Monthly reconciliation", name: "June",
      party_id: "party-00000000000a", party: "Example Kft.", period_start: "2026-06-01", period_end: "2026-06-30", auto: false,
      status: "open", actor: "Synthetic reviewer", created_at: "2026-10-16T08:00:00+00:00", updated_at: "2026-10-16T08:00:00+00:00" },
    steps: [
      { ...base, id: "invoices", kind: "documents", title: "Incoming invoices", kind_title: "Documents: extract their data",
        status: statuses[0], done: done(statuses[0]), budget: { jev: "0.20", openai: "0.10" } },
      { ...base, id: "statements", kind: "statements", title: "Bank statements", kind_title: "Bank statements",
        status: statuses[1], done: done(statuses[1]), budget: { jev: "0.05" } },
      { ...base, id: "reconcile", kind: "reconcile", title: "Reconciliation", kind_title: "Reconciliation",
        source: { kind: "none" }, after: ["invoices", "statements"], status: statuses[2], done: done(statuses[2]) },
    ],
    done: statuses.filter(done).length, total: 3, next, events: [],
    repeat_of: null, repeated_as: [],
  } as unknown as WorkflowView;
}

const steps = () => within(screen.getByRole("list", { name: "Steps" })).getAllByRole("listitem").filter((li) => li.className.includes("wf-step"));
const mark = (li: HTMLElement) => li.querySelector(".wf-card-head .status")!;

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("a workflow's control view (157)", () => {
  it("shows each step's state as a state mark, never in the action colour", async () => {
    vi.spyOn(api, "workflowView").mockResolvedValue(view(["running", "failed", "pairing"], { step: "statements", status: "failed" }));
    render(<Workflows route={{ view: "workflows", wfId: "wf-00000000000c" }} />);
    await screen.findByRole("list", { name: "Steps" });
    const [invoices, statements, reconcile] = steps();
    expect(mark(invoices).className).toBe("status s-running");
    expect(mark(statements).className).toBe("status s-failed");
    expect(mark(reconcile).className).toBe("status s-review"); // a person pairs in its package
    expect(document.querySelector(".wf-status, .wf-dot, .wf-active")).toBeNull();
  });

  it("marks the step that needs a person first and gives only its start the solid button, with what it may spend", async () => {
    vi.spyOn(api, "workflowView").mockResolvedValue(view(["failed", "ready", "waiting"], { step: "statements", status: "ready" }));
    render(<Workflows route={{ view: "workflows", wfId: "wf-00000000000c" }} />);
    await screen.findByRole("list", { name: "Steps" });
    const [invoices, statements, reconcile] = steps();
    expect(statements.getAttribute("aria-current")).toBe("step");
    expect(invoices.getAttribute("aria-current")).toBeNull();
    const start = within(statements).getByRole("button", { name: "Start" });
    expect(start.classList.contains("primary")).toBe(true);
    expect(start.querySelector(".spend")?.textContent).toBe("≤ 0.05 USD");
    expect(start.getAttribute("title")).toBe("Starts a run that can spend up to 0.05 USD");
    const retry = within(invoices).getByRole("button", { name: "Try again" });
    expect(retry.classList.contains("primary")).toBe(false);
    expect(retry.querySelector(".spend")?.textContent).toBe("≤ 0.30 USD");
    expect(within(reconcile).getByRole("button", { name: "Start now anyway" }).querySelector(".spend")).toBeNull(); // free
    expect(document.querySelectorAll("button.primary")).toHaveLength(1);
  });
});

describe("the workflows list (157)", () => {
  const row = (statuses: [Status, Status, Status]): WorkflowRow => {
    const v = view(statuses, { step: "invoices", status: statuses[0] });
    return { ...v.workflow, done: v.done, total: 3, next: v.next, steps: v.steps.map((s) => ({ id: s.id, title: s.title, status: s.status })) } as WorkflowRow;
  };

  it("shows the chain with state marks and keeps the period on one line", async () => {
    vi.spyOn(api, "workflows").mockResolvedValue({ workflows: [row(["review", "approved", "waiting"])] });
    render(<Workflows route={{ view: "workflows" }} />);
    await screen.findByRole("link", { name: "June" });
    const chain = [...document.querySelectorAll(".wz-chain .status")].map((el) => el.className);
    expect(chain).toEqual(["status s-review", "status s-done", "status s-waiting"]);
    expect(document.querySelector(".wf-period")?.textContent).toBe("2026-06-01 – 2026-06-30");
    expect(document.querySelector(".wf-list .mono")).toBeNull();
  });

  it("leaves the wizard's step the only solid button while a new workflow is being made", async () => {
    vi.spyOn(api, "workflows").mockResolvedValue({ workflows: [] });
    vi.spyOn(api, "workflowTemplates").mockReturnValue(new Promise(() => undefined));
    render(<Workflows route={{ view: "workflows", create: true }} />);
    const toggle = await screen.findByRole("link", { name: "New workflow" });
    expect(toggle.classList.contains("primary")).toBe(false);
  });
});
