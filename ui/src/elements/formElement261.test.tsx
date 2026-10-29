// 261 (plan B, B1g; the owner's decision of 2026-10-29: the three shared elements now, each with a first user): the
// shared element `form` shows a step's action's form as its capability describes it: the fields a person gives with
// their first values, the solid button once it can be sent, why not yet, and the page's state sent back as given; a
// form the service does not describe stays its step's own element's. Synthetic data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseAction, type CaseFormSpec, type CaseView } from "../api";
import { setLanguage } from "../i18n";
import { FormView } from "./FormElement";
import type { ElementProps } from "./registry";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const CASE = "wp-00000000f263";
const SET: CaseAction = { name: "set_day", label: "Set the day", form: {
  fields: [{ name: "day", label: "The day", kind: "date", required: true }, { name: "note", label: "A note", kind: "text", required: false }],
  values: { day: null, expected_state: 4 }, blocked: null } };
const page = (actions: CaseAction[]): CaseView => ({
  case: { id: CASE, pack: "invented", version: "1.0.0", title: "Invented", name: "Invented case", status: "open" },
  steps: { check: { title: "Its check", uses: "invented@1", start: "auto", state: "running", phase: null, waiting_for: null,
    awaiting_start: false, note: null, result: null, actions } },
  tabs: [], next: null,
});
const props = (view: CaseView): ElementProps => ({
  caseId: CASE, element: { type: "form", step: "check", data: null }, page: view, onChanged: vi.fn(), onView: vi.fn(),
});

describe("the shared form (261 B1g)", () => {
  it("asks for its fields, sends them with the page's state once the required ones are given", async () => {
    const view = page([SET, { name: "own", label: "Its own form", form: true }]);
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue(view);
    render(<FormView {...props(view)} />);
    const send = screen.getByRole("button", { name: "Set the day" });
    expect(send.className).toBe("secondary");
    expect(send).toHaveProperty("disabled", true);
    expect(screen.getByText("Give: The day")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Its own form" })).toBeNull();  // not described: its element's own
    fireEvent.change(screen.getByLabelText("The day"), { target: { value: "2027-02-01" } });
    expect(send.className).toBe("primary");
    fireEvent.click(send);
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "check", "set_day", undefined,
      { day: "2027-02-01", note: null, expected_state: 4 }));
  });

  it("says why it cannot be sent now", () => {
    const blocked: CaseFormSpec = { ...(SET.form as CaseFormSpec), values: { day: "2027-02-01" }, blocked: "Settle the disagreements first." };
    render(<FormView {...props(page([{ ...SET, form: blocked }]))} />);
    expect(screen.getByRole("button", { name: "Set the day" })).toHaveProperty("disabled", true);
    expect(screen.getByText("Settle the disagreements first.")).toBeTruthy();
  });
});
