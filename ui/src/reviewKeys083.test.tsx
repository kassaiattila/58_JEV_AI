// 083, the owner's second trial (2026-10-01): an earlier run's to-do on a field is shown at the field (the tick closes
// it), the earlier to-dos about the whole document sit closed at the bottom; selection on the image is always on (no
// toggle); the keyboard checks the fields one after the other (Tab / arrows / Enter / Esc); buttons for the previous
// and the next item, and the next item with to-dos when nothing is left. Artificial data, no service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DsPage, type ItemResult, type RunView, type Workpackage } from "./api";
import { setLanguage } from "./i18n";
import { draftKey, getDraft, resetDrafts, setField } from "./review/drafts";
import { FieldPanel } from "./review/FieldPanel";
import { nextAfterConfirm } from "./review/fieldFilter";
import { ReviewWorkspace } from "./views/ReviewWorkspace";

const RUN = "run-000000000084";
const ITEM = "c".repeat(64);

function result(over: Partial<ItemResult> = {}): ItemResult {
  return {
    run_id: RUN, item_id: ITEM,
    extraction: {
      doc_type: "invoice_hu", arm: "S", datapoints: { invoice_number: "MINTA-1", payment_iban: "HU00 1111" },
      field_conf: {}, validation: [], final_status: "needs_review", review_reasons: [],
    },
    correction: { run_id: RUN, item_id: ITEM, revision: 0, fields: {}, sources: {}, confirmed: {}, actor: null, note: null, created_at: null },
    effective: { invoice_number: "MINTA-1", payment_iban: "HU00 1111" },
    open_reasons: [{ id: 1, reason: "pick:low_conf:payment_iban:0.52", producer: "flow", run_id: RUN, field: "payment_iban" }],
    earlier_open_reasons: [
      { id: 7, reason: "pick:low_conf:payment_iban:0.47", producer: "old", run_id: "golden", field: "payment_iban" },
      { id: 9, reason: "pick:low_conf:payment_iban:0.47", producer: "old", run_id: "golden-2", field: "payment_iban" },
      { id: 8, reason: "parties:same_name", producer: "old", run_id: "golden", field: null },
    ],
    provenance: {
      invoice_number: { status: "located", method: "pick", alternatives: [], confidence: 0.99 },
      payment_iban: { status: "located", method: "pick", alternatives: [], confidence: 0.52 },
    },
    source: { layer_id: "L", text_source: "pdf", pages: [{ page: 1, width_pt: 595, height_pt: 842 }] },
    ...over,
  };
}

function panel(res: ItemResult, over: Partial<Parameters<typeof FieldPanel>[0]> = {}) {
  return (
    <FieldPanel result={res} fields={["payment_iban", "invoice_number"]} bandOf={() => "check"} activeField="payment_iban"
      onActivate={() => {}} selection={{ ids: [], text: "" }} onClearSelection={() => {}} selectMode
      onSaved={() => {}} onResolved={() => {}} onChooseAlternative={() => {}} readOnly={false} hasWords {...over} />
  );
}

beforeEach(() => setActor("Teszt Elek"));
afterEach(async () => { resetDrafts(); setActor(""); vi.restoreAllMocks(); await setLanguage("hu"); });

describe("083 earlier to-dos", () => {
  it("an earlier to-do on a field is shown at the field; the earlier ones about the document sit closed at the bottom", () => {
    render(panel(result()));
    expect(screen.queryByText(/Korábbi teendők az iraton/)).toBeNull();
    const atField = screen.getByRole("list", { name: "Bankszámlaszám: korábbi teendők" });
    // the same to-do from two earlier runs is shown once, with the number of runs
    expect(atField.textContent).toBe("2 korábbi futásból: Bizonytalan érték: Bankszámlaszám (valószínűség 0,47)");
    const bottom = screen.getByText(/Korábbi, egész iratra szóló teendők \(1\)/).closest("details") as HTMLDetailsElement;
    expect(bottom.open).toBe(false);
    expect(bottom.textContent).toContain("A szállító és a vevő neve azonos");
  });
});

