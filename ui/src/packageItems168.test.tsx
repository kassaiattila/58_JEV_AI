// 168 (plan F-item-list-and-adding; DECISIONS 168): the package's item list — the same in Processing and Review — shows
// each state's count, adds files or a folder (with its subfolders) in three steps, leaves a removed document unticked,
// removes several items with one reason and restores them, and names the pending items with their run. Artificial
// data, no service.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, type DsRow, type ItemPreview, type PreviewFile, type Readiness, type StatementPackageSurvey, type Workpackage,
  type WorkpackageView } from "./api";
import { setLanguage } from "./i18n";
import { ProcessStage } from "./views/ProcessStage";
import { PackageItemsPanel } from "./views/PackageItems";

const rows = vi.hoisted(() => ({ current: [] as Record<string, unknown>[] }));

// the table shows its toolbar, the actions on its selected rows (every row counts as selected) and each row's actions
vi.mock("./components/DataTable", () => {
  return { DataTable: ({ toolbar, selectionActions }: {
    toolbar?: ReactNode; selectionActions?: (rows: DsRow[], clear: () => void) => ReactNode;
  }) => (
    <div data-testid="table">
      {toolbar}
      <div data-testid="selection">{selectionActions?.(rows.current as DsRow[], () => {})}</div>
    </div>
  ) };
});

beforeEach(async () => { await setLanguage("en"); localStorage.setItem("jav.actor", "Example Person"); });
afterEach(async () => { vi.restoreAllMocks(); localStorage.clear(); window.location.hash = ""; await setLanguage("hu"); });

const WP = { id: "wp-1", name: "Invoices", source_kind: "folder", source_ref: "C:/in", revision: 5, status: "open", created_at: "",
  updated_at: "", items: [{ item_id: "a" }, { item_id: "b" }, { item_id: "c" }], assignment: null } as unknown as Workpackage;
const READY: Readiness = { workpackage_id: "wp-1", ready: true, blockers: [], warnings: [], counts: { items: 3 },
  budget: { jev: "0.10" }, assignment_revision: 0, input_hash: "0123456789abcdef" };

function viewOf(extra: Partial<WorkpackageView> = {}, wp: Partial<Workpackage> = {}): WorkpackageView {
  return { workpackage: { ...WP, ...wp }, readiness: READY, next: { code: "start", label: "", stage: "process" }, last_run: null,
    current_run: null, runs: 0, open_runs: [], item_counts: { pending: 3 }, ...extra } as unknown as WorkpackageView;
}

const file = (name: string, state: PreviewFile["state"], over: Partial<PreviewFile> = {}): PreviewFile => ({
  path: `C:/in/${over.folder ? `${over.folder}/` : ""}${name}`, name, folder: "", item_id: name.padEnd(64, "0"), state, elsewhere: false, ...over });

function preview(files: PreviewFile[], over: Partial<ItemPreview> = {}): ItemPreview {
  const count = (s: PreviewFile["state"]) => files.filter((f) => f.state === s).length;
  return { files, folder: "C:/in", others: { count: 0, names: [] },
    counts: { new: count("new"), already: count("already"), removed: count("removed"), repeated: count("repeated"),
      elsewhere: files.filter((f) => f.elsewhere).length }, ...over };
}

it("the tally shows each state with its own mark, and the switch names the removed items' count", () => {
  rows.current = [];
  const { container } = render(<PackageItemsPanel view={viewOf({ item_counts: { approved: 3, live: 1, pending: 2, removed: 1 } })} onChanged={() => {}} />);
  const tally = container.querySelector(".items-tally") as HTMLElement;
  expect(tally.textContent).toContain("3 items");
  expect([...tally.querySelectorAll(".status")].map((s) => s.className)).toEqual(
    ["status s-approved", "status s-live", "status s-pending", "status s-removed"]);
  expect(screen.getByRole("checkbox", { name: "Removed items too (1)" })).toBeTruthy();
});

