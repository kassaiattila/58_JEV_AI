// 136 (E4): a work package from a bank's statement exported as a table: the accounts are listed without their lines,
// and only the ticked ones are sent. Synthetic accounts only.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type StatementTableSurvey, type WorkpackageView } from "../api";
import { setLanguage } from "../i18n";
import { StatementTableCreate } from "./StatementTableCreate";

const SURVEY: StatementTableSurvey = {
  profile: "revolut_consolidated_hu", institution: "Revolut", file: "statement.xlsx", repairs: [],
  accounts: [
    { key: "A:HUF", account: "…0001", title: "Personal", occurrence: 1, currency: "HUF", lines: 4, first: "2026-01-02",
      last: "2026-03-01", period_start: "2026-01-01", period_end: "2026-03-31", checks_ok: true, problems: 0 },
    { key: "Pocket (HUF)#1", account: null, title: "Pocket", occurrence: 1, currency: "HUF", lines: 0, first: null,
      last: null, period_start: "2026-01-01", period_end: "2026-03-31", checks_ok: false, problems: 1 },
  ],
};

beforeEach(async () => { await setLanguage("en"); });
afterEach(() => vi.restoreAllMocks());

describe("a package from a bank's table export", () => {
  it("lists the accounts and creates the package with the ticked ones only", async () => {
    const survey = vi.spyOn(api, "statementTableSurvey").mockResolvedValue(SURVEY);
    const create = vi.spyOn(api, "createFromStatementTable").mockResolvedValue({ workpackage: { id: "wp-000000000001" } } as WorkpackageView);
    const done = vi.fn();
    render(<StatementTableCreate onDone={done} />);
    fireEvent.change(screen.getByLabelText("The exported file's or folder's full path"), { target: { value: "C:\\exports\\statement.xlsx" } });
    fireEvent.click(screen.getByRole("button", { name: "List the accounts" }));
    await screen.findByText("Accounts in the file (Revolut)");
    expect(survey).toHaveBeenCalledWith("C:\\exports\\statement.xlsx");
    expect(screen.getByText("a check failed: it becomes a to-do in the run")).toBeTruthy();
    const createButton = screen.getByRole("button", { name: "Create with 0 account(s)" }) as HTMLButtonElement;
    expect(createButton.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "Choose Personal (HUF)" }));
    fireEvent.click(screen.getByRole("button", { name: "Create with 1 account(s)" }));
    await waitFor(() => expect(done).toHaveBeenCalledWith("wp-000000000001"));
    expect(create).toHaveBeenCalledWith("C:\\exports\\statement.xlsx", ["A:HUF"], "Revolut statements 2026-01-01 – 2026-03-31");
  });

  it("137: lists a folder's months, marks the ones without a PDF statement and selects them all", async () => {
    const month = (start: string, end: string, pdf: boolean) => ({
      key: `111122233333444455556666:HUF:${start}`, account: null, title: `…6666 E ${start.slice(5, 7)}/2026`, occurrence: 1,
      currency: "HUF", lines: 3, first: start, last: end, period_start: start, period_end: end, checks_ok: pdf, problems: 0,
      balance_checked: pdf, companion: pdf ? `${end.replace(/-/g, "")}_S.pdf` : null });
    vi.spyOn(api, "statementTableSurvey").mockResolvedValue({
      profile: "erste_ledger_hu", institution: "Erste", file: "erste", repairs: [], skipped: 1,
      accounts: [month("2026-05-01", "2026-05-31", false), month("2026-06-01", "2026-06-30", true)] });
    const create = vi.spyOn(api, "createFromStatementTable").mockResolvedValue({ workpackage: { id: "wp-000000000002" } } as WorkpackageView);
    render(<StatementTableCreate onDone={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("The exported file's or folder's full path"), { target: { value: "C:\\exports\\erste" } });
    fireEvent.click(screen.getByRole("button", { name: "List the accounts" }));
    await screen.findByText("Accounts in the file (Erste)");
    expect(screen.getByText("balances not checked: no PDF statement (a to-do in the run)")).toBeTruthy();
    expect(screen.getByText("1 file(s) in the folder could not be read as an export")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    fireEvent.click(screen.getByRole("button", { name: "Create with 2 account(s)" }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0][1]).toEqual(["111122233333444455556666:HUF:2026-05-01", "111122233333444455556666:HUF:2026-06-01"]);
  });
});
