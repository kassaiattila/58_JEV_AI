// 133 (backlog F-own-parties; DECISIONS 133): a reconciliation package is one own party's. The pairing page lists the
// party's invoices and the unassigned ones, the other parties' ones with a switch or a search; the create form starts
// from the party; the settings page accepts the data's suggestions and rearranges the parties. Synthetic names only;
// the local service is replaced by spies. Expectations use the English interface; a separate test checks that every
// new label has a Hungarian translation.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api, setActor, type OwnParty, type PartiesOverview, type ReconcileInvoice, type ReconcileLine, type ReconcileWorkspace,
  type WorkpackageView,
} from "../../api";
import hungarian from "../../i18n/hu-native.json";
import { setLanguage, t } from "../../i18n";
import { SETTINGS_SECTIONS } from "../Settings";
import { PartiesPanel } from "../settings/PartiesPanel";
import { ReconcileCreate } from "./ReconcileCreate";
import { ReconcilePairing } from "./ReconcilePairing";

const WP = "wp-0000000000bb";
const STMT = "c".repeat(64);
const HOME = { id: "party-00000000000a", name: "Example Home" };
const CLUB = { id: "party-00000000000b", name: "Sporting Club" };
const lineId = (n: number) => `${STMT.slice(0, 16)}:${String(n).padStart(12, "0")}:0`;
const invId = (n: number) => String(n).repeat(64).slice(0, 64);

const line = (n: number, over: Partial<ReconcileLine> = {}): ReconcileLine => ({
  id: lineId(n), statement_id: STMT, account: "acct-1", statement_type: "bank_account", currency: "HUF",
  booking_date: `2026-04-${String(10 + n).padStart(2, "0")}`, direction: "debit", amount: "100.00", counterparty_name: `Example Payee ${n}`,
  counterparty_account: null, description: "Transfer", memo: `INV-000${n}`, state: "open", excluded_reason: null, allocated: "0",
  rest: "100.00", mark: null, allocations: [], candidates: [], rejected: [], statement_verified: true, file: "statement.pdf",
  other_candidates: [], ...over,
});
const invoice = (n: number, over: Partial<ReconcileInvoice> = {}): ReconcileInvoice => ({
  id: invId(n), doc_type: "invoice_hu", number: `INV-000${n}`, supplier_name: `Example Supplier ${n}`, amount: "100.00", currency: "HUF",
  issue_date: "2026-04-01", due_date: "2026-04-15", payment_method: null, file: `invoice-${n}.pdf`, state: "no_payment_found",
  allocated: "0", rest: "100.00", allocations: [], candidates: [], source: "approved", party: { ...HOME, how: "name" }, own: true, ...over,
});
const workspace = (lines: ReconcileLine[], invoices: ReconcileInvoice[]): ReconcileWorkspace => ({
  workpackage_id: WP, lines, invoices, coverage: [], blockers: [], line_marks: ["private", "other"], open: {},
  counts: { lines: {}, invoices: {}, open_lines: lines.length, other_invoices: invoices.filter((i) => i.own === false).length },
  learned_names: [], fx_tolerance: null, engine_version: "1.4.0", config_hash: "x",
  scope: { workpackage_id: WP, accounts: ["acct-1"], period_start: "2026-04-01", period_end: "2026-04-30", revision: 1, updated_at: "",
    party_id: HOME.id, party: HOME },
});

const party = (over: Partial<OwnParty>): OwnParty => ({
  id: HOME.id, name: HOME.name, invoices: 3, first: "2026-04-01", last: "2026-06-01", statements_first: "2026-04-01",
  statements_last: "2026-08-31", accounts: [{ key: "acct-1", label: "1111-2222", statements: 4, first: "2026-04-01", last: "2026-08-31",
    statement_types: ["bank_account"], currencies: ["HUF"] }],
  identities: [{ kind: "name", key: "example jane", label: "Jane Example", invoices: 3 },
    { kind: "account", key: "acct-1", label: "1111-2222", invoices: 4 }], updated_at: "", ...over,
});
const overview = (over: Partial<PartiesOverview> = {}): PartiesOverview => ({
  parties: [], suggestions: [], unassigned: [], dismissed: [], invoices: 10, unclaimed_invoices: 10, ambiguous_invoices: 0,
  buyer_is_supplier: 0, no_buyer: 0, config_hash: "x", ...over,
});

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

