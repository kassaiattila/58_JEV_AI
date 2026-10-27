// 231 (stage D, D-f6): a person's decision on another step's result. A choice the result does not allow cannot be
// taken; one that closes the case needs a reason; the decision is recorded with the result versions the page showed;
// above the limit, the earlier decision's maker sees that another person decides; a decision that holds says so.
// Invented data, a mocked service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type DecisionData } from "../api";
import { setLanguage } from "../i18n";
import { elementOf } from "./registry";

beforeEach(async () => { await setLanguage("en"); setActor("Minta Anna"); });
afterEach(() => { vi.restoreAllMocks(); });

const CASE = "wp-0000000d0f60";
const missing = { state: "missing" as const, step: "risk", active: null, versions: [], returned: null, outdated: null };
const risk = (over: Partial<DecisionData> = {}): DecisionData => ({
  about: "evaluate", result: { verdict: "refuse", version: 3 }, basis: { missing: 4 },
  choices: [{ code: "accept", title: "Accept the risk", closes: null, allowed: false },
            { code: "decline", title: "Decline the risk", closes: "declined", allowed: true }],
  second_person: null, problem: null, approval: missing, waits: true, decided: null, ...over,
});

function show(step: string, data: DecisionData, title: string) {
  const step_ = (t: string, uses: string): CaseView["steps"][string] => ({ title: t, uses, start: "auto", state: "running", phase: null,
    waiting_for: null, awaiting_start: false, note: null, result: null, actions: [] });
  const page: CaseView = {
    case: { id: CASE, pack: "insurance_offer", version: "1.3.0", title: "Insurance quote", name: "Minta Kft.", status: "open" },
    steps: { [step]: step_(title, "decision@1"), evaluate: step_("Rules", "rule_evaluation@1"), rate: step_("Premium", "rating@1"),
             risk: step_("Risk decision", "decision@1") },
    tabs: [{ id: "decision", label: "Decision and release", elements: [{ type: "decision", step, data }] }], next: null,
  };
  render(<>{elementOf("decision")!.render({ caseId: CASE, element: page.tabs[0].elements[0], page, onChanged: () => {} })}</>);
}

describe("a decision", () => {
  it("keeps a choice the result does not allow, and takes a closing one only with a reason, with the page's versions", async () => {
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue({} as CaseView);
    show("risk", risk(), "Risk decision");
    expect(await screen.findByText("Refused")).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Accept the risk/ })).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("radio", { name: /Decline the risk/ }));
    const record = screen.getByRole("button", { name: "Record the decision" });
    expect(record).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByRole("textbox", { name: "Reason (required)" }), { target: { value: "an excluded activity" } });
    expect(record.className).toBe("primary");
    fireEvent.click(record);
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "risk", "decide", undefined,
      { choice: "decline", note: "an excluded activity", expected_basis: { missing: 4 } }));
  });

  it("tells the earlier decision's maker that another person decides above the limit", async () => {
    show("premium", risk({ about: "rate", result: { total: { amount: "487000", currency: "HUF" } }, basis: { rate: 2 },
      choices: [{ code: "accept", title: "Accept the premium", closes: null, allowed: true }],
      second_person: { limit: "inv", amount: { amount: "487000", currency: "HUF" }, above: { amount: "300000", currency: "HUF" },
        needed: true, other_than: "risk", earlier_by: "Minta Anna", earlier_by_id: "local:Minta Anna" } }), "Premium decision");
    expect((await screen.findByText(/^Above the limit \(300,000 HUF\) another person decides, not Minta Anna \(who made the “Risk decision”\)/)).className)
      .toBe("notice todo small");
    fireEvent.click(screen.getByRole("radio", { name: /Accept the premium/ }));
    expect(screen.getByRole("button", { name: "Record the decision" })).toHaveProperty("disabled", true);
    expect(screen.getByText("Another person decides above the limit.")).toBeTruthy();
  });

  it("says the decision that holds, and offers no choice then", async () => {
    show("risk", risk({ waits: false, approval: { ...missing, state: "approved" }, decided: { version: 4, choice: "decline",
      title: "Decline the risk", note: "an excluded activity", by: "Minta Anna", at: "2026-10-26T10:00:00+00:00" } }), "Risk decision");
    expect((await screen.findByText(/^Decided: Decline the risk, by Minta Anna/)).className).toBe("notice ok-box");
    expect(screen.queryByRole("button", { name: "Record the decision" })).toBeNull();
  });
});
