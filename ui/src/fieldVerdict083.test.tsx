// 083 (the owner's trial of 2026-10-01): a tick and a cross right next to each field's value in Review, instead of
// resolving the to-dos at the top of the panel; a small filter (Javítandó / Bizonytalan / Mind); and the cross starts
// fixing the field with selection on the image. Artificial data, no service.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type ItemResult } from "./api";
import { setLanguage } from "./i18n";
import { draftKey, getDraft, resetDrafts, setField } from "./review/drafts";
import { FieldPanel } from "./review/FieldPanel";
import { classifyFields, initialFilter } from "./review/fieldFilter";

const RUN = "run-000000000083";
const ITEM = "b".repeat(64);
const BANDS = { confident: 0.9, check: 0.5 };

function result(over: Partial<ItemResult> = {}): ItemResult {
  return {
    run_id: RUN, item_id: ITEM,
    extraction: {
      doc_type: "invoice_hu", arm: "S", datapoints: { invoice_number: "MINTA-1", payment_iban: "HU00 1111", supplier_name: "Adattenger Kft." },
      field_conf: {}, validation: [], final_status: "needs_review", review_reasons: [],
    },
    correction: { run_id: RUN, item_id: ITEM, revision: 0, fields: {}, sources: {}, confirmed: {}, actor: null, note: null, created_at: null },
    effective: { invoice_number: "MINTA-1", payment_iban: "HU00 1111", supplier_name: "Adattenger Kft." },
    open_reasons: [
      { id: 1, reason: "pick:low_conf:payment_iban:0.52", producer: "flow", run_id: RUN, field: "payment_iban" },
      { id: 2, reason: "parties:same_tax_id", producer: "flow", run_id: RUN, field: null },
    ],
    earlier_open_reasons: [],
    provenance: {
      invoice_number: { status: "located", method: "pick", alternatives: [], confidence: 0.99 },
      payment_iban: { status: "located", method: "pick", alternatives: [], confidence: 0.52 },
      supplier_name: { status: "located", method: "pick", alternatives: [], confidence: 0.78 },
    },
    source: { layer_id: "L", text_source: "pdf", pages: [{ page: 1, width_pt: 595, height_pt: 842 }] },
    ...over,
  };
}

function panel(res: ItemResult, over: Partial<Parameters<typeof FieldPanel>[0]> = {}) {
  return (
    <FieldPanel result={res} fields={["payment_iban", "invoice_number", "supplier_name"]} bandOf={() => "check"} activeField="payment_iban"
      onActivate={() => {}} selection={{ ids: [], text: "" }} onClearSelection={() => {}} selectMode={false} onToggleSelect={() => {}}
      onSaved={() => {}} onResolved={() => {}} onChooseAlternative={() => {}} readOnly={false} hasWords {...over} />
  );
}

beforeEach(() => setActor("Teszt Elek"));
afterEach(async () => { resetDrafts(); setActor(""); vi.restoreAllMocks(); await setLanguage("hu"); });