it("a folder is previewed with its subfolders; a removed document is not ticked until the person ticks it", async () => {
  rows.current = [];
  const check = vi.spyOn(api, "previewItems").mockResolvedValue(preview([
    file("top.pdf", "new"), file("deep.pdf", "new", { folder: "march" }), file("old.pdf", "removed"), file("held.pdf", "already"),
  ], { others: { count: 2, names: ["scan.jpg", "notes.png"] } }));
  const add = vi.spyOn(api, "addItems").mockResolvedValue({ added: { added: 1, already: 1, restored: 1, left_out: 1,
    processed_elsewhere: [] } } as unknown as Awaited<ReturnType<typeof api.addItems>>);
  const onChanged = vi.fn();
  render(<PackageItemsPanel view={viewOf()} onChanged={onChanged} />);
  fireEvent.click(screen.getByRole("button", { name: "Add a folder" }));
  expect((screen.getByRole("radio", { name: "A folder" }) as HTMLInputElement).checked).toBe(true);
  expect((screen.getByRole("checkbox", { name: "Include subfolders" }) as HTMLInputElement).checked).toBe(true);
  fireEvent.change(screen.getByRole("textbox", { name: "The folder to add from" }), { target: { value: "C:/in" } });
  fireEvent.click(screen.getByRole("button", { name: "Check what would be added" }));
  await waitFor(() => expect(check).toHaveBeenCalledWith("wp-1", { folder: "C:/in", recursive: true }));
  const table = await screen.findByRole("table", { name: "Files to add" });
  expect(within(table).getByText("march")).toBeTruthy(); // the subfolder column
  expect(screen.getByText(/2 other file\(s\) left out, as they are not documents: scan.jpg, notes.png/)).toBeTruthy();
  const box = (name: string) => screen.getByRole("checkbox", { name: `Add ${name}` }) as HTMLInputElement;
  expect([box("top.pdf").checked, box("deep.pdf").checked, box("old.pdf").checked]).toEqual([true, true, false]);
  expect(box("held.pdf").disabled).toBe(true);
  fireEvent.click(box("old.pdf")); // restore it
  fireEvent.click(box("deep.pdf")); // leave it out
  fireEvent.click(screen.getByRole("button", { name: "Add 2 document(s)" }));
  await waitFor(() => expect(add).toHaveBeenCalledWith("wp-1", { folder: "C:/in", recursive: true }, 5,
    { exclude: ["deep.pdf".padEnd(64, "0")], restore: ["old.pdf".padEnd(64, "0")] }));
  expect(await screen.findByText(/left out as unticked: 1/)).toBeTruthy();
  expect(onChanged).toHaveBeenCalled();
});