describe("083 selection on the image is always on", () => {
  it("there is no toggle any more, only a hint", () => {
    render(panel(result()));
    expect(screen.queryByRole("button", { name: /Kijelölés/ })).toBeNull();
    expect(screen.getByText("A képen a szavakra kattintva vagy téglalapot húzva jelölöd ki az értéket.")).toBeTruthy();
  });
});

describe("083 keyboard in a field's box", () => {
  it("Enter is the tick: it saves and confirms the field and reports it as done from the keyboard", async () => {
    const saved = result({ correction: { ...result().correction, revision: 1, confirmed: { payment_iban: "HU00 1111" } } });
    const spy = vi.spyOn(api, "saveCorrection").mockResolvedValue(saved);
    const onConfirmed = vi.fn();
    render(panel(result(), { onConfirmed }));
    fireEvent.keyDown(screen.getByLabelText("Bankszámlaszám"), { key: "Enter" });
    await waitFor(() => expect(onConfirmed).toHaveBeenCalledWith("payment_iban", true, 1));
    expect(spy.mock.calls[0][2]).toEqual({ fields: {}, expected_revision: 0, confirm: ["payment_iban"] });
  });

  it("with an interpretable selection on the image, Enter first writes it into the box", async () => {
    vi.spyOn(api, "normalize").mockResolvedValue({ value: "HU42 1177 3016", ok: true } as never);
    const spy = vi.spyOn(api, "saveCorrection");
    render(panel(result(), { selection: { ids: [4, 5], text: "HU42 1177 3016" } }));
    await screen.findByText("HU42 1177 3016", { selector: "strong" });
    fireEvent.keyDown(screen.getByLabelText("Bankszámlaszám"), { key: "Enter" });
    expect(getDraft(draftKey(RUN, ITEM))?.values.payment_iban).toBe("HU42 1177 3016");
    expect(spy).not.toHaveBeenCalled();
  });

  it("Tab and the down arrow go to the next field, Shift+Tab and the up arrow to the previous one", () => {
    const onNavigate = vi.fn(() => true);
    render(panel(result(), { onNavigate }));
    const box = screen.getByLabelText("Bankszámlaszám");
    fireEvent.keyDown(box, { key: "Tab" });
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "Tab", shiftKey: true });
    fireEvent.keyDown(box, { key: "ArrowUp" });
    expect(onNavigate.mock.calls.map((c) => (c as unknown[])[0])).toEqual([1, 1, -1, -1]);
  });

  it("Esc brings back the original value of an edited field", () => {
    setField(draftKey(RUN, ITEM), 0, "payment_iban", "HU99");
    render(panel(result()));
    const box = screen.getByLabelText("Bankszámlaszám") as HTMLInputElement;
    expect(box.value).toBe("HU99");
    fireEvent.keyDown(box, { key: "Escape" });
    expect(box.value).toBe("HU00 1111");
  });

  it("after Enter, the next field is the one after it, or the one that took its place, or none (then the next item)", () => {
    expect(nextAfterConfirm(["a", "b", "c"], ["a", "b", "c"], "b")).toBe("c"); // still listed (All)
    expect(nextAfterConfirm(["a", "b", "c"], ["a", "c"], "b")).toBe("c"); // it left the filter (To fix)
    expect(nextAfterConfirm(["a", "b", "c"], ["a", "b", "c"], "c")).toBeNull(); // the last one
    expect(nextAfterConfirm(["a"], [], "a")).toBeNull(); // nothing is left
  });
});

describe("083 moving between the items from the right panel", () => {
  it("the previous and the next item buttons, disabled at the ends", async () => {
    const onNextItem = vi.fn();
    render(panel(result(), { onNextItem }));
    expect((screen.getByRole("button", { name: /Előző tétel/ }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: /Következő tétel/ }));
    expect(onNextItem).toHaveBeenCalled();
  });

  it("when nothing is left in the filter, the next item with to-dos is one click away", async () => {
    const onNextTodo = vi.fn();
    render(panel(result(), { fields: [], filter: "fix", counts: { fix: 0, uncertain: 0, all: 2 }, onFilter: () => {}, onNextTodo }));
    await userEvent.click(screen.getByRole("button", { name: /Következő teendős tétel/ }));
    expect(onNextTodo).toHaveBeenCalled();
  });

  it("the new labels have an English translation", async () => {
    await setLanguage("en");
    render(panel(result(), { onNextItem: () => {}, onPrevItem: () => {} }));
    expect(screen.getByRole("button", { name: /Next item/ })).toBeTruthy();
    expect(screen.getByRole("list", { name: "Bank account number: earlier to-dos" })).toBeTruthy();
  });
});

