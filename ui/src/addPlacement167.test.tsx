// 167 (the owner could not find how to add documents to an existing package): the add action sits at the top of
// Processing, above the run buttons, and in the package's actions menu; Review's document list names adding in its
// title. Artificial data, no service.
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

it("processing offers adding documents above the run buttons, with the package's count", () => {
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  const { container } = render(<ProcessStage view={view()} onChanged={() => {}} />);
  const add = screen.getByRole("button", { name: "Add documents" });
  const firstRun = container.querySelector("[data-run]") as HTMLElement;
  // the add action comes before the run buttons in the reading order
  expect(add.compareDocumentPosition(firstRun) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(container.textContent).toContain("2 documents");
  fireEvent.click(add);
  expect(parseRoute(window.location.hash)).toMatchObject({ wpId: "wp-1", stage: "process", add: true });
});

it("the open form adds by path, shows the service's counts and closes back to processing", async () => {
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  const add = vi.spyOn(api, "addItems").mockResolvedValue({ added: { added: 1, already: 0, restored: 0,
    processed_elsewhere: [] } } as unknown as Awaited<ReturnType<typeof api.addItems>>);
  const onChanged = vi.fn();
  render(<ProcessStage view={view()} adding onChanged={onChanged} />);
  fireEvent.change(screen.getByRole("textbox", { name: /Documents to add/ }), { target: { value: "C:/in/new.pdf" } });
  fireEvent.click(screen.getByRole("button", { name: "Add 1 document(s)" }));
  await waitFor(() => expect(add).toHaveBeenCalledWith("wp-1", ["C:/in/new.pdf"], 4));
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

it("a reconciliation package's menu has nothing to add", () => {
  render(<WorkpackageActions view={view({ source_kind: "reconcile" })} onChanged={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Manage package" }));
  expect(screen.queryByRole("button", { name: "Add documents" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Add statements" })).toBeNull();
});

it("after a run, review's document list names adding in its title", async () => {
  vi.spyOn(api, "workpackage").mockResolvedValue(view({}, { runs: 1, next: { code: "review", label: "", stage: "review" } }));
  render(<WorkpackageDetail route={{ view: "workpackages", wpId: "wp-1", stage: "review" }} wpId="wp-1" />);
  expect(await screen.findByText("Documents: add, open, download, remove")).toBeTruthy();
});