describe("083 tick and cross at the field", () => {
  it("every field has a tick and a cross; a field's to-do is shown at the field, a document's at the top", () => {
    render(panel(result()));
    for (const label of ["Bankszámlaszám", "Számlaszám", "Szállító neve"]) {
      expect(screen.getByRole("button", { name: `${label}: helyes` })).toBeTruthy();
      expect(screen.getByRole("button", { name: `${label}: hibás, javítom` })).toBeTruthy();
    }
    const top = screen.getByRole("list", { name: "Nyitott teendők ebben a futásban" });
    expect(top.textContent).toContain("A szállító és a vevő adószáma azonos");
    expect(top.textContent).not.toContain("Bankszámlaszám");
    const atField = screen.getByRole("list", { name: "Bankszámlaszám: teendők" });
    expect(atField.textContent).toContain("Bizonytalan érték: Bankszámlaszám");
  });

  it("the tick on an unchanged field confirms it without changing anything", async () => {
    const spy = vi.spyOn(api, "saveCorrection").mockResolvedValue(result());
    render(panel(result()));
    await userEvent.click(screen.getByRole("button", { name: "Bankszámlaszám: helyes" }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(spy.mock.calls[0][2]).toEqual({ fields: {}, expected_revision: 0, confirm: ["payment_iban"] });
  });

  it("the tick on an edited field saves that field only; the other unsaved change stays and follows the new version", async () => {
    const key = draftKey(RUN, ITEM);
    setField(key, 0, "invoice_number", "X-2");
    setField(key, 0, "payment_iban", "HU99 2222", [5, 6]);
    const saved = result({ correction: { ...result().correction, revision: 1, fields: { payment_iban: "HU99 2222" }, confirmed: { payment_iban: "HU99 2222" } } });
    const spy = vi.spyOn(api, "saveCorrection").mockResolvedValue(saved);
    render(panel(result()));
    await userEvent.click(screen.getByRole("button", { name: "Bankszámlaszám: helyes" }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(spy.mock.calls[0][2]).toEqual({ fields: { payment_iban: "HU99 2222" }, expected_revision: 0, sources: { payment_iban: [5, 6] }, confirm: ["payment_iban"] });
    expect(getDraft(key)).toEqual({ baseRevision: 1, values: { invoice_number: "X-2" }, sources: {}, lists: {} });
  });

  it("the cross empties the field and starts fixing it; the undo button brings the value back", async () => {
    const onStartFix = vi.fn();
    render(panel(result(), { onStartFix }));
    await userEvent.click(screen.getByRole("button", { name: "Bankszámlaszám: hibás, javítom" }));
    expect(onStartFix).toHaveBeenCalledWith("payment_iban");
    expect((screen.getByLabelText("Bankszámlaszám") as HTMLInputElement).value).toBe("");
    expect(screen.getByText(/Jelöld ki a helyes értéket a képen/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Bankszámlaszám: visszaállítás" }));
    expect((screen.getByLabelText("Bankszámlaszám") as HTMLInputElement).value).toBe("HU00 1111");
  });

  it("a confirmed field is marked as checked until its value is edited", async () => {
    const res = result({ correction: { ...result().correction, revision: 1, confirmed: { supplier_name: "Adattenger Kft." } } });
    render(panel(res));
    expect(screen.getByText("ellenőrizve")).toBeTruthy();
    await userEvent.type(screen.getByLabelText("Szállító neve"), "!");
    expect(screen.queryByText("ellenőrizve")).toBeNull();
  });

  it("an approved run cannot be confirmed", () => {
    render(panel(result(), { readOnly: true }));
    expect((screen.getByRole("button", { name: "Bankszámlaszám: helyes" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("083 the field filter", () => {
  it("sorts the fields into to fix, uncertain and all", () => {
    const res = result({ correction: { ...result().correction, confirmed: { supplier_name: "Adattenger Kft." } } });
    const groups = classifyFields(["payment_iban", "invoice_number", "supplier_name"], res, BANDS);
    expect(groups.fix).toEqual(["payment_iban"]);
    // the IBAN is weak and not yet checked; the supplier's name is weak too but a person confirmed it
    expect(groups.uncertain).toEqual(["payment_iban"]);
    expect(groups.all).toHaveLength(3);
  });

  it("starts on the fields to fix when there are any, otherwise on all; a choice made earlier is kept while it has fields", () => {
    expect(initialFilter({ fix: 1, uncertain: 2, all: 3 }, null)).toBe("fix");
    expect(initialFilter({ fix: 0, uncertain: 2, all: 3 }, null)).toBe("all");
    expect(initialFilter({ fix: 1, uncertain: 2, all: 3 }, "uncertain")).toBe("uncertain");
    expect(initialFilter({ fix: 1, uncertain: 0, all: 3 }, "uncertain")).toBe("fix");
  });

  it("shows the three buttons with counts, and says when nothing is left to fix", async () => {
    const onFilter = vi.fn();
    render(panel(result(), { fields: [], filter: "fix", counts: { fix: 0, uncertain: 1, all: 3 }, onFilter }));
    expect(screen.getByRole("button", { name: "Javítandó (0)" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Ezen a tételen nincs több javítandó mező.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Mind (3)" }));
    expect(onFilter).toHaveBeenCalledWith("all");
  });

  it("the new labels have an English translation", async () => {
    await setLanguage("en");
    render(panel(result(), { filter: "fix", counts: { fix: 1, uncertain: 1, all: 3 }, onFilter: () => {} }));
    expect(screen.getByRole("button", { name: "To fix (1)" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Bank account number: correct" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Bank account number: wrong, fix it" })).toBeTruthy();
  });
});
