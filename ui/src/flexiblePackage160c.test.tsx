// 160-C S1 (decisions 163 D2, D3, D7): removing a package's item names the person and needs a reason; removed items
// show behind a switch and can be restored; the release of a package with removed items says so and sends the count
// it showed (172: the package's Approve and release). Artificial data, no service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, type DsPage, type DsRow, type PackageResult, type RunView, type Workpackage, type WorkpackageView } from "./api";
import { setLanguage } from "./i18n";
import { PackageItemsPanel } from "./views/PackageItems";
import { ResultStage } from "./views/ResultStage";
import { ReviewWorkspace } from "./views/ReviewWorkspace";

const rows = vi.hoisted(() => ({ current: [] as Record<string, unknown>[] }));

// the table shows its scope, its toolbar and each row's actions (the dataset itself is the service's)
vi.mock("./components/DataTable", async () => {
  const React = await import("react");
  return { DataTable: ({ scope, toolbar, actions, onPage }: {
    scope?: Record<string, string>; toolbar?: React.ReactNode; actions?: (row: DsRow) => React.ReactNode; onPage?: (p: DsPage) => void;
  }) => {
    React.useEffect(() => { onPage?.({ rows: [], review_version: "v1" } as unknown as DsPage); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return (
      <div data-testid="table" data-scope={JSON.stringify(scope ?? {})}>
        {toolbar}
        {rows.current.map((r) => <div key={String(r._key)} data-testid={`row-${String(r._key)}`}>{actions?.(r as DsRow)}</div>)}
      </div>
    );
  } };
});

// the interface in English, so the tests read the source labels
beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => { vi.restoreAllMocks(); localStorage.clear(); await setLanguage("hu"); });

const WP = { id: "wp-1", name: "Invoices", source_kind: "manual", source_ref: null, revision: 3, status: "open", created_at: "",
  updated_at: "", items: [], assignment: null } as unknown as Workpackage;

// 168: the package's item list (the same in Processing and Review) takes the package's view
const viewOf = (wp: Workpackage) => ({ workpackage: wp, readiness: {}, item_counts: {} } as unknown as WorkpackageView);

function panel(): { onChanged: ReturnType<typeof vi.fn> } {
  const onChanged = vi.fn();
  render(<PackageItemsPanel view={viewOf(WP)} onChanged={onChanged} />);
  return { onChanged };
}

it("a removal asks for a reason and sends it with the package's revision", async () => {
  localStorage.setItem("jav.actor", "Example Person");
  rows.current = [{ _key: "doc-1", item_id: "doc-1", name: "invoice.pdf", original_name: "invoice.pdf", _removed: false }];
  const remove = vi.spyOn(api, "removeItem").mockResolvedValue({ workpackage: WP });
  const { onChanged } = panel();
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  const submit = screen.getByRole("button", { name: "Remove from the package" }) as HTMLButtonElement;
  expect(submit.disabled).toBe(true); // no reason yet
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "  a duplicate scan " } });
  expect(submit.disabled).toBe(false);
  fireEvent.click(submit);
  await waitFor(() => expect(remove).toHaveBeenCalledWith("wp-1", "doc-1", 3, "a duplicate scan"));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  expect(screen.queryByRole("textbox")).toBeNull(); // the form closes after the removal
});

it("the switch asks for the removed items too, and a removed item offers only its restore", async () => {
  rows.current = [{ _key: "doc-2", item_id: "doc-2", name: "old.pdf", _removed: true }];
  const restore = vi.spyOn(api, "restoreItem").mockResolvedValue({ workpackage: WP });
  panel();
  expect(JSON.parse(screen.getByTestId("table").dataset.scope ?? "{}").removed).toBeUndefined();
  fireEvent.click(screen.getByRole("checkbox", { name: /Removed items too/ }));
  expect(JSON.parse(screen.getByTestId("table").dataset.scope ?? "{}").removed).toBe("1");
  const row = screen.getByTestId("row-doc-2");
  expect(row.querySelector("a")).toBeNull(); // the service does not serve a removed item's file
  fireEvent.click(screen.getByRole("button", { name: "Restore" }));
  await waitFor(() => expect(restore).toHaveBeenCalledWith("wp-1", "doc-2", 3));
});

it("the package says what it was created from by its kind", () => {
  rows.current = [];
  render(<PackageItemsPanel view={viewOf({ ...WP, source_kind: "statements" } as Workpackage)} onChanged={() => {}} />);
  expect(screen.getByText(/Created from: a statement package/)).toBeTruthy();
});

it("the review list marks a removed item and does not count its to-dos as the run's work", async () => {
  const reason = (id: number) => ({ id, reason: "pick:low_conf:invoice_number:0.40", producer: "flow", run_id: "run-1:x", field: null });
  vi.spyOn(api, "datasetQuery").mockResolvedValue({ dataset: { name: "runs", label: "Runs", scope: ["workpackage_id"], optional_scope: [],
    natural_sort: [] }, columns: [], rows: [{ _key: "run-1", run_id: "run-1" }], total: 1, matched: 1, offset: 0, limit: 1, facets: {} } as unknown as DsPage);
  vi.spyOn(api, "run").mockResolvedValue({
    run: { run_id: "run-1", approval: null, items: [{ item_id: "a", status: "done", final_status: "needs_review" },
      { item_id: "b", status: "done", final_status: "needs_review" }],
    input: { items: [{ item_id: "a", source_path: "C:/x/a.pdf" }, { item_id: "b", source_path: "C:/x/b.pdf" }] } },
    titles: {}, open_reasons: { a: [reason(1)], b: [reason(2)] }, earlier_open_reasons: {}, removed_items: ["a"],
  } as unknown as RunView);
  vi.spyOn(api, "item").mockReturnValue(new Promise(() => {}));
  render(<ReviewWorkspace wp={{ id: "wp-1" } as Workpackage} itemId="b" />);
  await screen.findByText("Open to-dos in this run: 1");
  const queue = screen.getByRole("navigation", { name: "Items" });
  expect(queue.textContent).toContain("Removed");
});

