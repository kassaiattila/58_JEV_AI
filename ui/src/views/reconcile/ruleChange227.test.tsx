// 227 (backlog Q-reconcile-rule-fingerprint; DECISIONS 224, the owner's choice "only a change of content warns"): an
// approved reconciliation warns only when its content changed; a change of its rules alone is a note. The service
// says which (`since_approval`); an older service without it compares the fingerprints, as before. Synthetic data only;
// the service is spied on.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api, setActor, type ReconcileStatement, type ReconcileStatementCurrent, type ReconcileVersionMeta, type ReconcileWorkspace,
} from "../../api";
import { setLanguage } from "../../i18n";
import { ReconcileResult } from "./ReconcileResult";

const WP = "wp-0000000000fe";
const FP = "f".repeat(64);
const statement: ReconcileStatement = {
  format: 1, package: { id: WP, name: "April" }, party: "Example Home", period: ["2026-04-01", "2026-04-30"], accounts: ["A"],
  invoices: [], lines: [], warnings: [], counts: { invoices: {}, lines: {}, open_lines: 0 },
};
const v1: ReconcileVersionMeta = {
  version: 1, fingerprint: FP, approved_by: "Synthetic reviewer", approved_at: "2026-10-11T10:00:00+00:00",
  reopened_by: null, reopened_at: null, reopen_note: null,
};
const ws = { workpackage_id: WP, blockers: [], decision_state: [[0]] } as unknown as ReconcileWorkspace;
const CHANGED = /The data has changed since the approval/;
const NOTE = /rules or the program that applies them changed since the approval/;

function approved(over: Partial<ReconcileStatementCurrent>) {
  vi.spyOn(api, "reconcileStatement").mockResolvedValue({
    statement, fingerprint: "0".repeat(64), blockers: [], warnings: [], approval: { active: v1, versions: [v1] }, ...over,
  });
  vi.spyOn(api, "reconcileStatementVersion").mockResolvedValue({ ...v1, statement });
  render(<ReconcileResult ws={ws} archived={false} onChanged={vi.fn()} reloadWorkspace={vi.fn()} />);
}

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

describe("what changed since a reconciliation's approval (227)", () => {
  it("only notes a change of the rules when the content is the same", async () => {
    approved({ since_approval: { content_changed: false, rules_changed: true } });
    expect(await screen.findByText(/Approved: version 1/)).toBeTruthy();
    expect(screen.getByText(NOTE)).toBeTruthy();
    expect(screen.queryByText(CHANGED)).toBeNull(); // the fingerprints differ, the content does not
  });

  it("warns on a change of the content, and the note gives way to it", async () => {
    approved({ since_approval: { content_changed: true, rules_changed: true } });
    expect(await screen.findByText(CHANGED)).toBeTruthy();
    expect(screen.queryByText(NOTE)).toBeNull();
  });

  it("says nothing when neither changed", async () => {
    approved({ fingerprint: FP, since_approval: { content_changed: false, rules_changed: false } });
    expect(await screen.findByText(/Approved: version 1/)).toBeTruthy();
    expect(screen.queryByText(CHANGED)).toBeNull();
    expect(screen.queryByText(NOTE)).toBeNull();
  });

  it("compares the fingerprints when an older service does not say", async () => {
    approved({});
    expect(await screen.findByText(CHANGED)).toBeTruthy();
    expect(screen.queryByText(NOTE)).toBeNull();
  });
});
