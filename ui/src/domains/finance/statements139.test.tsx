// 139 (DECISIONS 139): one valid statement per account and day in the interface - the review page's panel of the
// statements of the same days, the month grid's note of a replaced statement, and the reconciliation package's list of
// the decisions not carried over. Synthetic names only; the local service is replaced by spies. Expectations use the
// English interface; the last test checks that every new label has a Hungarian translation.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type ItemResult } from "../../api";
import type { PartyMonths, ReconcileWorkspace, StatementRelation } from "./api";
import hungarian from "../../i18n/hu-native.json";
import { setLanguage } from "../../i18n";
import { ReconcilePrepare } from "./reconcile/ReconcileStages";
import { MonthGrid } from "./MonthStatus";
import { StatementPanel } from "./StatementPanel";

const OTHER = "b".repeat(64);
const relation = (over: Partial<StatementRelation> = {}): StatementRelation => ({
  other_doc_id: OTHER, other_file: "export-2026-04.json", relation: "conflict", how: null, other_run_id: "run-000000000002",
  other_item_id: OTHER, other_workpackage_id: "wp-000000000002", period: ["2026-04-01", "2026-04-30"],
  other_period: ["2026-04-01", "2026-04-30"], rank: "code_checked", other_rank: "code_checked", lines: 12, other_lines: 13,
  carried: null, left_over: null, reason_id: 7, kept: null, decided_by: null, decided_at: null, decision_state: 5, ...over,
});
const result = (statements: StatementRelation[]) => ({ run_id: "run-000000000001", item_id: "a".repeat(64), statements }) as unknown as ItemResult;

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

