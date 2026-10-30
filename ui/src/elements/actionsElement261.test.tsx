// 261 (plan B, B1e; the owner's decision of 2026-10-29: the three shared elements now, each with a first user): the
// shared element `actions` shows a step's actions as buttons, one that may spend with its cost cap on the button; an
// action with a form is left to its step's own element; the page after the action is taken at once. Synthetic data, a
// mocked service.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView } from "../api";
import { setLanguage } from "../i18n";
import { ActionsView } from "./ActionsElement";
import type { ElementProps } from "./registry";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const CASE = "wp-00000000f261";
const page = (actions: CaseView["steps"][string]["actions"]): CaseView => ({
  case: { id: CASE, pack: "invented", version: "1.0.0", title: "Invented", name: "Invented case", status: "open" },
  steps: { run: { title: "Its run", uses: "invented@1", start: "person", state: "running", phase: null, waiting_for: null,
    awaiting_start: false, note: null, result: null, actions } },
  tabs: [], next: null,
});
const props = (view: CaseView): ElementProps => ({
  caseId: CASE, element: { type: "actions", step: "run", data: null }, page: view, onChanged: vi.fn(), onView: vi.fn(),
});

describe("the shared actions (261 B1e)", () => {
  it("shows each action as a button, one that may spend with its cost cap, and leaves a form's to its element", async () => {
    const view = page([{ name: "start", label: "Start the live run", cap: { openai: "0.40", jev: "0.20" } },
      { name: "note", label: "It arrived" }, { name: "decide", label: "Decide", form: true }]);
    const p = props(view);
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue(view);
    render(<ActionsView {...p} />);
    const start = screen.getByRole("button", { name: "Start the live run" });
    expect(start.textContent).toContain("≤ 0.60 USD");
    expect(start.getAttribute("title")).toBe("Start the live run: it can spend up to 0.60 USD");
    expect(screen.getByRole("button", { name: "It arrived" }).textContent).toBe("It arrived");
    expect(screen.queryByRole("button", { name: "Decide" })).toBeNull();
    fireEvent.click(start);
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "run", "start"));
    expect(p.onView).toHaveBeenCalledWith(view);  // the page after the action, at once
  });

  it("shows nothing for a step with no action of its own now", () => {
    const { container } = render(<ActionsView {...props(page([{ name: "decide", label: "Decide", form: true }]))} />);
    expect(container.textContent).toBe("");
  });
});
