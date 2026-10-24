// 231 (plan stage A, A7e; DECISIONS 231): a case's general elements and the case list. The Sent tab sends the letter by
// starting the case's step and lists each attempt; an unknown arrival asks the person through the step's own actions;
// the Follow-up tab records the reply; the History tab shows the case's events and what its steps spent; the case list
// shows the handovers to check above the cases only while there are some. Synthetic data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type DsPage } from "../api";
import { setLanguage } from "../i18n";
import { CaseList } from "./CaseList";
import { CasePage } from "./CasePage";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const CASE = "wp-000000000231";
const step = (state: string, extra: Partial<CaseView["steps"][string]> = {}) => ({
  title: null, uses: "x@1", start: "auto" as const, state, phase: null, waiting_for: null, awaiting_start: false, note: null,
  result: null, actions: [], ...extra,
});
const sentTo = { mode: "output_folder", file_name: "Ajanlat-Invented-v1.eml", to: "buyer@example.com", subject: "Quote", size: 2048 };

function page(over: { send?: Partial<CaseView["steps"][string]>; follow?: Partial<CaseView["steps"][string]>;
                      handovers?: unknown; reply?: unknown; next?: CaseView["next"]; status?: string }): CaseView {
  return {
    case: { id: CASE, pack: "it_quote", version: "1.1.0", title: "IT quote", name: "Quote: Invented Buyer Ltd", status: over.status ?? "open" },
    steps: { letter: step("done"), send: step("running", over.send), follow_up: step("waiting", over.follow) },
    tabs: [
      { id: "sent", label: "Sent", elements: [{ type: "handover_view", step: "send", data: over.handovers ?? {
        mode: "output_folder", message: "quote_letter", state: "running", output_folder: "D:\\Invented\\out", attempts: [] } }] },
      { id: "follow_up", label: "Follow-up", elements: [{ type: "reply_wait", step: "follow_up", data: over.reply ?? {
        state: "waiting", since: null, remind_at: null, reminded_at: null, follow_up: null, reply: null, by: null, at: null, note: null } }] },
      { id: "history", label: "History", elements: [
        { type: "timeline", step: null, data: { events: [
          { at: "2026-10-24T10:00:00+00:00", kind: "started", step: null, step_title: null, who: "anna", detail: {} },
          { at: "2026-10-24T10:05:00+00:00", kind: "task_decided", step: "send", step_title: "Send", who: "anna",
            detail: { task_kind: "handover_settle", answer: "acknowledged" } }] } },
        { type: "cost", step: null, data: { total_usd: "0.0040", lines: [
          { step: "match", step_title: "Proposal", provider: "jev", calls: 2, reused: 1, cost_usd: "0.0040", open_usd: "0" }] } }] },
    ],
    next: over.next ?? { code: "case_send", label: "Send", stage: "result", tab: "sent" },
  };
}

