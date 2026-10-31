// 231 (stage D0, D0-d; the reassessment of 2026-10-26, F03, P14): the approval of a case's approving step says when it
// is out of date (a step it builds on has a new result: approve it again) and when a person returned it with a reason,
// and while it is not approved a person may return it with a reason. The shared approval element shows a step's domain's
// own approval where it registers one (the quote's), else the general one. Synthetic data, a mocked service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type ApprovalState, type CaseView } from "../api";
import { ApprovalPanel } from "../components/ApprovalPanel";
import { setLanguage } from "../i18n";
import { elementOf } from "./registry";
import { confirmAction } from "../confirm.testutil";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { vi.restoreAllMocks(); });

const CASE = "wp-0000000d0d00";
const missing: ApprovalState = { state: "missing", step: "premium", active: null, versions: [], returned: null, outdated: null };
const outdated: ApprovalState = {
  ...missing, state: "outdated", outdated: "an earlier step it builds on changed: match_a",
  versions: [{ version: 1, fingerprint: "f", approved_by: "anna", approved_at: "2026-10-26T10:00:00+00:00", reopened_by: "process-core",
    reopened_at: "2026-10-26T11:00:00+00:00", reopen_note: "out of date: an earlier step it builds on changed: match_a" }],
};
const returned: ApprovalState = {
  ...missing, state: "returned", returned: { reason: "Two lines are missing", rejected_by: "bela", rejected_at: "2026-10-26T12:00:00+00:00" },
};

function panel(state: ApprovalState, onReturn = vi.fn().mockResolvedValue(true)) {
  render(<ApprovalPanel approval={{ active: state.active, versions: state.versions }} archived={false} busy={false}
    lockedText="Locked." pendingText="Not approved." blockers={null} approveLabel="Approve" onApprove={() => {}}
    onReopen={async () => true} error={null} notice={null} state={state} onReturn={onReturn} />);
  return onReturn;
}

describe("the approval's state", () => {
  it("says an approval out of date is to be approved again, naming the step whose result changed", () => {
    panel(outdated);
    expect(screen.getByRole("status").textContent).toBe(
      "Out of date: an earlier step it builds on changed: match_a. Check it and approve it again.");
  });

  it("names who returned it, when and why", () => {
    panel(returned);
    expect(screen.getByRole("status").textContent).toMatch(/^Returned by bela, .+: Two lines are missing$/);
  });

  it("returns it with a reason, after asking once more", async () => {
    const onReturn = panel(missing);
    const button = screen.getByRole("button", { name: "Return it" });
    expect(button).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByRole("textbox", { name: "Reason for returning it" }), { target: { value: "Two lines are missing" } });
    fireEvent.click(button);
    fireEvent.click(confirmAction());
    await waitFor(() => expect(onReturn).toHaveBeenCalledWith("Two lines are missing"));
  });
});

describe("the shared approval element", () => {
  const page = (uses: string): CaseView => ({
    case: { id: CASE, pack: "invented", version: "1.0.0", title: "Invented", name: "Invented case", status: "open" },
    steps: { premium: { title: null, uses, start: "auto", state: "running", phase: null, waiting_for: "approval", awaiting_start: false,
      note: null, result: null, actions: [] } },
    tabs: [], next: null,
  } as unknown as CaseView);

  it("shows the general approval of a step whose domain shows none, and returns it through the case's step", async () => {
    const back = vi.spyOn(api, "returnCaseStep").mockResolvedValue({ ...returned });
    const onChanged = vi.fn();
    const spec = elementOf("approval")!;
    render(<>{spec.render({ caseId: CASE, element: { type: "approval", step: "premium", data: { approval: outdated } },
      page: page("premium_table@1"), onChanged })}</>);
    expect((await screen.findByRole("status")).textContent).toContain("Out of date");
    fireEvent.change(screen.getByRole("textbox", { name: "Reason for returning it" }), { target: { value: "Recheck the table" } });
    fireEvent.click(screen.getByRole("button", { name: "Return it" }));
    fireEvent.click(confirmAction());
    await waitFor(() => expect(back).toHaveBeenCalledWith(CASE, "premium", "Recheck the table"));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("gives the quote's line composition step the quote's own approval", () => {
    const spec = elementOf("approval")!;
    const status = spec.status?.({ caseId: CASE, element: { type: "approval", step: "premium", data: null },
      page: page("line_draft@1"), onChanged: () => {} });
    expect(status).toBe(null);  // the quote's own status line: nothing to say without its view
  });
});
