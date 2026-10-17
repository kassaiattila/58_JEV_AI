// 160-C S3: a run over only the package's pending items. The processing section offers it with its own cost cap (the
// main button when the package's next step is the pending items), the confirmation page shows the pending items'
// count, budget and input and starts with that scope, a rerun counts the package's items as they are now, and the
// review names another open live run's to-dos. Artificial data, no service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, type DsPage, type Readiness, type RunRow, type RunView, type Workpackage, type WorkpackageView } from "./api";
import { setLanguage } from "./i18n";
import { usdBudget } from "./labels";
import { parseRoute } from "./route";
import { ProcessStage } from "./views/ProcessStage";
import { ReviewWorkspace } from "./views/ReviewWorkspace";
import { StartConfirm } from "./views/StartConfirm";

vi.mock("./components/DataTable", () => ({ DataTable: () => null }));

beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => { vi.restoreAllMocks(); window.location.hash = ""; await setLanguage("hu"); });

const ITEMS = ["a", "b", "c"].map((id) => ({ item_id: id, kind: "document", source_path: `C:/x/${id}.pdf`, sha256: id, added_revision: 1 }));
const WP = { id: "wp-1", name: "Invoices", source_kind: "manual", source_ref: null, revision: 4, status: "open", created_at: "",
  updated_at: "", items: ITEMS, assignment: { workpackage_id: "wp-1", revision: 1, recipe_id: "document-processing", recipe_version: 2,
    recipe_hash: "h", params: { arm: "auto" }, actor: "Test User", note: null, created_at: "" } } as unknown as Workpackage;

const run = (id: string, extra: Partial<RunRow> = {}): RunRow => ({ run_id: id, workpackage_id: "wp-1", workpackage_name: "Invoices",
  recipe_id: "document-processing", recipe_version: 2, mode: "apply", status: "needs_review", approval: null, approved_by: null,
  actor: "Test User", created_at: "2026-10-17T10:00:00Z", finished_at: "2026-10-17T10:05:00Z", items: 2, items_done: 2,
  open_reasons: 3, ...extra });

const READY: Readiness = { workpackage_id: "wp-1", ready: true, blockers: [], warnings: [], counts: { items: 3 },
  budget: { jev: "0.15" }, assignment_revision: 1, input_hash: "0123456789abcdef",
  supplement: { apply: { items: 1, ready: true, blockers: [], warnings: [], budget: { jev: "0.05" },
    plan: { documents: 1, emails: 0, attachments: 0, paths: { S: 0, G: 0, unknown: 1 }, tasks_emails: 0, azure: false, jev_reuse: true },
    input_hash: "fedcba9876543210" } } };

function view(extra: Partial<WorkpackageView> = {}): WorkpackageView {
  const first = run("run-1");
  return { workpackage: WP, readiness: READY, next: { code: "pending", label: "", stage: "process", params: { n: 1 } },
    last_run: first, current_run: first, runs: 1, open_runs: [first], ...extra } as WorkpackageView;
}

it("the processing section offers the pending items with their own cap, as the main button when they are next", () => {
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  const { container } = render(<ProcessStage view={view()} onChanged={() => {}} />);
  const button = container.querySelector('[data-run="pending-apply"]') as HTMLButtonElement;
  expect(button.textContent).toContain("Live run, pending items only (1)");
  expect(button.querySelector(".spend")?.textContent).toBe(`≤ ${usdBudget(0.05)}`);
  expect(button.className).toBe("primary");
  expect((container.querySelector('[data-run="apply"]') as HTMLElement).className).toBe("secondary");
  expect(container.querySelector('[data-run="pending-shadow"]')).toBeNull(); // no trial run has finished items
  fireEvent.click(button);
  expect(parseRoute(window.location.hash)).toMatchObject({ view: "workpackages", wpId: "wp-1", stage: "process",
    start: { mode: "apply", rerun: false, pending: true } });
});

it("without pending items there is no such button", () => {
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  const { supplement: _none, ...plain } = READY;
  const { container } = render(<ProcessStage view={view({ readiness: plain, next: { code: "review", label: "", stage: "review" } })} onChanged={() => {}} />);
  expect(container.querySelector('[data-run^="pending"]')).toBeNull();
});

it("the confirmation of the pending items shows their count and budget and starts with their scope and input", async () => {
  vi.spyOn(api, "readiness").mockResolvedValue(READY);
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  const start = vi.spyOn(api, "start").mockResolvedValue({ run_id: "run-2", deduped: false, status: "queued" });
  render(<StartConfirm view={view()} mode="apply" rerun={false} pending onChanged={() => {}} />);
  const go = await screen.findByRole("button", { name: "Start on the pending items" }) as HTMLButtonElement;
  await waitFor(() => expect(go.disabled).toBe(false));
  expect(screen.getByText(/^1 items?$/)).toBeTruthy();
  expect(document.body.textContent).toContain(usdBudget("0.05"));
  expect(document.body.textContent).not.toContain(usdBudget("0.15"));
  fireEvent.click(go);
  await waitFor(() => expect(start).toHaveBeenCalledWith("wp-1", { mode: "apply", scope: "pending", expected_revision: 1,
    input_hash: "fedcba9876543210" }));
});

it("the confirmation says so when the pending items were processed meanwhile", async () => {
  const { supplement: _gone, ...plain } = READY;
  vi.spyOn(api, "readiness").mockResolvedValue(plain);
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  render(<StartConfirm view={view()} mode="apply" rerun={false} pending onChanged={() => {}} />);
  await screen.findByText("No item is pending any more: there is nothing to start on its own.");
  expect((screen.getByRole("button", { name: "Start on the pending items" }) as HTMLButtonElement).disabled).toBe(true);
});

it("a rerun's confirmation counts the package's items as they are now, not the last run's", async () => {
  vi.spyOn(api, "readiness").mockResolvedValue(READY);
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  render(<StartConfirm view={view()} mode="apply" rerun onChanged={() => {}} />);
  await screen.findByText("3 items");
  expect(screen.queryByText("2 items")).toBeNull();
});

it("the review opens on the current run and names another open live run's to-dos", async () => {
  const later = run("run-2", { created_at: "2026-10-17T12:00:00Z", items: 1, open_reasons: 2, scope: "pending" });
  vi.spyOn(api, "datasetQuery").mockResolvedValue({ rows: [{ _key: "run-2", run_id: "run-2" }], total: 2 } as unknown as DsPage);
  const runView = vi.spyOn(api, "run").mockImplementation(async (id: string) => ({
    run: { run_id: id, approval: null, items: [], input: { items: [{ item_id: "a", source_path: "C:/x/a.pdf" }] } },
    titles: {}, open_reasons: {}, earlier_open_reasons: {}, removed_items: [] } as unknown as RunView));
  vi.spyOn(api, "item").mockReturnValue(new Promise(() => {}));
  render(<ReviewWorkspace wp={WP} currentRunId="run-1" openRuns={[run("run-1"), later]} />);
  await waitFor(() => expect(runView).toHaveBeenCalledWith("run-1", expect.anything()));
  const note = await screen.findByRole("region", { name: "Other open live runs" });
  expect(note.textContent).toContain("2 open to-dos");
  fireEvent.click(screen.getByRole("button", { name: "Review it" }));
  await waitFor(() => expect(runView).toHaveBeenCalledWith("run-2", expect.anything()));
});
