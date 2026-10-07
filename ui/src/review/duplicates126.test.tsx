// 126: a suspected duplicate invoice on the review page: the two documents side by side, the differing values marked,
// and the three decisions. Expectations avoid Hungarian letters for the language guard.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DuplicatePair, type ItemResult } from "../api";
import { setLanguage } from "../i18n";
import { reasonText } from "../labels";
import { DuplicatePanel } from "./DuplicatePanel";

const OTHER = "a".repeat(64);
const pair = (over: Partial<DuplicatePair> = {}): DuplicatePair => ({
  other_doc_id: OTHER, other_file: "earlier.pdf", other_run_id: "run-000000000001", other_item_id: OTHER,
  other_workpackage_id: "wp-000000000001", kind: "variant", reason_id: 7, repeat: true, decision: null, decided_by: null, decided_at: null,
  fields: [
    { field: "invoice_number", value: "INV-1", other_value: "INV-1", differs: false, missing: false },
    { field: "gross_total", value: "1270.50", other_value: "1300.00", differs: true, missing: false },
    { field: "currency", value: "HUF", other_value: null, differs: false, missing: true },
  ],
  ...over,
});
const result = (pairs: DuplicatePair[]): ItemResult => ({
  run_id: "run-000000000002", item_id: "b".repeat(64), extraction: null, effective: {}, open_reasons: [], earlier_open_reasons: [],
  provenance: {}, source: null, kinds: { gross_total: "money" }, duplicates: pairs,
  correction: { run_id: "run-000000000002", item_id: "b".repeat(64), revision: 0, fields: {}, actor: null, note: null, created_at: null },
} as unknown as ItemResult);

beforeEach(async () => { await setLanguage("hu"); setActor("Synthetic reviewer"); });
afterEach(() => vi.restoreAllMocks());

describe("suspected duplicate invoices (126)", () => {
  it("names each kind of duplicate to-do", () => {
    expect(reasonText(`duplicate:copy:${OTHER.slice(0, 16)}`)).toMatch(/m.solata egy kor.bbi iratnak/);
    expect(reasonText(`duplicate:variant:${OTHER.slice(0, 16)}`)).toMatch(/m.dos.tott v.ltozata/);
    expect(reasonText(`duplicate:undecidable:${OTHER.slice(0, 16)}`)).toMatch(/egy .rt.k hi.nyzik/);
  });

  it("shows the two documents side by side with the differing value marked and a link to the earlier one", () => {
    render(<DuplicatePanel result={result([pair()])} readOnly={false} onDecided={() => {}} />);
    const table = screen.getByRole("table");
    const amount = within(table).getAllByRole("row").find((r) => r.textContent?.includes("1270,50"));
    expect(amount?.className).toBe("differs");
    expect(amount?.textContent).toContain("1300,00");
    expect(within(table).getAllByRole("row").find((r) => r.textContent?.includes("HUF"))?.className).toBe("missing");
    expect(screen.getByRole("link", { name: "earlier.pdf" }).getAttribute("href")).toBe(`#/workpackages/wp-000000000001/review/${OTHER}`);
  });

  it("sends the chosen decision and refreshes", async () => {
    const decide = vi.spyOn(api, "decideDuplicate").mockResolvedValue(result([]));
    const done = vi.fn();
    render(<DuplicatePanel result={result([pair()])} readOnly={false} onDecided={done} />);
    const buttons = within(screen.getByRole("group")).getAllByRole("button");
    expect(buttons).toHaveLength(3);
    fireEvent.click(buttons[2]); // not the same invoice
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(decide).toHaveBeenCalledWith("run-000000000002", "b".repeat(64), OTHER, "different");
  });

  it("shows a decision, and no buttons on an approved run", () => {
    render(<DuplicatePanel result={result([pair({ decision: "copy", decided_by: "Anna", reason_id: null })])} readOnly onDecided={() => {}} />);
    expect(screen.getByText(/Anna/).textContent).toMatch(/m.solat/i);
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("shows nothing without a suspicion", () => {
    const { container } = render(<DuplicatePanel result={result([])} readOnly={false} onDecided={() => {}} />);
    expect(container.textContent).toBe("");
  });
});
