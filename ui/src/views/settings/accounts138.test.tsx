// 138 (DECISIONS 137, 138): an own account or card registered with its party in advance, and the party's data status
// month by month - on the settings page and before a new reconciliation package, where a gap warns but does not stop.
// Synthetic names and made-up account numbers only; the local service is replaced by spies. Expectations use the
// English interface; the last test checks that every new label has a Hungarian translation.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api, setActor, type MonthCell, type OwnParty, type PartiesOverview, type PartyMonths, type WorkpackageView,
} from "../../api";
import hungarian from "../../i18n/hu-native.json";
import { setLanguage } from "../../i18n";
import { ReconcileCreate } from "../reconcile/ReconcileCreate";
import { columnLabel, MonthGrid, monthWarnings } from "./MonthStatus";
import { PartiesPanel } from "./PartiesPanel";

const HOME = { id: "party-00000000000a", name: "Example Home" };
const KEY = "222233344444555566667777";
const NUMBER = "22223334-44445555-66667777";

const cell = (month: string, state: MonthCell["state"], over: Partial<MonthCell> = {}): MonthCell =>
  ({ month, state, statements: state === "missing" || state === "none" ? 0 : 1, flags: [], ...over });
const months = (over: Partial<PartyMonths> = {}): PartyMonths => ({
  party: HOME, start: "2026-01", end: "2026-03", months: ["2026-01", "2026-02", "2026-03"], today: "2026-10-10",
  columns: [{ key: KEY, currency: "HUF", label: NUMBER, kind: "account", bank: "Example Bank", registered: true,
    opened: "2026-01-01", closed: null, statements: 2,
    months: [cell("2026-01", "ok"), cell("2026-02", "unapproved", { flags: ["break"] }), cell("2026-03", "missing")] }],
  invoices: [{ month: "2026-01", total: 3, approved: 3, not_approved: 0, no_run: 0 },
    { month: "2026-02", total: 2, approved: 0, not_approved: 1, no_run: 1 }, { month: "2026-03", total: 0, approved: 0, not_approved: 0, no_run: 0 }],
  summary: { ok: 1, unapproved: 1, unverified: 0, partial: 0, missing: 1, overlap: 0, break: 1 }, ...over,
});
const party = (over: Partial<OwnParty> = {}): OwnParty => ({
  id: HOME.id, name: HOME.name, invoices: 5, first: "2026-01-05", last: "2026-02-20", statements_first: null, statements_last: null,
  accounts: [{ key: KEY, label: NUMBER, statements: 0, first: null, last: null, statement_types: [], currencies: ["HUF"],
    registered: { kind: "account", bank: "Example Bank", currencies: ["HUF"], valid_from: "2026-01-01", valid_to: null } }],
  identities: [{ kind: "account", key: KEY, label: NUMBER, invoices: 0 }], updated_at: "", ...over,
});
const overview = (over: Partial<PartiesOverview> = {}): PartiesOverview => ({
  parties: [party()], suggestions: [], unassigned: [], dismissed: [], invoices: 5, unclaimed_invoices: 0, ambiguous_invoices: 0,
  buyer_is_supplier: 0, no_buyer: 0, config_hash: "x", ...over,
});

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

describe("the monthly data status", () => {
  it("shows each month of each account, its flags and the month's invoices", () => {
    render(<MonthGrid data={months()} />);
    const grid = screen.getByRole("table", { name: "Data status by month" });
    expect(within(grid).getByRole("columnheader", { name: "Example Bank …7777 HUF" })).toBeTruthy();
    const feb = within(grid).getByRole("row", { name: /2026-02/ });
    expect(within(feb).getByText("Awaiting approval")).toBeTruthy();
    expect(within(feb).getByText("balance break")).toBeTruthy();
    expect(within(feb).getByText(/2 not approved/)).toBeTruthy();
    expect(within(within(grid).getByRole("row", { name: /2026-03/ })).getByText("No statement")).toBeTruthy();
  });

  it("says what the chosen accounts lack, and nothing for another account", () => {
    const warnings = monthWarnings(months());
    expect(warnings).toHaveLength(3);
    expect(warnings[0]).toMatch(/^1 months of an account have no statement/);
    expect(monthWarnings(months(), ["another-account"])).toEqual([]);
    expect(columnLabel({ bank: null, label: "LT12 3456", currency: "EUR" })).toBe("LT12 3456 EUR");
  });
});