describe("a case's send, follow-up and history (231 A7e)", () => {
  it("sends the accepted letter by starting the case's step, from the Sent tab", async () => {
    vi.spyOn(api, "casePage").mockResolvedValue(page({ send: { start: "person", awaiting_start: true, phase: "awaiting_start" } }));
    const start = vi.spyOn(api, "startCaseStep").mockResolvedValue(page({}));
    render(<CasePage caseId={CASE} tab="sent" />);
    const card = await screen.findByRole("region", { name: "Sending" });
    expect(within(card).getByText("Ready to send")).toBeTruthy();
    expect(within(card).getByText("D:\\Invented\\out")).toBeTruthy();
    expect(within(card).getByText(/written into the output folder as an email file/)).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Send" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith(CASE, "send"));
  });

  it("lists each attempt and asks the person whether an interrupted handover arrived", async () => {
    const handovers = { mode: "output_folder", message: "quote_letter", state: "running", output_folder: "D:\\Invented\\out", attempts: [
      { attempt: 1, status: "failed", error: "no output folder is set", created_at: null, updated_at: "2026-10-24T09:00:00+00:00", receipt: null, ...sentTo },
      { attempt: 2, status: "uncertain", error: "OSError: the share stopped", created_at: null, updated_at: "2026-10-24T09:10:00+00:00", receipt: null, ...sentTo }] };
    vi.spyOn(api, "casePage").mockResolvedValue(page({ handovers, send: { waiting_for: "task_closed", actions: [
      { name: "delivered", label: "It arrived" }, { name: "not_delivered", label: "It did not arrive" }] },
      next: { code: "case_send_settle", label: "Say whether it arrived", stage: "result", tab: "sent" } }));
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue(page({}));
    render(<CasePage caseId={CASE} tab="sent" />);
    const card = await screen.findByRole("region", { name: "Sending" });
    expect(within(card).getByText(/not known whether the message arrived/)).toBeTruthy();
    const rows = within(within(card).getByRole("table", { name: "Handovers" })).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1].textContent).toContain("Failed");
    expect(rows[2].textContent).toContain("Arrival unknown");
    fireEvent.click(within(card).getByRole("button", { name: "It arrived" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "send", "delivered"));
  });

  it("records the reply on the Follow-up tab once the follow-up opened", async () => {
    const reply = { state: "running", since: "2026-10-19T10:00:00+00:00", remind_at: "2026-10-24T10:00:00+00:00",
                    reminded_at: "2026-10-24T10:00:01+00:00", follow_up: "open", reply: null, by: null, at: null, note: null };
    vi.spyOn(api, "casePage").mockResolvedValue(page({ reply, send: { state: "done" }, follow: { state: "running", waiting_for: "task_closed",
      actions: [{ name: "replied", label: "A reply arrived" }, { name: "not_needed", label: "No reply is needed" },
                { name: "keep_waiting", label: "I reminded them, keep waiting" }] },
      next: { code: "case_follow_up", label: "Follow up the reply", stage: "result", tab: "follow_up" } }));
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue(page({}));
    render(<CasePage caseId={CASE} tab="follow_up" />);
    const card = await screen.findByRole("region", { name: "Follow-up" });
    expect(within(card).getByText("Follow up the reply")).toBeTruthy();
    expect(within(card).getByText(/No reply came in the days the process sets/)).toBeTruthy();
    // the follow-up is the person's turn: recording the reply is the card's one solid button
    expect(within(card).getByRole("button", { name: "A reply arrived" }).className).toBe("primary");
    fireEvent.click(within(card).getByRole("button", { name: "I reminded them, keep waiting" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "follow_up", "keep_waiting"));
  });

  it("shows the case's events and what its steps spent on the History tab", async () => {
    vi.spyOn(api, "casePage").mockResolvedValue(page({ status: "closed", next: null, send: { state: "done" }, follow: { state: "done" } }));
    render(<CasePage caseId={CASE} tab="history" />);
    const events = await screen.findByRole("region", { name: "Events" });
    expect(within(events).getByText("The case started")).toBeTruthy();
    expect(within(events).getByText("Said whether it arrived — it arrived")).toBeTruthy();
    const cost = screen.getByRole("region", { name: "Cost" });
    expect(within(cost).getByText("JEV")).toBeTruthy();
    expect(within(cost).getAllByText(/0[.,]00 USD/).length).toBeGreaterThan(0);
  });
});

describe("the case list (231 A7e)", () => {
  const ds = (name: string, rows: Record<string, unknown>[]): DsPage => ({
    dataset: { name, label: name, scope: [], optional_scope: [], one_of: [], natural_sort: [] },
    columns: [{ key: "name", label: "Case", kind: "text", hidden: false, labels: null, extra: { link: "workpackage" } }],
    rows, total: rows.length, matched: rows.length, offset: 0, limit: 50, facets: {},
  } as unknown as DsPage);

  it("shows the handovers to check above the cases only while there are some", async () => {
    const query = vi.spyOn(api, "datasetQuery").mockImplementation(async (name) =>
      name === "handovers" ? ds("handovers", [{ name: "Quote A", _key: "h1", _wp: CASE }]) : ds("cases", [{ name: "Quote A", _key: CASE, _wp: CASE }]));
    render(<CaseList />);
    expect(await screen.findByRole("heading", { name: "Handovers to check" })).toBeTruthy();
    expect(query).toHaveBeenCalledWith("cases", {}, expect.anything());
    cleanup();
    query.mockImplementation(async (name) => ds(name, name === "handovers" ? [] : [{ name: "Quote A", _key: CASE, _wp: CASE }]));
    render(<CaseList />);
    expect(await screen.findAllByText("Quote A")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Handovers to check" })).toBeNull();
  });
});
