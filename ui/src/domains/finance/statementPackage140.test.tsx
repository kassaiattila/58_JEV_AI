// 140 (backlog F-package-kinds K3): the create form asks the goal first, then the source (231 C3b3: the bank
// statements' process pack's general form; C3b5a: the statement package's own form went, with its survey's tests); the
// package's page shows each item's statement. Synthetic names and made-up accounts only; the local service is replaced by spies. Expectations use the
// English interface; a separate check makes sure every new label has a Hungarian translation.
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type OwnParty, type PartiesOverview, type WorkflowTemplates } from "../../api";
import type { PartyMonths } from "./api";
import workflowConfig from "../../views/workflows/workflowTemplates181.fixture.json";  // 181: the service's templates
import hungarian from "../../i18n/hu-native.json";
import { setLanguage, t } from "../../i18n";
import { reasonText } from "../../labels";
import { StatementPackagePanel } from "./StatementPackagePanel";
import { CreateForm } from "../../views/Workpackages";

const PARTY: OwnParty = {
  id: "party-00000000000a", name: "Example Kft.", invoices: 0, first: null, last: null, statements_first: null,
  statements_last: null, accounts: [], identities: [], updated_at: "",
};
const OVERVIEW: PartiesOverview = {
  parties: [PARTY], suggestions: [], unassigned: [], dismissed: [], invoices: 0, unclaimed_invoices: 0, ambiguous_invoices: 0,
  buyer_is_supplier: 0, no_buyer: 0, config_hash: "x",
};
const MONTHS: PartyMonths = {
  party: { id: PARTY.id, name: PARTY.name }, start: "2026-01", end: "2026-09", months: [], today: "2026-10-10", columns: [],
  invoices: [], summary: { ok: 0, unapproved: 0, unverified: 0, partial: 0, missing: 0, overlap: 0, break: 0 },
};
beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

describe("the create form asks the goal first", () => {
  // 146: the new work wizard - what the work is for, which work, then its own form
  it("offers documents, emails, bank statements and reconciliation step by step", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    vi.spyOn(api, "workflowTemplates").mockResolvedValue(workflowConfig as unknown as WorkflowTemplates);
    // 231 (C3b3): the bank statements' template starts its process pack's case with the general form
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [{ id: "bank_statements", title: "Bank statements", version: "1.0.0",
      scope: ["party", "period", "source"], asks: ["party", "period", "source"], package_kinds: [] }] });
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
    render(<CreateForm onDone={vi.fn()} />);
    expect((await screen.findByRole("radio", { name: "Documents and emails" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: "Bank statements and reconciliation" }));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    expect((screen.getByRole("radio", { name: "Bank statements" }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("radio", { name: "Reconciliation of statements and invoices" })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: "Bank statement from a table" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    expect(await screen.findByRole("form", { name: "Bank statements" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Documents from a folder" })).toBeTruthy();  // the case's source
    await screen.findByRole("option", { name: "Example Kft." });
    fireEvent.click(screen.getByRole("button", { name: "← Back" }));
    expect(screen.getByRole("radio", { name: "Reconciliation of statements and invoices" })).toBeTruthy();
  });
});

describe("the package's page and its to-dos", () => {
  it("shows each item's statement state and the party's months", async () => {
    vi.spyOn(api, "partyMonths").mockResolvedValue(MONTHS);
    render(<StatementPackagePanel view={{
      scope: { workpackage_id: "wp-1", party_id: PARTY.id, party: { id: PARTY.id, name: PARTY.name }, period_start: "2026-01-01",
        period_end: "2026-09-30", revision: 1 },
      statements: [
        { item_id: "1", kind: "statement_table", file: "may.json", state: "valid", account: "…6666", currency: "HUF",
          period_start: "2026-05-01", period_end: "2026-05-31", rank: "code_checked" },
        { item_id: "2", kind: "document", file: "other-bank.pdf", state: "pending" },
      ],
    }} />);
    expect(screen.getByText("1 valid, 0 replaced, 0 to choose, 1 without a statement yet")).toBeTruthy();
    expect(screen.getByText("no statement from it yet")).toBeTruthy();
    await screen.findByText("The party has no account or card yet: its first statements will bring them.");
  });

  it("names the statement package's to-dos in plain words", () => {
    expect(reasonText("statements:not_a_statement:invoice_hu")).toMatch(/^This PDF is not a bank statement/);
    expect(reasonText("statements:other_party:party-00000000000b")).toMatch(/another own party/);
  });

  it("has a Hungarian translation for every new label", () => {
    const labels = ["What is the package for?", "Bank statements", "Survey the files", "Statements of the package",
      "goes to {{party}}", "replaces {{n}} statement(s)", "no statement from it yet"];
    for (const label of labels) expect((hungarian as Record<string, string>)[label], label).toBeTruthy();
    expect(t("Bank statements")).toBe("Bank statements");
  });
});
