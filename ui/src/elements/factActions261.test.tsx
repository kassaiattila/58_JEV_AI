// 261 (backlog Q-rogzites-409): after a person's action on a case's data check the next action is made on the state the
// action answered with, not on the page's earlier one, even while the page's reload has not ended; a page someone else
// made stale meanwhile is reloaded and says so. Invented data, a mocked service, a case page that never reloads.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor, type CaseView, type FieldReviewData } from "../api";
import type { Catalogue } from "../api/products";
import { setLanguage } from "../i18n";
import { elementOf } from "./registry";

beforeEach(async () => { await setLanguage("en"); setActor("Minta Anna"); });
afterEach(() => { vi.restoreAllMocks(); });

const CASE = "wp-0000000d0f41";
const CAT: Catalogue = {
  id: "property", version: "1.4.0", levels: ["holder"], outcomes: {},
  facts: { activity_code: { type: "code", level: "holder", title: "Activity code (NACE)", unit: null, currency: null, options: null } },
  labels: { holder: "Policyholder" },
};
const review = (state: number, open: boolean): FieldReviewData => ({
  units: [{ unit_id: "u-1", level: "holder", parent_id: null, state, facts: { activity_code: "4719" }, sources: {} }],
  claims: open ? [{ claim_key: "k-1", from_step: "company", unit_key: "holder", fact: "activity_code", value: "2562",
    placement: "conflict", unit_id: "u-1", open: true, kept: null }] : [],
  state, approval: { state: "missing", step: "check", active: null, versions: [], returned: null, outdated: null },
  catalogue: CAT, frozen: null, conflicts: open ? 1 : 0, waits: true, cover_start_hint: "2027-01-01",
});
const page = (data: FieldReviewData): CaseView => ({
  case: { id: CASE, pack: "insurance_offer", version: "1.1.0", title: "Insurance quote", name: "Minta Kft.", status: "open" },
  steps: {
    check: { title: "Data check", uses: "field_check@1", start: "auto", state: "running", phase: null, waiting_for: null,
      awaiting_start: false, note: null, result: null, actions: [] },
    company: { title: "Company register", uses: "lookup@1", start: "auto", state: "done", phase: null, waiting_for: null,
      awaiting_start: false, note: null, result: null, actions: [] },
  },
  tabs: [{ id: "data", label: "Data check", elements: [{ type: "field_review", step: "check", data }] }], next: null,
});

/** The case page's part this needs: the page it shows, an action's answer taken at once, a reload that never ends. */
function Harness({ first, reloads }: { first: CaseView; reloads: () => void }) {
  const [view, setView] = useState(first);
  const element = view.tabs[0].elements[0];
  return <>{elementOf("field_review")!.render({ caseId: CASE, element, page: view, onChanged: reloads, onView: setView })}</>;
}

describe("an action on a case's data check", () => {
  it("is followed by the next one on the state the first answered with", async () => {
    const act = vi.spyOn(api, "caseStepAction").mockImplementation(async (_c, _s, name) =>
      (name === "keep_value" ? page(review(8, false)) : page(review(9, false))));
    const reloads = vi.fn();
    render(<Harness first={page(review(7, true))} reloads={reloads} />);
    fireEvent.click(await screen.findByRole("button", { name: "Keep the value shown" }));
    const freeze = await screen.findByRole("button", { name: "Freeze the facts" });
    await waitFor(() => expect(freeze.className).toBe("primary"));  // the answer settled the disagreement
    fireEvent.click(freeze);
    await waitFor(() => expect(act).toHaveBeenLastCalledWith(CASE, "check", "freeze", undefined,
      { cover_start: "2027-01-01", expected_state: 8 }));
    expect(reloads).not.toHaveBeenCalled();
  });

  it("reloads a page someone else made stale and says so", async () => {
    vi.spyOn(api, "caseStepAction").mockRejectedValue(new ApiError(409, "revision_conflict", "the facts changed meanwhile; reload them"));
    const reloads = vi.fn();
    render(<Harness first={page(review(7, false))} reloads={reloads} />);
    fireEvent.click(await screen.findByRole("button", { name: "Freeze the facts" }));
    expect(await screen.findByText("The case changed since it was shown; it has been reloaded. Check it and try again.")).toBeTruthy();
    expect(reloads).toHaveBeenCalledTimes(1);
  });
});