describe("the statements of the same days on the review page", () => {
  it("asks which one is valid and sends the choice", async () => {
    const choose = vi.spyOn(api, "chooseStatement").mockResolvedValue(result([]));
    const onDecided = vi.fn();
    render(<StatementPanel result={result([relation()])} readOnly={false} onDecided={onDecided} />);
    expect(screen.getByText("Another statement books the same days of this account: which one is valid?")).toBeTruthy();
    expect(screen.getByText("Until a person chooses, both count and their lines may be counted twice.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "export-2026-04.json" }).getAttribute("href")).toBe(`#/workpackages/wp-000000000002/review/${OTHER}`);
    expect(screen.queryByRole("button", { name: "By the rule" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "The other one is valid" }));
    await waitFor(() => expect(onDecided).toHaveBeenCalled());
    expect(choose).toHaveBeenCalledWith("run-000000000001", "a".repeat(64), OTHER, "other", 5);  // 187: the state it read
  });

  it("says what replaced the statement, how many lines carried over, and offers the rule back after a choice", () => {
    const { rerender } = render(<StatementPanel result={result([relation({ relation: "replaced_by", how: "rule", rank: "unchecked",
      carried: 11, left_over: 1, reason_id: null })])} readOnly={false} onDecided={() => {}} />);
    expect(screen.getByText("This statement is replaced: another statement of the same days is the valid one")).toBeTruthy();
    expect(screen.getByText(/the decisions on 1 lines have to be made again/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "The other one is valid" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("balances not checked")).toBeTruthy();
    rerender(<StatementPanel result={result([relation({ relation: "replaces", how: "person", decided_by: "Synthetic reviewer",
      carried: 13, left_over: 0, kept: "a".repeat(64) })])} readOnly={false} onDecided={() => {}} />);
    expect(screen.getByText(/Chosen by Synthetic reviewer\./)).toBeTruthy();
    expect(screen.getByRole("button", { name: "By the rule" })).toBeTruthy();
  });

  it("shows nothing for a document without such a statement, and no buttons when read only", () => {
    const { container } = render(<StatementPanel result={result([])} readOnly={false} onDecided={() => {}} />);
    expect(container.innerHTML).toBe("");
    render(<StatementPanel result={result([relation()])} readOnly onDecided={() => {}} />);
    expect(screen.queryByRole("button", { name: "This one is valid" })).toBeNull();
  });
});

it("the month grid notes a replaced statement of the month", () => {
  const data: PartyMonths = {
    party: { id: "party-00000000000a", name: "Example Home" }, start: "2026-04", end: "2026-04", months: ["2026-04"], today: "2026-10-10",
    columns: [{ key: "222233344444555566667777", currency: "HUF", label: "22223334-44445555-66667777", kind: "account", bank: "Example Bank",
      registered: true, opened: null, closed: null, statements: 1,
      months: [{ month: "2026-04", state: "ok", statements: 1, flags: [], replaced: ["c".repeat(64)] }] }],
    invoices: [{ month: "2026-04", total: 0, approved: 0, not_approved: 0, no_run: 0 }],
    summary: { ok: 1, unapproved: 0, unverified: 0, partial: 0, missing: 0, overlap: 0, break: 0 },
  };
  render(<MonthGrid data={data} />);
  expect(screen.getByText("1 replaced").getAttribute("title")).toBe("1 statements of this month were replaced by a better one and are left out.");
});

it("the reconciliation package lists the decisions not carried over and revokes one", async () => {
  vi.spyOn(api, "reconcileAccounts").mockResolvedValue({ accounts: [] } as never);
  vi.spyOn(api, "parties").mockResolvedValue({ parties: [], suggestions: [], unassigned: [], dismissed: [] } as never);
  const ws = {
    workpackage_id: "wp-000000000003", lines: [], invoices: [], coverage: [], line_marks: ["fee"], open: {},
    blockers: [{ code: "decision_not_carried", doc_id: "d".repeat(64), file: "old.pdf", kind: "statement" }],
    left_over: [{ kind: "mark", ref: "7", line_id: "dddd:x:0", statement_id: "d".repeat(64), replaced_by: "e".repeat(64),
      invoice_id: null, category: "fee", decision: null, workpackage_id: "wp-000000000003", currency: "HUF",
      booking_date: "2026-04-20", amount: "50.00", direction: "debit", counterparty_name: "Example Bank", file: "old.pdf",
      replaced_by_file: "new.json", invoice_file: null }],
    counts: { lines: {}, invoices: {}, open_lines: 0 }, learned_names: [], fx_tolerance: null, engine_version: "1.8.0", config_hash: "x",
    scope: { workpackage_id: "wp-000000000003", accounts: [], period_start: "2026-04-01", period_end: "2026-04-30", revision: 1, updated_at: "" },
  } as unknown as ReconcileWorkspace;
  const revoke = vi.spyOn(api, "reconcileRevoke").mockResolvedValue({ ...ws, left_over: [], blockers: [] });
  render(<ReconcilePrepare ws={ws} readOnly={false} onWorkspace={() => {}} reload={() => {}} />);
  const section = screen.getByRole("region", { name: "Decisions not carried over" });
  expect(within(section).getByText("2026-04-20 · Example Bank · −50.00 HUF")).toBeTruthy();
  expect(within(section).getByText("needs no invoice (Bank fee or interest)")).toBeTruthy();
  expect(screen.getByText("A decision on a replaced statement's line has no same line on the valid statement: old.pdf")).toBeTruthy();
  fireEvent.click(within(section).getByRole("button", { name: "Revoke" }));
  await waitFor(() => expect(revoke).toHaveBeenCalledWith("wp-000000000003", "mark", "7"));
});

it("every new label has a Hungarian translation", () => {
  const hu = hungarian as Record<string, string>;
  for (const key of ["Another statement books the same days of this account: which one is valid?", "This one is valid",
    "The other one is valid", "By the rule", "Decisions not carried over", "{{n}} replaced", "Revoke",
    "Another statement books the same days of this account: choose the valid one",
    "A decision on a replaced statement's line has no same line on the valid statement: {{name}}"]) {
    expect(hu[key], key).toBeTruthy();
    expect(hu[key]).not.toBe(key);
  }
});
