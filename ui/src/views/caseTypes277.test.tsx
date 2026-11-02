// 277 (O3; the owner's decision of 2026-11-02: the case types grouped, and those alike made one with a choice when a
// case starts): New case lists the processes under their groups; a process that asks a choice shows its options first,
// and the form asks only the documents of the steps the chosen option keeps and starts the case with the choice; an
// option a case cannot start on yet says what it needs; the case list's left panel groups the processes; a process's
// settings show a resource a choice sets as each option's value. Synthetic data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, choiceQuery, pickedOptions, setActor, type ProcessRow } from "../api";
import { setLanguage } from "../i18n";
import { CaseList } from "./CaseList";
import { NewCase } from "./NewCase";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ""; });

const CASE = "wp-000000000277";
const PARTY = "party-000000000001";
const GROUPS = [{ id: "documents", title: "Documents" }, { id: "emails", title: "Emails" },
  { id: "reconciliation", title: "Reconciliation" }, { id: "quotes", title: "Quotes" }];
const MONTHLY: ProcessRow = {
  id: "monthly_reconciliation", title: "Monthly reconciliation", version: "1.2.0", scope: ["party", "period", "step_sources"],
  asks: ["party", "period", "step_sources"], package_kinds: [], manual: true, examples: false, missing_at_start: [],
  summary: "An own party's period in one case.", group: "reconciliation",
  step_sources: [
    { step: "invoices", title: "Incoming invoices", pack: "documents", process: "Documents", source_kinds: ["folder", "files"], examples: false },
    { step: "emails", title: "Emails and their attachments", pack: "mailbox", process: "Emails from a mailbox", source_kinds: ["mailbox"], examples: false },
    { step: "statements", title: "Bank statements", pack: "bank_statements", process: "Bank statements", source_kinds: ["folder", "files"], examples: false },
  ],
  choices: [{ id: "invoices_from", title: "Where the invoices come from", default: "folder", options: [
    { id: "folder", title: "A folder or files", leaves_out: ["emails"], examples: false, missing_at_start: [] },
    { id: "mailbox", title: "A mailbox", leaves_out: ["invoices"], examples: false, missing_at_start: [] },
    { id: "both", title: "Both", leaves_out: [], examples: false, missing_at_start: [] }] }],
};
const ROW = (id: string, title: string, group: string): ProcessRow => ({ id, title, version: "1.0.0", manual: true, group,
  asks: ["source"], scope: ["source"], source_kinds: ["folder", "files"], examples: false, missing_at_start: [], choices: [] });
const QUOTE: ProcessRow = { ...ROW("insurance_offer", "Insurance quote", "quotes"), examples: true,
  choices: [{ id: "product", title: "Product", default: "invented", options: [
    { id: "invented", title: "Invented business property product", leaves_out: [], examples: true, missing_at_start: [] },
    { id: "allianz", title: "Allianz corporate property", leaves_out: [], examples: true,
      missing_at_start: [{ key: "product", label: "Product" }] }] }] };

