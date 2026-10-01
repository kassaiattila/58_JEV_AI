// 084 (the owner's report of 2026-10-01): one shared date reader on every path. In Review a selected date whose day
// and month can be read two ways says so instead of a general "cannot be interpreted", a typed one the service refuses
// says how to type it, and a saved date is read back like a saved amount. Artificial data, no service.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor, type ItemResult } from "./api";
import { setLanguage } from "./i18n";
import { reasonText, savedValues } from "./labels";
import { draftKey, resetDrafts, setField } from "./review/drafts";
import { FieldPanel } from "./review/FieldPanel";

const RUN = "run-000000000084";
const ITEM = "c".repeat(64);

function result(): ItemResult {
  return {
    run_id: RUN, item_id: ITEM,
    extraction: {
      doc_type: "invoice_foreign", arm: "S", datapoints: { issue_date: "2022-04-12", invoice_number: "MINTA-1" },
      field_conf: {}, validation: [], final_status: "needs_review", review_reasons: [],
    },
    correction: { run_id: RUN, item_id: ITEM, revision: 0, fields: {}, sources: {}, confirmed: {}, actor: null, note: null, created_at: null },
    effective: { issue_date: "2022-04-12", invoice_number: "MINTA-1" },
    open_reasons: [{ id: 1, reason: "date:order_ambiguous:issue_date:'04/12/2022'", producer: "flow", run_id: RUN, field: "issue_date" }],
    earlier_open_reasons: [],
    provenance: {
      issue_date: { status: "located", method: "pick", alternatives: [], confidence: 0.95 },
      invoice_number: { status: "located", method: "pick", alternatives: [], confidence: 0.99 },
    },
    source: { layer_id: "L", text_source: "pdf", pages: [{ page: 1, width_pt: 595, height_pt: 842 }] },
  };
}

function panel(res: ItemResult, over: Partial<Parameters<typeof FieldPanel>[0]> = {}) {
  return (
    <FieldPanel result={res} fields={["issue_date", "invoice_number"]} bandOf={() => "check"} activeField="issue_date"
      onActivate={() => {}} selection={{ ids: [], text: "" }} onClearSelection={() => {}} selectMode
      onSaved={() => {}} onResolved={() => {}} onChooseAlternative={() => {}} readOnly={false} hasWords {...over} />
  );
}

beforeEach(() => setActor("Teszt Elek"));
afterEach(async () => { resetDrafts(); setActor(""); vi.restoreAllMocks(); await setLanguage("hu"); });

describe("084 dates in Review", () => {
  it("names the to-do of a date whose day and month can be read two ways", () => {
    expect(reasonText("date:order_ambiguous:issue_date:'04/12/2022'")).toBe("A nap és a hónap sorrendje kétes: Kiállítás dátuma");
    render(panel(result()));
    const atField = screen.getByRole("list", { name: "Kiállítás dátuma: teendők" });
    expect(atField.textContent).toContain("A nap és a hónap sorrendje kétes: Kiállítás dátuma");
  });

  it("reads a saved date back next to the saved amounts", () => {
    const text = savedValues({ issue_date: "2022-12-04", net_total: "28000", invoice_number: "A-1" },
      { issue_date: "date", net_total: "money", invoice_number: "invoice_number" });
    expect(text.replace(/[  ]/g, " ")).toBe("Kiállítás dátuma: 2022-12-04; Nettó összeg: 28 000");
  });

  it("a selected date that can be read two ways is not offered for the box, and the panel says why", async () => {
    vi.spyOn(api, "normalize").mockResolvedValue(
      { ok: false, value: null, reasons: ["date:order_ambiguous:issue_date:'04/12/2022'"], kind: "date" });
    render(panel(result(), { selection: { ids: [4], text: "04/12/2022" } }));
    expect(await screen.findByText(/a nap és a hónap kétféleképpen is olvasható/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Beírás a mezőbe" })).toBeNull();
  });

  it("a typed date the service refuses as two-way asks for the year first and keeps the change", async () => {
    setField(draftKey(RUN, ITEM), 0, "issue_date", "04/12/2022");
    vi.spyOn(api, "saveCorrection").mockRejectedValue(
      new ApiError(422, "ambiguous_date", "the day and the month can be read two ways"));
    render(panel(result()));
    await userEvent.click(screen.getByRole("button", { name: "Kiállítás dátuma: helyes" }));
    expect(await screen.findByText(/az évvel kezdve/)).toBeTruthy();
    expect((screen.getByLabelText("Kiállítás dátuma") as HTMLInputElement).value).toBe("04/12/2022");
  });
});
