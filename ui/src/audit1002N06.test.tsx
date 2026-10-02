// 090 (audit of 2026-10-02, N06): a change made while a save is under way is not lost. After the save only what was
// sent leaves the working copy; a newer value, a line-item list edited meanwhile or a new selection on the image stays,
// on the saved version, and the next save sends it. The audit's witness, turned round. Artificial data, no service.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, setActor, type ItemResult } from "./api";
import { draftKey, getDraft, resetDrafts, setField, setList, settleDraft } from "./review/drafts";
import { FieldPanel } from "./review/FieldPanel";

const RUN = "run-audit-n06";
const ITEM = "a".repeat(64);
const KEY = draftKey(RUN, ITEM);

function result(revision = 0, fields: Record<string, unknown> = {}): ItemResult {
  return {
    run_id: RUN, item_id: ITEM, kinds: { invoice_number: "text", supplier_name: "text" },
    extraction: { doc_type: "invoice_hu", arm: "S", datapoints: { invoice_number: "OLD", supplier_name: "Adattenger Kft." },
      field_conf: {}, validation: [], review_reasons: [] },
    correction: { revision, fields, sources: {}, confirmed: {} },
    effective: { invoice_number: "OLD", supplier_name: "Adattenger Kft.", ...fields },
    open_reasons: [], earlier_open_reasons: [], provenance: {}, source: null,
  } as unknown as ItemResult;
}

function panel(res: ItemResult) {
  return (
    <FieldPanel result={res} fields={["invoice_number", "supplier_name"]} bandOf={() => "check"} activeField="invoice_number"
      onActivate={() => {}} selection={{ ids: [], text: "" }} onClearSelection={() => {}} selectMode onSaved={() => {}}
      onResolved={() => {}} onChooseAlternative={() => {}} readOnly={false} hasWords={false} />
  );
}

/** A save that waits until the test lets it finish. */
function slowSave() {
  const pending: ((v: ItemResult) => void)[] = [];
  const spy = vi.spyOn(api, "saveCorrection").mockImplementation(() => new Promise((resolve) => { pending.push(resolve); }));
  return { spy, finish: (v: ItemResult) => pending.shift()!(v) };
}

beforeEach(() => setActor("Teszt Elek"));
afterEach(() => { resetDrafts(); setActor(""); vi.restoreAllMocks(); });

it("a value typed while saving stays in the working copy and the next save sends it", async () => {
  const { spy, finish } = slowSave();
  const view = render(panel(result()));
  const box = screen.getByLabelText("Számlaszám");
  fireEvent.change(box, { target: { value: "FIRST" } });
  fireEvent.click(screen.getByRole("button", { name: /Javítás mentése/ }));
  expect(spy.mock.calls[0][2].fields.invoice_number).toBe("FIRST");
  fireEvent.change(box, { target: { value: "SECOND" } });
  await act(async () => finish(result(1, { invoice_number: "FIRST" })));
  expect(getDraft(KEY)).toMatchObject({ baseRevision: 1, values: { invoice_number: "SECOND" } });

  view.rerender(panel(result(1, { invoice_number: "FIRST" })));  // the panel reloads the saved version
  fireEvent.click(screen.getByRole("button", { name: /Javítás mentése/ }));
  await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  expect(spy.mock.calls[1][2]).toMatchObject({ expected_revision: 1, fields: { invoice_number: "SECOND" } });
});

it("a field that did not change while saving leaves the working copy; another field typed meanwhile stays", async () => {
  const { finish } = slowSave();
  render(panel(result()));
  fireEvent.change(screen.getByLabelText("Számlaszám"), { target: { value: "FIRST" } });
  fireEvent.click(screen.getByRole("button", { name: /Javítás mentése/ }));
  fireEvent.change(screen.getByLabelText("Szállító neve"), { target: { value: "Másik Kft." } });
  await act(async () => finish(result(1, { invoice_number: "FIRST" })));
  const draft = getDraft(KEY);
  expect(draft?.values).toEqual({ supplier_name: "Másik Kft." });
  expect(draft?.baseRevision).toBe(1);
});

it("a line-item list or a selection on the image changed while saving stays", async () => {
  const { finish } = slowSave();
  render(panel(result()));
  fireEvent.change(screen.getByLabelText("Számlaszám"), { target: { value: "FIRST" } });
  fireEvent.click(screen.getByRole("button", { name: /Javítás mentése/ }));
  act(() => {
    setList(KEY, 0, "line_items", [{ description: "Új sor" }]);
    setField(KEY, 0, "invoice_number", "FIRST", [7, 8]);  // the same value, now picked from the image
  });
  await act(async () => finish(result(1, { invoice_number: "FIRST" })));
  const draft = getDraft(KEY);
  expect(draft?.lists).toEqual({ line_items: [{ description: "Új sor" }] });
  expect(draft?.values).toEqual({ invoice_number: "FIRST" });
  expect(draft?.sources).toEqual({ invoice_number: [7, 8] });
});

it("nothing changed while saving: the working copy is cleared as before", async () => {
  const { finish } = slowSave();
  render(panel(result()));
  fireEvent.change(screen.getByLabelText("Számlaszám"), { target: { value: "FIRST" } });
  fireEvent.click(screen.getByRole("button", { name: /Javítás mentése/ }));
  await act(async () => finish(result(1, { invoice_number: "FIRST" })));
  expect(getDraft(KEY)).toBeUndefined();
});

it("the tick: a value retyped in the same field while it is being confirmed stays", async () => {
  const { spy, finish } = slowSave();
  render(panel(result()));
  fireEvent.change(screen.getByLabelText("Számlaszám"), { target: { value: "FIRST" } });
  fireEvent.click(screen.getByRole("button", { name: "Számlaszám: helyes" }));
  expect(spy.mock.calls[0][2]).toMatchObject({ fields: { invoice_number: "FIRST" }, confirm: ["invoice_number"] });
  fireEvent.change(screen.getByLabelText("Számlaszám"), { target: { value: "SECOND" } });
  await act(async () => finish(result(1, { invoice_number: "FIRST" })));
  expect(getDraft(KEY)).toMatchObject({ baseRevision: 1, values: { invoice_number: "SECOND" } });
});

it("settling an unknown or already discarded working copy does nothing", () => {
  settleDraft(KEY, { baseRevision: 0, values: { invoice_number: "X" }, sources: {} }, 1);
  expect(getDraft(KEY)).toBeUndefined();
});
