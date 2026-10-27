// 231 (stage D, D-f4): an assessment's data check. The field review shows the units in their tree with where each fact
// came from, the disagreements a person settles (taking the offered value saves the unit with the state the page
// showed), and the freeze, which is the one solid button only once nothing is to settle and the day cover starts is
// given; a frozen check says so and may be reopened with a reason. The documents' facts list what could not be read, and
// a register's answer shows the facts it offers. Invented data, a mocked service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type DocumentFactsData, type FieldReviewData, type LookupData } from "../api";
import type { Catalogue } from "../api/products";
import { setLanguage } from "../i18n";
import { elementOf } from "./registry";

beforeEach(async () => { await setLanguage("en"); setActor("Minta Anna"); });
afterEach(() => { vi.restoreAllMocks(); });

const CASE = "wp-0000000d0f40";
const CAT: Catalogue = {
  id: "property", version: "1.4.0", levels: ["holder", "site", "asset_group"], outcomes: {},
  facts: {
    company_name: { type: "text", level: "holder", title: "Company name", unit: null, currency: null, options: null },
    activity_code: { type: "code", level: "holder", title: "Activity code (NACE)", unit: null, currency: null, options: null },
    flood_zone: { type: "code", level: "site", title: "Flood zone", unit: null, currency: null, options: ["none", "low", "high"] },
    sum_insured: { type: "money", level: "asset_group", title: "Sum insured", unit: null, currency: "HUF", options: null },
  },
  labels: { holder: "Policyholder", site: "Site", asset_group: "Asset group", low: "Low", high: "High" },
};
const SRC = { source: { item: "i1", file: "request.pdf", page: 1, quote: "Szerződő: Minta Kft." } };
const review = (over: Partial<FieldReviewData> = {}): FieldReviewData => ({
  units: [
    { unit_id: "u-1", level: "holder", parent_id: null, state: 3, facts: { company_name: "Minta Kft.", activity_code: "4719" },
      sources: { company_name: SRC } },
    { unit_id: "u-2", level: "site", parent_id: "u-1", state: 1, facts: { flood_zone: "low" }, sources: {} },
  ],
  claims: [{ from_step: "company", unit_key: "holder", fact: "activity_code", value: "2562", placement: "conflict", unit_id: "u-1", open: true }],
  state: 7, approval: { state: "missing", step: "check", active: null, versions: [], returned: null, outdated: null },
  catalogue: CAT, frozen: null, conflicts: 1, waits: true, ...over,
});

function page(type: string, step: string, data: unknown, uses: string, title: string, state = "running"): CaseView {
  return {
    case: { id: CASE, pack: "insurance_offer", version: "1.1.0", title: "Insurance quote", name: "Minta Kft.", status: "open" },
    steps: {
      [step]: { title, uses, start: "auto", state, phase: null, waiting_for: null, awaiting_start: false, note: null, result: null, actions: [] },
      company: { title: "Company register", uses: "lookup@1", start: "auto", state: "done", phase: null, waiting_for: null,
        awaiting_start: false, note: null, result: null, actions: [] },
    },
    tabs: [{ id: "data", label: "Data check", elements: [{ type, step, data }] }], next: null,
  };
}

function show(type: string, step: string, data: unknown, uses: string, title: string, state?: string) {
  const p = page(type, step, data, uses, title, state);
  const spec = elementOf(type)!;
  render(<>{spec.render({ caseId: CASE, element: p.tabs[0].elements[0], page: p, onChanged: () => {} })}</>);
}

