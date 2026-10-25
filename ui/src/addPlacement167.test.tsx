// 167 (the owner could not find how to add documents to an existing package): the add action is in Processing and in
// the package's actions menu; Review's list names adding in its title. 168 (DECISIONS 168, the owner's choice "Run on
// top"): the item list with its add actions sits below the Run card, and adding is previewed before anything is
// written. Artificial data, no service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, type Readiness, type Workpackage, type WorkpackageView } from "./api";
import { setLanguage } from "./i18n";
import { parseRoute, routeHash } from "./route";
import { ProcessStage } from "./views/ProcessStage";
import { WorkpackageActions } from "./views/WorkpackageActions";
import { WorkpackageDetail } from "./views/WorkpackageDetail";

vi.mock("./components/DataTable", () => ({ DataTable: () => null }));
vi.mock("./views/ReviewWorkspace", () => ({ ReviewWorkspace: () => null }));

beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => { vi.restoreAllMocks(); window.location.hash = ""; await setLanguage("hu"); });

const ITEMS = ["a", "b"].map((id) => ({ item_id: id, kind: "document", source_path: `C:/x/${id}.pdf`, sha256: id, added_revision: 1 }));
const WP = { id: "wp-1", name: "Invoices", source_kind: "manual", source_ref: null, revision: 4, status: "open", created_at: "",
  updated_at: "", items: ITEMS, assignment: null } as unknown as Workpackage;
const READY: Readiness = { workpackage_id: "wp-1", ready: true, blockers: [], warnings: [], counts: { items: 2 },
  budget: { jev: "0.10" }, assignment_revision: 0, input_hash: "0123456789abcdef" };

function view(wp: Partial<Workpackage> = {}, extra: Partial<WorkpackageView> = {}): WorkpackageView {
  return { workpackage: { ...WP, ...wp }, readiness: READY, next: { code: "start", label: "", stage: "process" },
    last_run: null, current_run: null, runs: 0, open_runs: [], ...extra } as unknown as WorkpackageView;
}

it("the address of the add form survives a reload", () => {
  const r = parseRoute("#/workpackages/wp-1/process/add");
  expect(r).toMatchObject({ view: "workpackages", wpId: "wp-1", stage: "process", add: true });
  expect(routeHash(r)).toBe("#/workpackages/wp-1/process/add");
  expect(parseRoute("#/workpackages/wp-1/process")).not.toHaveProperty("add");
});

it("processing shows the package's items below the run buttons, with adding files and a folder", () => {
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  const { container } = render(<ProcessStage view={view({}, { item_counts: { pending: 2 } })} onChanged={() => {}} />);
  const add = screen.getByRole("button", { name: "Add files" });
  const firstRun = container.querySelector("[data-run]") as HTMLElement;
  // the run buttons come first in the reading order, the item list with its add actions after them
  expect(firstRun.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add a folder" })).toBeTruthy();
  expect(container.querySelector(".items-tally")?.textContent).toContain("2 items");
  fireEvent.click(add);
  expect(parseRoute(window.location.hash)).toMatchObject({ wpId: "wp-1", stage: "process", add: true });
});

it("the open form previews, adds by path, shows the service's counts and closes back to processing", async () => {
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  vi.spyOn(api, "previewItems").mockResolvedValue({ folder: null, others: { count: 0, names: [] },
    files: [{ path: "C:/in/new.pdf", name: "new.pdf", folder: "", item_id: "c".repeat(64), state: "new", elsewhere: false }],
    counts: { new: 1, already: 0, removed: 0, repeated: 0, elsewhere: 0 } });
  const add = vi.spyOn(api, "addItems").mockResolvedValue({ added: { added: 1, already: 0, restored: 0,
    processed_elsewhere: [] } } as unknown as Awaited<ReturnType<typeof api.addItems>>);
  const onChanged = vi.fn();
  const { container } = render(<ProcessStage view={view()} adding onChanged={onChanged} />);
  fireEvent.change(screen.getByRole("textbox", { name: /Documents to add/ }), { target: { value: "C:/in/new.pdf" } });
  fireEvent.click(screen.getByRole("button", { name: "Check what would be added" }));
  const submit = await screen.findByRole("button", { name: "Add 1 document(s)" });
  // while the form is open its last step is the view's one solid button
  expect([...container.querySelectorAll("button.primary")]).toEqual([submit]);
  fireEvent.click(submit);
  await waitFor(() => expect(add).toHaveBeenCalledWith("wp-1", { paths: ["C:/in/new.pdf"] }, 4, { exclude: [], restore: [] }));
  expect(await screen.findByText("Added: 1 · already in the package: 0 · restored: 0")).toBeTruthy();
  expect(onChanged).toHaveBeenCalled();
  expect(parseRoute(window.location.hash)).not.toHaveProperty("add");
});

it("a statement package offers adding statements in processing", () => {
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  render(<ProcessStage view={view({ source_kind: "statements" })} onChanged={() => {}} />);
  expect(screen.getByRole("button", { name: "Add statements" })).toBeTruthy();
});

it("the package's actions menu leads to the add form in processing", () => {
  render(<WorkpackageActions view={view()} onChanged={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Manage package" }));
  fireEvent.click(screen.getByRole("button", { name: "Add documents" }));
  expect(parseRoute(window.location.hash)).toMatchObject({ wpId: "wp-1", stage: "process", add: true });
});

// 231 (C3a-2): a reconciliation is a process pack's case since its package kind retired (no package menu of its own)

it("after a run, review's item list names adding in its title", async () => {
  vi.spyOn(api, "workpackage").mockResolvedValue(view({}, { runs: 1, next: { code: "review", label: "", stage: "review" } }));
  render(<WorkpackageDetail route={{ view: "workpackages", wpId: "wp-1", stage: "review" }} wpId="wp-1" />);
  expect(await screen.findByText("The package's items: add, open, download, remove")).toBeTruthy();
});
