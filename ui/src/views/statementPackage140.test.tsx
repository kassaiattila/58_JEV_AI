// 140 (backlog F-package-kinds K3): the create form asks the goal first, then the source; a statement package is
// surveyed before it is made, and only the ticked statements and PDFs are sent; the package's page shows each item's
// statement. Synthetic names and made-up accounts only; the local service is replaced by spies. Expectations use the
// English interface; a separate check makes sure every new label has a Hungarian translation.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api, setActor, type OwnParty, type PartiesOverview, type PartyMonths, type StatementPackageSurvey, type StatementSurveyRow,
  type WorkflowTemplates, type WorkpackageView,
} from "../api";
import workflowConfig from "../../../configs/workflows.json";
import hungarian from "../i18n/hu-native.json";
import { setLanguage, t } from "../i18n";
import { reasonText } from "../labels";
import { defaultStatementPeriod, StatementPackageCreate } from "./StatementPackageCreate";
import { StatementPackagePanel } from "./StatementPackagePanel";
import { CreateForm } from "./Workpackages";

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
const row = (n: number, over: Partial<StatementSurveyRow> = {}): StatementSurveyRow => ({
  id: String(n).repeat(64), institution: "Erste", file: `2026060${n}_export.xml`, companion: null, title: `…6666 E ${n}/2026`,
  account: "…6666", currency: "HUF", period_start: `2026-0${n}-01`, period_end: `2026-0${n}-28`, lines: 4, checks_ok: true,
  balance_checked: true, rank: "code_checked", in_period: true, in_store: false, owner: "none", owner_party: null,
  replaces: [], replaced_by: null, conflicts: [], chosen: true, ...over,
});
const SURVEY: StatementPackageSurvey = {
  party: { id: PARTY.id, name: PARTY.name }, period_start: "2026-01-01", period_end: "2026-09-30",
  statements: [
    row(5, { rank: "code_checked", companion: "20260529_S.pdf",
      replaces: [{ id: "f".repeat(64), file: "old-may.json", period_start: "2026-05-01", period_end: "2026-05-31", rank: "unchecked", in_store: true }] }),
    row(6, { rank: "unchecked", balance_checked: false, checks_ok: false }),
    row(7, { in_store: true, chosen: false }),
  ],
  pdfs: [{ path: "C:\\statements\\other-bank.pdf", file: "other-bank.pdf", sha256: "a".repeat(64), in_store: false, statement: null, chosen: true }],
  skipped: [{ file: "notes.xml", reason: "no statement table of a known profile in the file" }],
};

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

describe("the create form asks the goal first", () => {
  // 146: the new work wizard - what the work is for, which work, then its own form
  it("offers documents, emails, bank statements and reconciliation step by step", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    vi.spyOn(api, "workflowTemplates").mockResolvedValue(workflowConfig as unknown as WorkflowTemplates);
    render(<CreateForm onDone={vi.fn()} />);
    expect((await screen.findByRole("radio", { name: "Documents and emails" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: "Bank statements and reconciliation" }));
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    expect((screen.getByRole("radio", { name: "Bank statements" }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("radio", { name: "Reconciliation of statements and invoices" })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: "Bank statement from a table" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Next →" }));
    expect(screen.getByRole("form", { name: "New statement package" })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: "Documents from a folder" })).toBeNull();
    await screen.findByText("Example Kft.");
    fireEvent.click(screen.getByRole("button", { name: "← Back" }));
    expect(screen.getByRole("radio", { name: "Reconciliation of statements and invoices" })).toBeTruthy();
  });
});

describe("a statement package is surveyed before it is made", () => {
  it("proposes the survey's ticks and sends only the ticked statements and PDFs", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    vi.spyOn(api, "partyMonths").mockResolvedValue(MONTHS);
    const survey = vi.spyOn(api, "statementPackageSurvey").mockResolvedValue(SURVEY);
    const create = vi.spyOn(api, "createStatementPackage").mockResolvedValue({ workpackage: { id: "wp-000000000001" } } as WorkpackageView);
    const done = vi.fn();
    render(<StatementPackageCreate onDone={done} />);
    const surveyButton = screen.getByRole("button", { name: "Survey the files" }) as HTMLButtonElement;
    expect(surveyButton.disabled).toBe(true); // no party, no folder yet
    fireEvent.click(await screen.findByRole("radio", { name: /Example Kft\./ }));
    fireEvent.change(screen.getByLabelText("The statements' folder"), { target: { value: "C:\\statements" } });
    const [start, end] = defaultStatementPeriod();
    fireEvent.click(screen.getByRole("button", { name: "Survey the files" }));
    const table = await screen.findByRole("table", { name: "Statements in the files" });
    expect(survey).toHaveBeenCalledWith({ paths: ["C:\\statements"], party_id: PARTY.id, period_start: start, period_end: end });
    expect(within(table).getByText("replaces 1 statement(s)")).toBeTruthy();
    expect(within(table).getByText("already in the store")).toBeTruthy();
    expect(within(table).getAllByText("goes to Example Kft.")).toHaveLength(3);
    expect(within(table).getByText("no PDF statement: a to-do in the run")).toBeTruthy();
    expect(screen.getByText("1 file(s) could not be read as a statement")).toBeTruthy();
    // the survey's ticks: May and June, not July (already in the store), and the PDF
    fireEvent.click(screen.getByRole("checkbox", { name: "Choose …6666 E 6/2026 (HUF), 2026-06-01 – 2026-06-28" }));
    fireEvent.click(screen.getByRole("button", { name: "Create with 1 statement(s) and 1 PDF(s)" }));
    await waitFor(() => expect(done).toHaveBeenCalledWith("wp-000000000001"));
    expect(create).toHaveBeenCalledWith({
      paths: ["C:\\statements"], party_id: PARTY.id, period_start: start, period_end: end,
      name: `Example Kft. statements ${start} – ${end}`, statements: ["5".repeat(64)], pdfs: ["C:\\statements\\other-bank.pdf"],
    });
  });

  it("drops the survey when what is surveyed changes", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(OVERVIEW);
    vi.spyOn(api, "partyMonths").mockResolvedValue(MONTHS);
    vi.spyOn(api, "statementPackageSurvey").mockResolvedValue(SURVEY);
    render(<StatementPackageCreate onDone={vi.fn()} />);
    fireEvent.click(await screen.findByRole("radio", { name: /Example Kft\./ }));
    fireEvent.change(screen.getByLabelText("The statements' folder"), { target: { value: "C:\\statements" } });
    fireEvent.click(screen.getByRole("button", { name: "Survey the files" }));
    await screen.findByRole("table", { name: "Statements in the files" });
    fireEvent.change(screen.getByLabelText("The statements' folder"), { target: { value: "C:\\other" } });
    expect(screen.queryByRole("table", { name: "Statements in the files" })).toBeNull();
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
