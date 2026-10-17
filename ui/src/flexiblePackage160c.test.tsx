// 160-C S1 (decisions 163 D2, D3, D7): removing a package's item names the person and needs a reason; removed items
// show behind a switch and can be restored; the approval of a run with removed items says so and sends the count it
// showed. Artificial data, no service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, type DsPage, type DsRow, type RunView, type Workpackage, type WorkpackageView } from "./api";
import { DocumentsPanel } from "./views/DocumentsPanel";
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

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

const WP = { id: "wp-1", name: "Invoices", source_kind: "manual", source_ref: null, revision: 3, status: "open", created_at: "",
  updated_at: "", items: [], assignment: null } as unknown as Workpackage;

function panel(): { onChanged: ReturnType<typeof vi.fn> } {
  const onChanged = vi.fn();
  render(<DocumentsPanel wp={WP} onChanged={onChanged} />);
  return { onChanged };
}

it("a removal asks for a reason and sends it with the package's revision", async () => {
  localStorage.setItem("jav.actor", "Example Person");
  rows.current = [{ _key: "doc-1", item_id: "doc-1", name: "invoice.pdf", original_name: "invoice.pdf", _removed: false }];
  const remove = vi.spyOn(api, "removeItem").mockResolvedValue({ workpackage: WP });
  const { onChanged } = panel();
  fireEvent.click(screen.getByRole("button", { name: "Eltávolítás" }));
  const submit = screen.getByRole("button", { name: "Kivétel a csomagból" }) as HTMLButtonElement;
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
  fireEvent.click(screen.getByRole("checkbox", { name: /Kivett tételek is/ }));
  expect(JSON.parse(screen.getByTestId("table").dataset.scope ?? "{}").removed).toBe("1");
  const row = screen.getByTestId("row-doc-2");
  expect(row.querySelector("a")).toBeNull(); // the service does not serve a removed item's file
  fireEvent.click(screen.getByRole("button", { name: "Visszaállítás" }));
  await waitFor(() => expect(restore).toHaveBeenCalledWith("wp-1", "doc-2", 3));
});

it("the package says what it was created from by its kind", () => {
  rows.current = [];
  render(<DocumentsPanel wp={{ ...WP, source_kind: "statements" } as Workpackage} onChanged={() => {}} />);
  expect(screen.getByText(/Létrehozva ebből: kivonatcsomag/)).toBeTruthy();
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
  await screen.findByText("1 nyitott teendő ebben a futásban");
  const queue = screen.getByRole("navigation", { name: "Tételek" });
  expect(queue.textContent).toContain("Kivéve");
});

const VIEW = { workpackage: { id: "wp-1" }, last_run: { run_id: "run-1" }, runs: 1 } as unknown as WorkpackageView;

it("the approval of a run with a removed item names it, leaves its to-dos out and sends the count", async () => {
  rows.current = [];
  vi.spyOn(api, "run").mockResolvedValue({ run: { run_id: "run-1", mode: "apply", status: "done", approval: null },
    tables: ["datapoints"], open_reasons: { "doc-1": [{ reason: "pick" }] }, review_version: "v1",
    removed_items: ["doc-1"] } as unknown as RunView);
  vi.spyOn(api, "datasetQuery").mockResolvedValue({ rows: [], review_version: "v1" } as unknown as DsPage);
  const approve = vi.spyOn(api, "approve").mockResolvedValue({} as RunView);
  const { container } = render(<ResultStage view={VIEW} onChanged={() => {}} />);
  await waitFor(() => expect(container.querySelector(".release-line")).not.toBeNull());
  const line = container.querySelector(".release-line") as HTMLElement;
  expect(line.dataset.state).toBe("ready"); // the removed item's to-do does not count
  expect(line.querySelector(".release-removed .status.s-warn")?.textContent).toContain("1");
  const button = line.querySelector("button") as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  fireEvent.click(button); // the approval needs two clicks
  await waitFor(() => expect(approve).toHaveBeenCalledWith("run-1", "v1", 1));
});