describe("the field review", () => {
  it("shows the units with their sources and a disagreement to settle, taken with the unit's state", async () => {
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue({} as CaseView);
    show("field_review", "check", review(), "field_check@1", "Data check");
    expect(await screen.findByRole("heading", { name: "What the sources disagree on: 1" })).toBeTruthy();
    expect(screen.getByText("Policyholder")).toBeTruthy();
    expect(screen.getByText(/request\.pdf · page 1/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Take this value" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "check", "unit_save", undefined, {
      unit_id: "u-1", facts: { company_name: "Minta Kft.", activity_code: "2562" }, expected_state: 3, note: "taken from Company register" }));
  });

  it("offers the freeze as the solid button only once nothing is to settle and the day is given", async () => {
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue({} as CaseView);
    show("field_review", "check", review({ claims: [], conflicts: 0 }), "field_check@1", "Data check");
    const freeze = await screen.findByRole("button", { name: "Freeze the facts" });
    expect(freeze.className).toBe("secondary");
    expect(freeze).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText("Cover starts"), { target: { value: "2027-01-01" } });
    expect(freeze.className).toBe("primary");
    fireEvent.click(freeze);
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "check", "freeze", undefined,
      { cover_start: "2027-01-01", expected_state: 7 }));
  });

  it("keeps the freeze secondary while a disagreement is open", async () => {
    show("field_review", "check", review(), "field_check@1", "Data check");
    fireEvent.change(await screen.findByLabelText("Cover starts"), { target: { value: "2027-01-01" } });
    expect(screen.getByRole("button", { name: "Freeze the facts" }).className).toBe("secondary");
    expect(screen.getByText("Settle the disagreements first.")).toBeTruthy();
  });

  it("edits a unit's facts and saves them with its state", async () => {
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue({} as CaseView);
    show("field_review", "check", review({ claims: [], conflicts: 0 }), "field_check@1", "Data check");
    fireEvent.click((await screen.findAllByRole("button", { name: "Edit" }))[1]);
    fireEvent.change(screen.getByRole("combobox", { name: "Flood zone" }), { target: { value: "high" } });
    fireEvent.click(screen.getByRole("button", { name: "Save the unit" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "check", "unit_save", undefined,
      { unit_id: "u-2", facts: { flood_zone: "high" }, expected_state: 1, note: null }));
  });

  it("says a frozen check's version and reopens it with a reason", async () => {
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue({} as CaseView);
    show("field_review", "check", review({ claims: [], conflicts: 0, waits: false,
      frozen: { version: 2, cover_start: "2027-01-01", by: "Minta Anna", at: "2026-10-26T10:00:00+00:00" } }), "field_check@1", "Data check", "done");
    expect((await screen.findByText(/^Frozen as version 2 by Minta Anna/)).className).toBe("notice ok-box");
    expect(screen.queryByRole("button", { name: "Freeze the facts" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Reopen the check" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Why it is reopened" }), { target: { value: "a site is missing" } });
    fireEvent.click(screen.getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "check", "reopen", "a site is missing", undefined));
  });
});

describe("the documents' facts and a register's answer", () => {
  it("lists what a document could not read, with why", async () => {
    const data: DocumentFactsData = { state: "done", catalogue: CAT, documents: [
      { item: "i1", file: "schedule.pdf", doc_type: "property_schedule", claims: 9,
        unread: [{ unit: "site:1", fact: "flood_zone", value: "nagyon magas", why: "not a known code" }] },
      { item: "i2", file: "invoice.pdf", doc_type: "invoice_hu", claims: 0, unread: [], note: "no reading takes this type" }] };
    show("document_facts", "facts", data, "fact_claims@1", "Facts from the documents", "done");
    expect((await screen.findByText("Flood zone: “nagyon magas” was not read (not a known code)")).className).toBe("warning");
    expect(screen.getByText("not read: another type")).toBeTruthy();
  });

  it("shows what a register was asked with and the facts it offers", async () => {
    const data: LookupData = { state: "done", note: null, connector: "invented_company_register", what: "An invented company register",
      asked: true, missing: [], question: { company_name: "Minta Kft." }, catalogue: CAT,
      claims: [{ unit: "holder", fact: "activity_code", value: "2562" }] };
    show("lookup", "company", data, "lookup@1", "Company register", "done");
    expect(await screen.findByRole("heading", { name: "Company register" })).toBeTruthy();
    expect(screen.getByText("Answered").className).toBe("status s-done");
    expect(screen.getByText("Asked with").nextElementSibling?.textContent).toBe("Company name: Minta Kft.");
    expect(screen.getByRole("table", { name: "What the register says" }).textContent).toContain("Activity code (NACE)2562");
  });
});