describe("083 the keyboard flow in the whole workspace", () => {
  function runView(): RunView {
    const runs: DsPage = { dataset: { name: "runs", label: "Futások", scope: ["workpackage_id"], optional_scope: [], natural_sort: [] },
      columns: [], rows: [{ _key: "run-k1", run_id: "run-k1" }], total: 1, matched: 1, offset: 0, limit: 1, facets: {} };
    vi.spyOn(api, "datasetQuery").mockResolvedValue(runs);
    return {
      run: { run_id: "run-k1", approval: null, items: [{ item_id: "a", status: "done", final_status: "needs_review" }, { item_id: "b", status: "done", final_status: "needs_review" }],
        input: { items: [{ item_id: "a", source_path: "C:/x/a.pdf" }, { item_id: "b", source_path: "C:/x/b.pdf" }] } },
      titles: {}, open_reasons: { a: [{ id: 1, reason: "pick:low_conf:invoice_number:0.5" }], b: [{ id: 2, reason: "parties:same_name" }] },
      earlier_open_reasons: {},
    } as unknown as RunView;
  }
  const item = (revision: number, reasons: ItemResult["open_reasons"]) => result({
    run_id: "run-k1", item_id: "a", open_reasons: reasons, earlier_open_reasons: [],
    correction: { ...result().correction, run_id: "run-k1", item_id: "a", revision },
  });

  it("Enter confirms, goes to the next field to fix, and after the last one to the next item with to-dos", async () => {
    vi.spyOn(api, "run").mockResolvedValue(runView());
    vi.spyOn(api, "settings").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "words").mockReturnValue(new Promise(() => {}));
    const reasons: ItemResult["open_reasons"] = [
      { id: 11, reason: "pick:low_conf:invoice_number:0.5", producer: "flow", run_id: "run-k1:a", field: "invoice_number" },
      { id: 12, reason: "pick:low_conf:payment_iban:0.5", producer: "flow", run_id: "run-k1:a", field: "payment_iban" },
    ];
    vi.spyOn(api, "item").mockResolvedValueOnce(item(0, reasons)).mockResolvedValueOnce(item(1, [reasons[1]])).mockResolvedValue(item(2, []));
    const save = vi.spyOn(api, "saveCorrection").mockResolvedValueOnce(item(1, [reasons[1]])).mockResolvedValueOnce(item(2, []));
    window.location.hash = "";
    render(<ReviewWorkspace wp={{ id: "wp-k" } as Workpackage} itemId="a" />);
    // the item opens on the fields to fix, with the cursor in the first one
    await waitFor(() => expect(document.activeElement?.id).toBe("fv-invoice_number"));
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    await waitFor(() => expect(document.activeElement?.id).toBe("fv-payment_iban"));
    expect(save.mock.calls[0][2]).toMatchObject({ confirm: ["invoice_number"] });
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    await waitFor(() => expect(window.location.hash).toBe("#/workpackages/wp-k/review/b"));
    expect(save.mock.calls[1][2]).toMatchObject({ confirm: ["payment_iban"] });
  });

  it("PageDown and PageUp switch items, in a field's box too", async () => {
    vi.spyOn(api, "run").mockResolvedValue(runView());
    vi.spyOn(api, "settings").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "words").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "item").mockResolvedValue(item(0, []));
    window.location.hash = "";
    render(<ReviewWorkspace wp={{ id: "wp-k" } as Workpackage} itemId="a" />);
    await waitFor(() => expect(document.activeElement?.id).toMatch(/^fv-/));
    fireEvent.keyDown(document.activeElement!, { key: "PageDown" });
    expect(window.location.hash).toBe("#/workpackages/wp-k/review/b");
  });
});
