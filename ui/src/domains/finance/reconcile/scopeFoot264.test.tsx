// 264 (plan E, F5; the owner's decision of 2026-10-31): the reconciliation's scope is saved from its card's foot - "Cancel"
// puts back what is saved, the save is the card's main button while something changed - instead of a quiet button in
// the period's row. Synthetic data, a mocked service.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, setActor } from "../../../api";
import type { ReconcileWorkspace } from "../api";
import { setLanguage } from "../../../i18n";
import { ReconcilePrepare } from "./ReconcileStages";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

const WS = {
  workpackage_id: "wp-000000000264", lines: [], invoices: [], coverage: [], line_marks: [], open: {}, blockers: [], left_over: [],
  counts: { lines: {}, invoices: {}, open_lines: 0 }, learned_names: [], fx_tolerance: null, engine_version: "1.8.0", config_hash: "x",
  scope: { workpackage_id: "wp-000000000264", accounts: ["acc-1"], period_start: "2026-04-01", period_end: "2026-04-30", revision: 3,
    updated_at: "" },
} as unknown as ReconcileWorkspace;

it("saves the scope from the card's foot and puts it back on Cancel", async () => {
  vi.spyOn(api, "reconcileAccounts").mockResolvedValue({ accounts: [] } as never);
  vi.spyOn(api, "parties").mockResolvedValue({ parties: [], suggestions: [], unassigned: [], dismissed: [] } as never);
  const save = vi.spyOn(api, "setReconcileScope").mockResolvedValue(WS);
  render(<ReconcilePrepare ws={WS} readOnly={false} onWorkspace={() => {}} reload={() => {}} />);
  const card = screen.getByRole("region", { name: "Scope" });
  const button = within(card).getByRole("button", { name: "Save the scope" });
  expect(button.closest(".form-actions")).toBeTruthy();
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(within(card).queryByRole("button", { name: "Cancel" })).toBeNull();

  const from = within(card).getByLabelText("Period from") as HTMLInputElement;
  fireEvent.change(from, { target: { value: "2026-04-02" } });
  expect(button.className).toContain("primary");
  fireEvent.click(within(card).getByRole("button", { name: "Cancel" }));
  expect(from.value).toBe("2026-04-01");

  fireEvent.change(from, { target: { value: "2026-04-03" } });
  fireEvent.click(within(card).getByRole("button", { name: "Save the scope" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith("wp-000000000264", expect.objectContaining({ period_start: "2026-04-03",
    expected_revision: 3 })));
});
