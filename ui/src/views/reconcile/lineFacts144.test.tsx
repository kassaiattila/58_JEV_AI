// 144 (DECISIONS 144): a statement line's facts wherever a person pairs — labelled in the finder's pinned line, on the
// card without the statement's file name — and the documents' statement pane: the line's facts, the bank's PDF behind a
// statement read by code with the line framed, or the statement as read when there is no PDF. Synthetic lines only; the
// local service is replaced by spies. Expectations use the English interface.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type ReconcileInvoice, type ReconcileLine, type ReconcileLocation, type ReconcileWorkspace } from "../../api";
import { setLanguage } from "../../i18n";
import { DocumentPair } from "./DocumentPair";
import { LineFacts } from "./LineFacts";
import { ReconcilePairing } from "./ReconcilePairing";

const WP = "wp-0000000000ee";
const STMT = "c".repeat(64);
const lineId = (n: number) => `${STMT.slice(0, 16)}:${String(n).padStart(12, "0")}:0`;

const line = (n: number, over: Partial<ReconcileLine> = {}): ReconcileLine => ({
  id: lineId(n), statement_id: STMT, account: "111122233333444455556666", statement_type: "bank_account", currency: "HUF",
  booking_date: `2026-04-${String(10 + n).padStart(2, "0")}`, value_date: `2026-04-${String(8 + n).padStart(2, "0")}`, direction: "debit",
  amount: "1000.00", counterparty_name: "Example Federation", counterparty_account: "99998887-77776666-55554444", description: "Transfer",
  memo: `A long memo that names FED-000${n} and the season's fee`, running_balance: "5000.00", state: "open", excluded_reason: null,
  allocated: "0", rest: "1000.00", mark: null, allocations: [], candidates: [], rejected: [], statement_verified: true,
  file: "CIB - statement 2026-04.json", ...over,
});
const workspace = (lines: ReconcileLine[], invoices: ReconcileInvoice[] = []): ReconcileWorkspace => ({
  workpackage_id: WP, lines, invoices, coverage: [], blockers: [], line_marks: ["private", "fee", "other"], open: {},
  counts: { lines: {}, invoices: {}, open_lines: lines.length }, learned_names: [], fx_tolerance: null, engine_version: "1.10.0",
  config_hash: "x", scope: { workpackage_id: WP, accounts: ["111122233333444455556666"], period_start: "2026-04-01", period_end: "2026-04-30", revision: 1, updated_at: "" },
});
const statementLines = (n: number) => Array.from({ length: n }, (_, i) => {
  const l = line(i + 1);
  return { id: l.id, booking_date: l.booking_date, value_date: l.value_date ?? null, direction: l.direction, amount: l.amount,
    counterparty_name: `Partner ${i + 1}`, counterparty_account: null, memo: `MEMO-${i + 1}`, description: null, running_balance: "5000.00" };
});
const located = (id: string, over: Partial<ReconcileLocation> = {}): ReconcileLocation => ({
  line_id: id, statement_id: STMT, open: null, image: null, pages: null, page: null, box: null, original: null,
  statement: { file: "CIB - statement 2026-04.json", institution: "Example Bank", account: "111122233333444455556666", currency: "HUF",
    period_start: "2026-04-01", period_end: "2026-04-30", opening_balance: "9000.00", closing_balance: "5000.00", verified: true,
    lines: statementLines(10) },
  ...over,
});

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

describe("the line's facts", () => {
  it("stand labelled in the finder's pinned line, without the statement's file name", async () => {
    vi.spyOn(api, "reconcileMatches").mockResolvedValue({ line_id: lineId(1), matches: [] });
    render(<ReconcilePairing ws={workspace([line(1)])} readOnly={false} onWorkspace={vi.fn()} reload={() => {}} />);
    const head = screen.getByLabelText("The selected line");
    expect(within(head).getByText("Memo")).toBeTruthy();
    expect(within(head).getByText("A long memo that names FED-0001 and the season's fee")).toBeTruthy();
    expect(within(head).getByText("Counterparty's account")).toBeTruthy();
    expect(within(head).getByText("99998887-77776666-55554444")).toBeTruthy();
    expect(within(head).getByText("Value day")).toBeTruthy();
    expect(within(head).queryByText(/statement 2026-04\.json/)).toBeNull();
    await waitFor(() => expect(api.reconcileMatches).toHaveBeenCalled());
  });

  it("on the left list a line without a memo shows no file name either", () => {
    vi.spyOn(api, "reconcileMatches").mockResolvedValue({ line_id: lineId(1), matches: [] });
    render(<ReconcilePairing ws={workspace([line(1, { memo: null, description: null })])} readOnly={false} onWorkspace={vi.fn()} reload={() => {}} />);
    expect(screen.queryByText(/statement 2026-04\.json/)).toBeNull();
  });

  it("show the facts beyond the money a code reader kept, only the printed ones", () => {
    const { unmount } = render(<LineFacts line={line(1, {
      card_number: "411111xxxxxx1111", purchase_date: "2026-04-09", transaction_time: "10:15", authorisation_code: "123456",
      exchange_rate: "394.11 HUF/EUR", fee: "300 HUF + 450 HUF", bank_reference: "A1BC000000000000001", end_to_end_id: "E2E-77",
    })} repeat={false} invoices={new Map()} />);
    for (const [label, value] of [["Card", "411111xxxxxx1111"], ["Purchased", "2026-04-09 10:15"], ["Authorisation code", "123456"],
      ["Exchange rate", "394.11 HUF/EUR"], ["Fee", "300 HUF + 450 HUF"], ["Bank reference", "A1BC000000000000001"], ["End-to-end id", "E2E-77"]]) {
      expect(screen.getByText(label)).toBeTruthy();
      expect(screen.getByText(value)).toBeTruthy();
    }
    expect(screen.queryByText("Terminal")).toBeNull();
    expect(screen.queryByText("Order id")).toBeNull();
    unmount();
    render(<LineFacts line={line(2, { transaction_time: "08:01:02" })} repeat={false} invoices={new Map()} />);
    expect(screen.getByText("Time")).toBeTruthy();
    expect(screen.queryByText("Purchased")).toBeNull();
  });

  it("on the card name every fact but the statement's file, and warn when the balances do not check out", () => {
    render(<LineFacts line={line(1, { statement_verified: false })} repeat={false} invoices={new Map()} />);
    expect(screen.getByText("Booking day")).toBeTruthy();
    expect(screen.getByText("Balance after")).toBeTruthy();
    expect(screen.queryByText("Statement")).toBeNull();
    expect(screen.queryByText(/statement 2026-04\.json/)).toBeNull();
    expect(screen.getByText("statement balances do not check out")).toBeTruthy();
  });
});