const VIEW = { workpackage: { id: "wp-1" }, last_run: { run_id: "run-1" }, runs: 1 } as unknown as WorkpackageView;

it("the release of a package with a removed item names it and sends the count", async () => {
  // 172: the package's Approve and release (the run's own line has no approval)
  rows.current = [];
  vi.spyOn(api, "run").mockResolvedValue({ run: { run_id: "run-1", mode: "apply", status: "done", approval: null },
    tables: ["datapoints"], open_reasons: { "doc-1": [{ reason: "pick" }] }, review_version: "v1",
    removed_items: ["doc-1"] } as unknown as RunView);
  vi.spyOn(api, "packageResult").mockResolvedValue({ workpackage_id: "wp-1", mark: "m1", open_live_runs: ["run-1"], removed_items: 1,
    blockers: [], state: "not_released", versions: [], tables: ["datapoints"],
    items: [{ item_id: "doc-2", kind: "document", file: "b.pdf", tier: "live", run_id: "run-1", final_status: "done", released: false }] } as PackageResult);
  const give = vi.spyOn(api, "releasePackage").mockResolvedValue({} as never);
  const { container } = render(<ResultStage view={VIEW} onChanged={() => {}} />);
  await waitFor(() => expect(container.querySelector(".release-line")).not.toBeNull());
  const line = container.querySelector(".release-line") as HTMLElement;
  expect(line.dataset.state).toBe("ready"); // the removed item's to-do does not count
  expect(line.querySelector(".release-removed .status.s-warn")?.textContent).toContain("1");
  const button = line.querySelector("button") as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  fireEvent.click(button); // the release needs two clicks
  await waitFor(() => expect(give).toHaveBeenCalledWith("wp-1", "m1", 1));
});

// --- S2: adding to an existing package ---------------------------------------------------------------------------

it("adding documents sends the paths with the revision and shows the service's own counts", async () => {
  rows.current = [];
  const file = (name: string) => ({ path: `C:/in/${name}`, name, folder: "", item_id: name.padEnd(64, "0"), state: "new" as const, elsewhere: false });
  vi.spyOn(api, "previewItems").mockResolvedValue({ files: [file("a.pdf"), file("b.pdf")], folder: null,
    counts: { new: 2, already: 0, removed: 0, repeated: 0, elsewhere: 0 }, others: { count: 0, names: [] } });
  const add = vi.spyOn(api, "addItems").mockResolvedValue({ added: { added: 1, already: 1, restored: 0,
    processed_elsewhere: ["invoice_2.pdf"] } } as unknown as Awaited<ReturnType<typeof api.addItems>>);
  const { onChanged } = panel();
  fireEvent.click(screen.getByRole("button", { name: "Add files" }));
  fireEvent.change(screen.getByRole("textbox", { name: /Documents to add/ }), { target: { value: "C:/in/a.pdf\n\"C:/in/b.pdf\"\n" } });
  fireEvent.click(screen.getByRole("button", { name: "Check what would be added" }));
  fireEvent.click(await screen.findByRole("button", { name: "Add 2 document(s)" }));
  await waitFor(() => expect(add).toHaveBeenCalledWith("wp-1", { paths: ["C:/in/a.pdf", "C:/in/b.pdf"] }, 3, { exclude: [], restore: [] }));
  expect(await screen.findByText("Added: 1 · already in the package: 1 · restored: 0")).toBeTruthy();
  expect(screen.getByText(/Already processed in a live run of another package: invoice_2.pdf/)).toBeTruthy();
  expect(onChanged).toHaveBeenCalled();
});

it("a statement package grows through its survey, and what it holds cannot be ticked again", async () => {
  rows.current = [];
  const row = (id: string, inPackage: boolean) => ({ id, institution: "Example Bank", file: `${id}.xlsx`, companion: null, title: "Account",
    account: "…1234", currency: "HUF", period_start: "2026-05-01", period_end: "2026-05-31", lines: 3, checks_ok: true,
    balance_checked: true, rank: "code_checked", in_period: true, in_store: inPackage, owner: "package" as const, owner_party: null,
    replaces: [], replaced_by: null, conflicts: [], chosen: !inPackage, in_package: inPackage });
  vi.spyOn(api, "packageStatementSurvey").mockResolvedValue({ party: { id: "p-1", name: "Example Kft." }, period_start: "2026-05-01",
    period_end: "2026-06-30", statements: [row("a".repeat(64), true), row("b".repeat(64), false)], pdfs: [], skipped: [] });
  const add = vi.spyOn(api, "addPackageStatements").mockResolvedValue({} as Awaited<ReturnType<typeof api.addPackageStatements>>);
  render(<PackageItemsPanel view={viewOf({ ...WP, source_kind: "statements" } as Workpackage)} onChanged={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Add statements" }));
  fireEvent.change(screen.getByRole("textbox", { name: "The statements' folder" }), { target: { value: "C:/bank" } });
  fireEvent.click(screen.getByRole("button", { name: "Survey the files" }));
  const boxes = await screen.findAllByRole("checkbox", { name: /^Choose/ });
  expect((boxes[0] as HTMLInputElement).disabled).toBe(true);
  expect((boxes[1] as HTMLInputElement).checked).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Add 1 statement(s) and 0 PDF(s)" }));
  await waitFor(() => expect(add).toHaveBeenCalledWith("wp-1", { paths: ["C:/bank"], expected_revision: 3, statements: ["b".repeat(64)], pdfs: [] }));
});