describe("an account registered on the settings page", () => {
  it("registers a new account by its number with its details", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(overview({ parties: [party({ accounts: [], identities: [] })] }));
    const register = vi.spyOn(api, "registerPartyAccount").mockResolvedValue(overview());
    render(<PartiesPanel />);
    const card = await screen.findByRole("region", { name: "Example Home" });
    fireEvent.click(within(card).getByRole("button", { name: "Register a bank account or card" }));
    const form = within(card).getByRole("form", { name: "New account or card" });
    fireEvent.change(within(form).getByLabelText("Account number (IBAN or domestic)"), { target: { value: NUMBER } });
    fireEvent.change(within(form).getByLabelText(/Bank/), { target: { value: "Example Bank" } });
    fireEvent.change(within(form).getByLabelText("Currencies"), { target: { value: "huf, eur" } });
    fireEvent.change(within(form).getByLabelText(/Opened/), { target: { value: "2026-01-01" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(register).toHaveBeenCalledWith(HOME.id, NUMBER,
      { kind: "account", currencies: ["HUF", "EUR"], bank: "Example Bank", valid_from: "2026-01-01", valid_to: null }));
    expect(await screen.findByText("The account has been registered.")).toBeTruthy();
  });

  it("shows a registered account's details and edits them", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(overview());
    const set = vi.spyOn(api, "setPartyAccount").mockResolvedValue(overview());
    render(<PartiesPanel />);
    const card = await screen.findByRole("region", { name: "Example Home" });
    expect(within(card).getByText("Bank account · Example Bank · HUF · 2026-01-01 – …")).toBeTruthy();
    expect(within(card).getAllByText("no statement yet").length).toBeGreaterThan(0);
    fireEvent.click(within(card).getByRole("button", { name: "Details" }));
    const form = within(card).getByRole("form", { name: `Details of ${NUMBER}` });
    fireEvent.change(within(form).getByLabelText("Kind"), { target: { value: "card" } });
    fireEvent.change(within(form).getByLabelText(/Closed/), { target: { value: "2025-12-31" } });
    expect(within(form).getByText("The account is closed before it was opened.")).toBeTruthy();
    expect((within(form).getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(form).getByLabelText(/Closed/), { target: { value: "2026-06-30" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(set).toHaveBeenCalledWith(KEY,
      { kind: "card", currencies: ["HUF"], bank: "Example Bank", valid_from: "2026-01-01", valid_to: "2026-06-30" }));
  });

  it("folds the party's months open on request", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(overview());
    const load = vi.spyOn(api, "partyMonths").mockResolvedValue(months());
    render(<PartiesPanel />);
    const card = await screen.findByRole("region", { name: "Example Home" });
    expect(load).not.toHaveBeenCalled();
    const details = within(card).getByText("Data status by month").closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(await within(card).findByRole("table", { name: "Data status by month" })).toBeTruthy();
    expect(load).toHaveBeenCalledWith(HOME.id, expect.stringMatching(/^\d{4}-01$/), expect.stringMatching(/^\d{4}-\d{2}$/));
  });
});

describe("a new reconciliation package with a registered account", () => {
  it("chooses an account without a statement and warns about the months it lacks, without stopping", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(overview());
    vi.spyOn(api, "reconcileAccounts").mockResolvedValue({ accounts: [
      { key: KEY, account: NUMBER, statement_types: [], currencies: ["HUF"], statements: 0, first: null, last: null, party: HOME,
        registered: { kind: "account", bank: "Example Bank", currencies: ["HUF"], valid_from: "2026-01-01", valid_to: null, label: NUMBER } },
    ] });
    const load = vi.spyOn(api, "partyMonths").mockResolvedValue(months());
    const create = vi.spyOn(api, "createReconcilePackage").mockResolvedValue({ workpackage: { id: "wp-0000000000cc" } } as unknown as WorkpackageView);
    render(<ReconcileCreate onDone={vi.fn()} />);
    const home = await screen.findByRole("radio", { name: /Example Home/ });
    expect(screen.getByText(/1 accounts or cards, no statement yet/)).toBeTruthy();
    fireEvent.click(home);
    expect((screen.getByRole("checkbox", { name: /registered, no statement yet/ }) as HTMLInputElement).checked).toBe(true);
    fireEvent.change(screen.getByLabelText("Period from"), { target: { value: "2026-01-01" } });
    fireEvent.change(screen.getByLabelText("to"), { target: { value: "2026-03-31" } });
    const preview = await screen.findByRole("region", { name: "Data status of the period" });
    expect(within(preview).getByText(/have no statement: their invoices will show/)).toBeTruthy();
    expect(within(preview).getByText("The package can be created; the gaps show in its result.")).toBeTruthy();
    expect(load).toHaveBeenLastCalledWith(HOME.id, "2026-01", "2026-03");
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({ accounts: [KEY], party_id: HOME.id })));
  });
});

describe("the Hungarian interface of the registered accounts", () => {
  it("has a translation for every new label", () => {
    const sources = import.meta.glob<string>(["./MonthStatus.tsx", "./PartiesPanel.tsx", "../reconcile/ReconcileCreate.tsx"],
      { eager: true, query: "?raw", import: "default" });
    const keys = new Set<string>();
    for (const src of Object.values(sources)) {
      for (const m of src.matchAll(/\bt\(\s*"((?:[^"\\]|\\.)*)"/g)) keys.add(JSON.parse(`"${m[1]}"`));
      for (const block of src.matchAll(/tmap\(\{([\s\S]*?)\}\)/g)) for (const m of block[1].matchAll(/:\s*"((?:[^"\\]|\\.)*)"/g)) keys.add(JSON.parse(`"${m[1]}"`));
    }
    const missing = [...keys].filter((k) => !(k in (hungarian as Record<string, string>)));
    expect(keys.size).toBeGreaterThan(60);
    expect(missing).toEqual([]);
  });
});