it("a file processed live in another package is marked, and changing the choice drops the preview", async () => {
  rows.current = [];
  vi.spyOn(api, "previewItems").mockResolvedValue(preview([file("a.pdf", "new", { elsewhere: true })], { folder: null }));
  render(<PackageItemsPanel view={viewOf()} onChanged={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Add files" }));
  const paths = screen.getByRole("textbox", { name: /Documents to add/ });
  fireEvent.change(paths, { target: { value: "C:/in/a.pdf" } });
  fireEvent.click(screen.getByRole("button", { name: "Check what would be added" }));
  expect(await screen.findByText("processed live elsewhere")).toBeTruthy();
  expect(screen.getByText(/1 of them were already processed in a live run of another package/)).toBeTruthy();
  fireEvent.change(paths, { target: { value: "C:/in/b.pdf" } });
  expect(screen.queryByRole("table", { name: "Files to add" })).toBeNull();
  expect(screen.getByRole("button", { name: "Check what would be added" })).toBeTruthy();
});

it("several selected items are removed with one reason, and selected removed ones are restored", async () => {
  rows.current = [{ _key: "a", item_id: "a", name: "a.pdf", _removed: false }, { _key: "b", item_id: "b", name: "b.pdf", _removed: false },
    { _key: "c", item_id: "c", name: "c.pdf", _removed: true }];
  const remove = vi.spyOn(api, "removeItems").mockResolvedValue({} as WorkpackageView);
  const restore = vi.spyOn(api, "restoreItems").mockResolvedValue({} as WorkpackageView);
  const onChanged = vi.fn();
  render(<PackageItemsPanel view={viewOf()} onChanged={onChanged} />);
  fireEvent.click(screen.getByRole("button", { name: "Remove 2 from the package…" }));
  const submit = screen.getByRole("button", { name: "Remove from the package" }) as HTMLButtonElement;
  expect(submit.disabled).toBe(true);
  fireEvent.change(screen.getByRole("textbox", { name: "Why remove these items (2)?" }), { target: { value: " the wrong folder " } });
  fireEvent.click(submit);
  await waitFor(() => expect(remove).toHaveBeenCalledWith("wp-1", ["a", "b"], 5, "the wrong folder"));
  // 203: the buttons stay disabled until the removal has finished; under load a click before that was lost
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Restore 1" }));
  await waitFor(() => expect(restore).toHaveBeenCalledWith("wp-1", ["c"], 5));
  expect(onChanged).toHaveBeenCalledTimes(2);
});

it("in processing the pending items' line carries their run, while the run card keeps the one solid button", () => {
  rows.current = [];
  vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
  const supplement = { items: 2, ready: true, blockers: [], warnings: [], budget: { jev: "0.02" }, input_hash: "fedcba9876543210",
    plan: { documents: 2, emails: 0, attachments: 0, paths: { S: 2, G: 0, unknown: 0 }, tasks_emails: 0, azure: false, jev_reuse: true } };
  const v = viewOf({ readiness: { ...READY, supplement: { apply: supplement } }, next: { code: "pending", label: "", stage: "process", params: { n: 2 } },
    last_run: { run_id: "run-1", mode: "apply", status: "done", items: 1, items_done: 1 } as WorkpackageView["last_run"] });
  render(<ProcessStage view={v} onChanged={() => {}} />);
  const line = screen.getByRole("region", { name: "Pending items" });
  expect(line.textContent).toContain("2 item(s) wait for processing");
  const here = within(line).getByRole("button", { name: /Live run, pending items only \(2\)/ });
  expect(here.className).toBe("secondary");
  const onCard = document.querySelector('[data-run="pending-apply"]') as HTMLButtonElement;
  expect(onCard.className).toBe("primary");
  fireEvent.click(here);
  expect(window.location.hash).toContain("/process/start");
});

it("in review the pending items' line leads to processing", () => {
  rows.current = [];
  const supplement = { items: 1, ready: true, blockers: [], warnings: [], budget: {}, input_hash: "fedcba9876543210",
    plan: { documents: 1, emails: 0, attachments: 0, paths: { S: 1, G: 0, unknown: 0 }, tasks_emails: 0, azure: false, jev_reuse: true } };
  render(<PackageItemsPanel view={viewOf({ readiness: { ...READY, supplement: { shadow: supplement } } })} onChanged={() => {}} />);
  const line = screen.getByRole("region", { name: "Pending items" });
  expect(within(line).getByRole("link", { name: "Run them in Processing" }).getAttribute("href")).toBe("#/workpackages/wp-1/process");
});

it("a statement package's folder is surveyed with its subfolders only when ticked", async () => {
  rows.current = [];
  const survey = vi.spyOn(api, "packageStatementSurvey").mockResolvedValue({ party: { id: "p-1", name: "Example Kft." },
    period_start: "2026-05-01", period_end: "2026-06-30", statements: [], pdfs: [], skipped: [] } as StatementPackageSurvey);
  render(<PackageItemsPanel view={viewOf({}, { source_kind: "statements" })} onChanged={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Add statements" }));
  const sub = screen.getByRole("checkbox", { name: "Include subfolders" }) as HTMLInputElement;
  expect(sub.checked).toBe(false);
  fireEvent.change(screen.getByRole("textbox", { name: "The statements' folder" }), { target: { value: "C:/bank" } });
  fireEvent.click(sub);
  fireEvent.click(screen.getByRole("button", { name: "Survey the files" }));
  await waitFor(() => expect(survey).toHaveBeenCalledWith("wp-1", ["C:/bank"], true));
});