describe("the case types (277 O3)", () => {
  it("lists the processes under their groups, in the groups' order", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ groups: GROUPS, processes: [
      QUOTE, MONTHLY, ROW("documents", "Documents", "documents"), ROW("mailbox", "Emails from a mailbox", "emails"),
      ROW("bank_statements", "Bank statements", "documents")] });
    render(<NewCase />);
    const list = await screen.findByRole("region", { name: "Which process?" });
    const groups = within(list).getAllByRole("group");
    expect(groups.map((g) => g.querySelector("legend")?.textContent)).toEqual(["Documents", "Emails", "Reconciliation", "Quotes"]);
    expect(within(groups[0]).getAllByRole("radio").map((r) => r.getAttribute("aria-label"))).toEqual(["Documents", "Bank statements"]);
  });

  it("shows a process's choice first and asks only the documents of the steps the chosen option keeps", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ groups: GROUPS, processes: [MONTHLY] });
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
    vi.spyOn(api, "ownParties").mockResolvedValue({ parties: [{ id: PARTY, name: "Example Party Kft.", identities: [] }] } as never);
    const start = vi.spyOn(api, "startCase").mockResolvedValue({ case_id: CASE });
    render(<NewCase pack="monthly_reconciliation" />);
    const form = await screen.findByRole("form", { name: "Monthly reconciliation" });
    expect(within(form).queryByRole("group", { name: /Emails and their attachments/ })).toBeNull();  // the default: a folder
    expect(within(form).getByRole("group", { name: "Incoming invoices · Documents" })).toBeTruthy();
    const choice = screen.getByRole("group", { name: "Where the invoices come from" });
    expect((within(choice).getByRole("radio", { name: "A folder or files" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(choice).getByRole("radio", { name: "Both" }));
    const both = await screen.findByRole("form", { name: "Monthly reconciliation" });
    expect(within(both).getByRole("group", { name: "Incoming invoices · Documents" })).toBeTruthy();
    expect(within(both).getByRole("group", { name: "Emails and their attachments · Emails from a mailbox" })).toBeTruthy();
    fireEvent.click(within(choice).getByRole("radio", { name: "A mailbox" }));
    const mailbox = await screen.findByRole("form", { name: "Monthly reconciliation" });
    expect(within(mailbox).queryByRole("group", { name: "Incoming invoices · Documents" })).toBeNull();
    fireEvent.click(within(choice).getByRole("radio", { name: "A folder or files" }));
    const folder = await screen.findByRole("form", { name: "Monthly reconciliation" });
    fireEvent.change(within(folder).getByLabelText("Own party"), { target: { value: PARTY } });
    fireEvent.change(within(folder).getByLabelText("Period from"), { target: { value: "2026-03-01" } });
    fireEvent.change(within(folder).getByLabelText("to"), { target: { value: "2026-03-31" } });
    for (const name of ["Incoming invoices · Documents", "Bank statements · Bank statements"]) {
      fireEvent.change(within(within(folder).getByRole("group", { name })).getByLabelText("The folder's full path"),
        { target: { value: `D:\\Invented\\${name.split(" ")[0]}` } });
    }
    fireEvent.click(within(folder).getByRole("button", { name: "Create" }));
    await waitFor(() => expect(start).toHaveBeenCalled());
    expect(start.mock.calls[0][0]).toMatchObject({ pack: "monthly_reconciliation", choices: { invoices_from: "folder" } });
    expect(Object.keys(start.mock.calls[0][0].step_sources ?? {})).toEqual(["invoices", "statements"]);
  });

  it("says what an option needs before a case can start on it, and shows that option's example material", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ groups: GROUPS, processes: [QUOTE] });
    const examples = vi.spyOn(api, "processExamples").mockResolvedValue({ sets: [
      { kind: "product_set", name: "x", title: "An invented tariff", state: "missing", example: false }], packets: [] });
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
    render(<NewCase pack="insurance_offer" />);
    const choice = await screen.findByRole("group", { name: "Product" });
    expect(await screen.findByRole("form", { name: "Insurance quote" })).toBeTruthy();  // the default can start
    await waitFor(() => expect(examples).toHaveBeenCalledWith("insurance_offer", { product: "invented" }));
    fireEvent.click(within(choice).getByRole("radio", { name: "Allianz corporate property" }));
    expect(within(choice).getByText("Before a case can start: Product needs an active version.")).toBeTruthy();
    await waitFor(() => expect(examples).toHaveBeenCalledWith("insurance_offer", { product: "allianz" }));
    expect(screen.queryByRole("form", { name: "Insurance quote" })).toBeNull();  // until its product is active
    expect(screen.getByRole("button", { name: "Install the example material" }).className).toContain("primary");
  });

  it("groups the processes in the case list's left panel", async () => {
    vi.spyOn(api, "caseViews").mockResolvedValue({ views: { waiting: 0, mine: 0, open: 3, closed: 0 }, groups: GROUPS,
      processes: [{ pack: "documents", title: "Documents", open: 2, all: 2, repeats: false, group: "documents" },
        { pack: "insurance_offer", title: "Insurance quote", open: 1, all: 1, repeats: false, group: "quotes" },
        { pack: "allianz_property_offer", title: "Allianz corporate property quote", open: 0, all: 4, repeats: false, group: "quotes" }] });
    vi.spyOn(api, "datasetQuery").mockResolvedValue({
      dataset: { name: "cases", label: "Cases", scope: [], optional_scope: [] },
      columns: [{ key: "name", label: "Case", kind: "text", link: "case" }],
      rows: [], total: 0, matched: 0, offset: 0, limit: 50, facets: {} } as never);
    render(<CaseList />);
    const quotes = await screen.findByRole("button", { name: /^Quotes/ });
    expect(quotes.getAttribute("aria-expanded")).toBe("true");  // a group starts open
    expect(screen.getByRole("link", { name: /^Allianz corporate property quote/ })).toBeTruthy();  // an old case type's cases
    expect(screen.getByRole("button", { name: /^Documents/ })).toBeTruthy();
  });

  it("builds the address's choices and reads the picked options", () => {
    expect(choiceQuery({ product: "allianz" })).toBe("?choice=product%3Aallianz");
    expect(choiceQuery()).toBe("");
    expect(pickedOptions(QUOTE.choices, {}).map((o) => o.id)).toEqual(["invented"]);
    expect(pickedOptions(QUOTE.choices, { product: "allianz" }).map((o) => o.id)).toEqual(["allianz"]);
  });
});
