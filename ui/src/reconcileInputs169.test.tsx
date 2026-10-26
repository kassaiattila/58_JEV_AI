// 169 (DECISIONS 169): a reconciliation package's item list — its inputs by kind, leaving documents out of this
// reconciliation only with one reason and restoring them, and adding files to an existing documents or statement
// package with that package's own three steps. Artificial data, no service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, type DsRow, type WorkpackageView } from "./api";
import type { ReconcileTargets, ReconcileWorkspace } from "./domains/finance/api";
import { setLanguage } from "./i18n";
import { ReconcileInputs } from "./domains/finance/reconcile/ReconcileInputs";

const rows = vi.hoisted(() => ({ current: [] as Record<string, unknown>[] }));

// the table shows its toolbar and the actions on its selected rows (every row counts as selected)
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
afterEach(async () => { vi.restoreAllMocks(); localStorage.clear(); await setLanguage("hu"); });

function wsOf(counts: Partial<ReconcileWorkspace["counts"]> = {}, partyId: string | null = "party-1"): ReconcileWorkspace {
  return { workpackage_id: "wp-rc", scope: { workpackage_id: "wp-rc", accounts: ["k"], period_start: "2026-01-01",
    period_end: "2026-03-31", revision: 1, party_id: partyId }, lines: [], invoices: [], coverage: [], blockers: [],
    line_marks: [], open: {}, counts: { lines: {}, invoices: {}, open_lines: 0, other_invoices: 7, statements: 3,
      own_invoices: 12, left_out: 2, ...counts }, decision_state: [1] } as unknown as ReconcileWorkspace;
}

const TARGETS: ReconcileTargets = {
  documents: [
    { id: "wp-giver", name: "March invoices", source_kind: "folder", items: 40, inputs: 9, updated_at: "2026-10-01" },
    { id: "wp-other", name: "Loose files", source_kind: "manual", items: 3, inputs: 0, updated_at: "2026-10-02" },
  ],
  statements: [],
};

it("the tally counts the inputs by kind, and the switches name the left-out and the other parties' documents", () => {
  rows.current = [];
  const { container } = render(<ReconcileInputs ws={wsOf()} readOnly={false} onWorkspace={() => {}} />);
  const tally = container.querySelector(".items-tally") as HTMLElement;
  expect(tally.textContent).toContain("15 documents");
  expect(tally.textContent).toContain("3 statements");
  expect(tally.textContent).toContain("12 invoices");
  expect(tally.textContent).toContain("7 invoices of other parties");
  expect(tally.querySelector(".s-removed")?.textContent).toBe("2 left out");
  expect(screen.getByRole("checkbox", { name: "Left-out documents too (2)" })).toBeTruthy();
  expect(screen.getByRole("checkbox", { name: "Other parties' invoices too (7)" })).toBeTruthy();
});

it("a package without a party has no other parties' switch", () => {
  rows.current = [];
  render(<ReconcileInputs ws={wsOf({}, null)} readOnly={false} onWorkspace={() => {}} />);
  expect(screen.queryByRole("checkbox", { name: /Other parties/ })).toBeNull();
});

it("several documents are left out of this reconciliation with one reason", async () => {
  rows.current = [{ doc_id: "d1", name: "a.pdf", _left_out: false }, { doc_id: "d2", name: "b.pdf", _left_out: false }];
  const next = wsOf({ left_out: 4 });
  const leave = vi.spyOn(api, "reconcileLeaveOut").mockResolvedValue(next);
  const onWorkspace = vi.fn();
  render(<ReconcileInputs ws={wsOf()} readOnly={false} onWorkspace={onWorkspace} />);
  fireEvent.click(screen.getByRole("button", { name: "Leave 2 out of this reconciliation…" }));
  const why = screen.getByRole("textbox", { name: "Why leave these documents (2) out of this reconciliation?" });
  const submit = screen.getByRole("button", { name: "Leave out of this reconciliation" }) as HTMLButtonElement;
  expect(submit.disabled).toBe(true); // the reason is required
  expect(screen.getByText("The document stays in its own package and in every other reconciliation, and it can be restored here.")).toBeTruthy();
  fireEvent.change(why, { target: { value: "another company's" } });
  fireEvent.click(submit);
  await waitFor(() => expect(leave).toHaveBeenCalledWith("wp-rc", ["d1", "d2"], "another company's"));
  await waitFor(() => expect(onWorkspace).toHaveBeenCalledWith(next));
  expect(screen.queryByRole("form", { name: "Leave out of this reconciliation" })).toBeNull(); // done: the form closes
});

it("left-out documents are restored from the selection", async () => {
  rows.current = [{ doc_id: "d9", name: "gone.pdf", _left_out: true }];
  const restore = vi.spyOn(api, "reconcileRestoreLeftOut").mockResolvedValue(wsOf({ left_out: 1 }));
  render(<ReconcileInputs ws={wsOf()} readOnly={false} onWorkspace={() => {}} />);
  expect(screen.queryByRole("button", { name: /Leave .* out/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Restore 1" }));
  await waitFor(() => expect(restore).toHaveBeenCalledWith("wp-rc", ["d9"]));
});

it("files go to a chosen documents package, the givers first, with that package's three steps", async () => {
  rows.current = [];
  vi.spyOn(api, "reconcileTargets").mockResolvedValue(TARGETS);
  const view = { workpackage: { id: "wp-giver", name: "March invoices", source_kind: "folder", revision: 4, items: [] } } as unknown as WorkpackageView;
  const load = vi.spyOn(api, "workpackage").mockResolvedValue(view);
  render(<ReconcileInputs ws={wsOf()} readOnly={false} onWorkspace={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Add documents" }));
  const select = await screen.findByRole("combobox", { name: "Add them to the documents package" }) as HTMLSelectElement;
  expect([...select.options].map((o) => o.textContent)).toEqual([
    "March invoices · 9 of its documents are in this reconciliation", "Loose files · 3 items"]);
  await waitFor(() => expect(load).toHaveBeenCalledWith("wp-giver"));
  expect(await screen.findByRole("form", { name: "Add documents to the package" })).toBeTruthy();
  expect((screen.getByRole("radio", { name: "A folder" }) as HTMLInputElement).checked).toBe(true);
  fireEvent.click(screen.getByRole("radio", { name: "Bank statements" }));
  expect(screen.getByText("This party has no statement package yet; create one from the package list.")).toBeTruthy();
});

it("an approved package lists its inputs without adding or leaving out", () => {
  rows.current = [{ doc_id: "d1", name: "a.pdf", _left_out: false }];
  render(<ReconcileInputs ws={wsOf()} readOnly onWorkspace={() => {}} />);
  expect(screen.queryByRole("button", { name: "Add documents" })).toBeNull();
  expect(screen.queryByRole("button", { name: /Leave 1 out/ })).toBeNull();
});