// --- the pairing page ----------------------------------------------------------------------------------------------------

describe("the pairing page of a party's package", () => {
  const club = invoice(2, { supplier_name: "Club Supplier", party: { ...CLUB, how: "tax" }, own: false, amount: "250.00", rest: "250.00" });
  const nobody = invoice(3, { supplier_name: "Nobody's Supplier", party: null, own: true });

  it("lists the party's and the unassigned invoices, the other parties' ones with the switch", () => {
    render(<ReconcilePairing ws={workspace([line(1)], [invoice(1), club, nobody])} readOnly={false} onWorkspace={vi.fn()} reload={() => {}} />);
    const pane = screen.getByRole("region", { name: "Invoices" });
    expect(within(pane).getByRole("heading", { name: "Invoices of Example Home" })).toBeTruthy();
    expect(within(pane).queryByText(/Club Supplier/)).toBeNull();
    expect(within(pane).getByText(/Nobody's Supplier/)).toBeTruthy();
    expect(within(pane).getByText("no own party")).toBeTruthy();
    fireEvent.click(within(pane).getByRole("checkbox", { name: /Other parties' invoices too \(1\)/ }));
    expect(within(pane).getByText(/Club Supplier/)).toBeTruthy();
    expect(within(pane).getByText("Other party: Sporting Club")).toBeTruthy();
  });

  it("finds another party's invoice by a search, and says when the selected line has a candidate there", () => {
    const busy = line(1, { other_candidates: [{ invoice_id: club.id, party: CLUB.name }] });
    render(<ReconcilePairing ws={workspace([busy], [invoice(1), club])} readOnly={false} onWorkspace={vi.fn()} reload={() => {}} />);
    const pane = screen.getByRole("region", { name: "Invoices" });
    expect(within(pane).getByText("1 candidate(s) among other parties' invoices: Sporting Club")).toBeTruthy();
    fireEvent.change(within(pane).getByRole("searchbox", { name: "Search the invoices" }), { target: { value: "Club" } });
    expect(within(pane).getByText(/Club Supplier/)).toBeTruthy();
    fireEvent.change(within(pane).getByRole("searchbox", { name: "Search the invoices" }), { target: { value: "" } });
    expect(within(pane).queryByText(/Club Supplier/)).toBeNull();
    fireEvent.click(within(pane).getByRole("button", { name: "Show them" }));
    expect(within(pane).getByText(/Club Supplier/)).toBeTruthy();
  });
});

// --- the create form -----------------------------------------------------------------------------------------------------

describe("a new package starts from its own party", () => {
  it("checks the party's accounts, takes its statements' span and sends the party", async () => {
    const parties = overview({ parties: [party({}), party({ ...CLUB, accounts: [], statements_first: null, statements_last: null })] });
    vi.spyOn(api, "parties").mockResolvedValue(parties);
    vi.spyOn(api, "reconcileAccounts").mockResolvedValue({ accounts: [
      { key: "acct-1", account: "1111-2222", statement_types: ["bank_account"], currencies: ["HUF"], statements: 4, first: "2026-04-01", last: "2026-08-31", party: HOME },
      { key: "acct-2", account: "3333-4444", statement_types: ["credit_card"], currencies: ["HUF"], statements: 1, first: "2026-05-01", last: "2026-05-31", party: null },
    ] });
    const create = vi.spyOn(api, "createReconcilePackage").mockResolvedValue({ workpackage: { id: WP } } as unknown as WorkpackageView);
    const done = vi.fn();
    render(<ReconcileCreate onDone={done} />);
    const home = await screen.findByRole("radio", { name: /Example Home/ });
    expect((screen.getByRole("radio", { name: /Sporting Club/ }) as HTMLInputElement).disabled).toBe(true); // no statement yet
    expect((screen.getByRole("button", { name: "Create" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(home);
    expect((screen.getByRole("checkbox", { name: /1111-2222/ }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("checkbox", { name: /3333-4444/ }) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByLabelText("Period from") as HTMLInputElement).value).toBe("2026-04-01");
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(done).toHaveBeenCalledWith(WP));
    expect(create).toHaveBeenCalledWith({ name: "Example Home · 2026-04-01 – 2026-08-31", accounts: ["acct-1"],
      period_start: "2026-04-01", period_end: "2026-08-31", party_id: HOME.id });
  });

  it("without any own party it points to the settings", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(overview());
    vi.spyOn(api, "reconcileAccounts").mockResolvedValue({ accounts: [] });
    render(<ReconcileCreate onDone={vi.fn()} />);
    expect(await screen.findByRole("link", { name: "Settings › Own parties" })).toBeTruthy();
  });
});

// --- the settings page ---------------------------------------------------------------------------------------------------

describe("the own parties in the settings", () => {
  const suggestion = (id: string, name: string, n: number) => ({
    id, party_id: null, name, invoices: n, identities: [{ kind: "name" as const, key: name.toLowerCase(), label: name, invoices: n }],
  });

  it("accepts every suggestion with the names a person gave", async () => {
    vi.spyOn(api, "parties").mockResolvedValue(overview({ suggestions: [suggestion("a".repeat(16), "Jane Example", 3), suggestion("b".repeat(16), "City Transport", 2)] }));
    const accept = vi.spyOn(api, "acceptPartySuggestions").mockResolvedValue(overview({ parties: [party({})] }));
    render(<PartiesPanel />);
    const name = await screen.findByDisplayValue("Jane Example");
    fireEvent.change(name, { target: { value: "Example Home" } });
    const all = screen.getByRole("button", { name: "Accept all 2" });
    fireEvent.click(all);
    fireEvent.click(all); // a second click confirms
    await waitFor(() => expect(accept).toHaveBeenCalledWith(["a".repeat(16), "b".repeat(16)], { ["a".repeat(16)]: "Example Home" }));
    expect(await screen.findByRole("region", { name: "Example Home" })).toBeTruthy();
  });

  it("moves an identity to another party and dismisses an unassigned one", async () => {
    const club = party({ ...CLUB, accounts: [], identities: [{ kind: "tax", key: "domestic:13570008", label: "13570008-1-13", invoices: 2 }] });
    const lonely = { kind: "name" as const, key: "lonely name", label: "Lonely Name Bt.", invoices: 1 };
    vi.spyOn(api, "parties").mockResolvedValue(overview({ parties: [party({}), club], unassigned: [lonely] }));
    const set = vi.spyOn(api, "setPartyIdentity").mockResolvedValue(overview({ parties: [party({}), club], unassigned: [lonely] }));
    render(<PartiesPanel />);
    const card = await screen.findByRole("region", { name: "Sporting Club" });
    fireEvent.change(within(card).getByRole("combobox", { name: "Move 13570008-1-13" }), { target: { value: HOME.id } });
    fireEvent.click(within(card).getByRole("button", { name: "Move" }));
    await waitFor(() => expect(set).toHaveBeenCalledWith(club.identities[0], "assign", HOME.id));
    set.mockClear();
    const unassigned = screen.getByRole("region", { name: "Unassigned" });
    const notOwn = within(unassigned).getByRole("button", { name: "Not own" });
    fireEvent.click(notOwn);
    fireEvent.click(notOwn);
    await waitFor(() => expect(set).toHaveBeenCalledWith(lonely, "dismiss"));
  });
});

// --- every new label has a Hungarian translation ----------------------------------------------------------------------------

describe("the Hungarian interface of the own parties", () => {
  it("has a translation for every label of the settings page and the menu", async () => {
    const sources = import.meta.glob<string>(["../settings/PartiesPanel.tsx"], { eager: true, query: "?raw", import: "default" });
    const keys = new Set<string>();
    for (const src of Object.values(sources)) {
      for (const m of src.matchAll(/\bt\(\s*"((?:[^"\\]|\\.)*)"/g)) keys.add(JSON.parse(`"${m[1]}"`));
      for (const block of src.matchAll(/tmap\(\{([\s\S]*?)\}\)/g)) for (const m of block[1].matchAll(/:\s*"((?:[^"\\]|\\.)*)"/g)) keys.add(JSON.parse(`"${m[1]}"`));
    }
    const section = SETTINGS_SECTIONS.find((s) => s.key === "parties")!;
    keys.add(section.label);
    keys.add(section.hint);
    const missing = [...keys].filter((k) => !(k in (hungarian as Record<string, string>)));
    expect(keys.size).toBeGreaterThan(30);
    expect(missing).toEqual([]);
    await setLanguage("hu");
    expect(t(section.label)).toBe("Saj\u00e1t gazd\u00e1lkod\u00f3k");
  });
});