describe("the documents' statement pane", () => {
  it("shows the bank's PDF behind a statement read by code, the line framed, the statement as read closed", async () => {
    vi.spyOn(api, "reconcileLocate").mockResolvedValue(located(lineId(5), {
      image: "original", pages: 2, page: 1, box: [0.1, 0.2, 0.9, 0.25], original: { file: "20260430_statement.pdf", state: "found" },
    }));
    const { container } = render(<DocumentPair wpId={WP} line={line(5)} invoice={null} opens={{}} />);
    const img = await screen.findByRole("img", { name: "Statement" });
    expect(img.getAttribute("src")).toBe(api.originalPageUrl(WP, lineId(5), 1));
    expect(screen.getByText("20260430_statement.pdf")).toBeTruthy();
    expect(screen.getByText("Page 1 of 2")).toBeTruthy();
    expect(container.querySelector(".rc-box")).not.toBeNull();
    const facts = screen.getByLabelText("The line on the statement");
    expect(within(facts).getByText("A long memo that names FED-0005 and the season's fee")).toBeTruthy();
    expect((container.querySelector("details.rc-asread") as HTMLDetailsElement).open).toBe(false);
  });

  it("without a PDF shows the statement as read open, the line highlighted among its neighbours", async () => {
    vi.spyOn(api, "reconcileLocate").mockResolvedValue(located(lineId(5), { original: { file: "export.xlsx", state: "export" } }));
    const { container } = render(<DocumentPair wpId={WP} line={line(5)} invoice={null} opens={{}} />);
    expect(await screen.findByText("This statement was read from the bank's table or XML export, so it has no PDF page.")).toBeTruthy();
    expect(screen.queryByRole("img", { name: "Statement" })).toBeNull();
    expect((container.querySelector("details.rc-asread") as HTMLDetailsElement).open).toBe(true);
    const current = container.querySelector("tr[aria-current='true']") as HTMLElement;
    expect(within(current).getByText("MEMO-5")).toBeTruthy();
    await waitFor(() => expect(container.querySelectorAll(".rc-asread-table tbody tr")).toHaveLength(7));
    fireEvent.click(screen.getByRole("button", { name: "All 10 lines" }));
    // 153: waited for, as the other interface tests do (under the full check's load it once still showed the 7 rows)
    // 167 (the flaky lineFacts144 test): the default second was not enough once while a backup ran beside the full check
    await waitFor(() => expect(container.querySelectorAll(".rc-asread-table tbody tr")).toHaveLength(10), { timeout: 5000 });
    expect(screen.getByText(/Opening balance: 9,000\.00 HUF/)).toBeTruthy();
  });

  it("says when the bank's PDF is gone or changed since it was read", async () => {
    vi.spyOn(api, "reconcileLocate").mockResolvedValue(located(lineId(1), { original: { file: "20260430_statement.pdf", state: "missing" } }));
    render(<DocumentPair wpId={WP} line={line(1)} invoice={null} opens={{}} />);
    expect(await screen.findByText(/The bank's PDF \(20260430_statement\.pdf\) is not in the package's source folder/)).toBeTruthy();
    expect(screen.queryByRole("img", { name: "Statement" })).toBeNull();
  });

  it("keeps a PDF statement's own page, opened in its package", async () => {
    const open = { workpackage_id: "wp-0000000000aa", run_id: "run-000000000001", item_id: STMT, pages: 3 };
    vi.spyOn(api, "reconcileLocate").mockResolvedValue(located(lineId(1), { open, image: "item", pages: 3, page: 2, box: [0, 0.5, 1, 0.55] }));
    render(<DocumentPair wpId={WP} line={line(1)} invoice={null} opens={{}} />);
    const img = await screen.findByRole("img", { name: "Statement" });
    await waitFor(() => expect(img.getAttribute("src")).toBe(api.pageUrl(open.workpackage_id, STMT, 2)));
    expect(screen.getByRole("link", { name: "Open in its package" })).toBeTruthy();
  });
});
