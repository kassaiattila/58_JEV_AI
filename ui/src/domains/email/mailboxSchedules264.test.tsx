// 264 (plan E, F5-F6; the owner's decision of 2026-10-31): Settings › Mailboxes builds its pages the one way - the
// schedules are the one list, "New schedule" the title row's main action, a schedule its own page with its own downloads
// - and the one-off download of a date range goes to a new mailbox case (the schedule's form could only count it).
// Synthetic mailboxes, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DsQuery } from "../../api";
import type { MailboxSchedule } from "./api";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { findConfirmAction } from "../../confirm.testutil";
import { linkCol, listPage } from "../../views/settings/listPage.testutil";
import { Mailbox } from "./Mailbox";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic owner"); sessionStorage.clear(); window.location.hash = ""; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const SCHEDULE: MailboxSchedule = {
  id: "sch-0000000001", request: { accounts: ["office@example.com"], folders: ["Inbox"], subfolders: false, since_days: 3, max_items: 0 },
  label: "office@example.com · Inbox · last 3 days", interval_min: 60, enabled: true, actor: "Synthetic owner",
  next_at: "2026-10-31T10:00:00+00:00", last_at: null, last_status: null, last_result: null,
} as MailboxSchedule;

function service() {
  vi.spyOn(api, "mailbox").mockResolvedValue({ schedules: [SCHEDULE], pulls: [], bridge_available: true, accounts: ["office@example.com"],
    defaults: { interval_min: 60, lookback_days: 3 } });
  return vi.spyOn(api, "datasetQuery").mockImplementation(async (name: string, _scope: unknown, _q: DsQuery) => name === "mailbox_schedules"
    ? listPage(name, [linkCol("label", "Reads", "mailboxes")], [{ _key: SCHEDULE.id, label: SCHEDULE.label, _request: SCHEDULE.request }])
    : listPage(name, [], []));
}

describe("Settings › Mailboxes", () => {
  it("lists the schedules, each opening its page; a new schedule and a one-off download are the title row's actions", async () => {
    const query = service();
    render(<Mailbox />);
    expect(screen.getByRole("link", { name: "New schedule" }).getAttribute("href")).toBe("#/settings/mailboxes/new");
    expect(screen.getByRole("link", { name: "Download once, in a new case" }).getAttribute("href")).toBe("#/cases/new/mailbox");
    const table = await screen.findByRole("table", { name: "Mailbox schedules" });
    expect(within(table).getByRole("link", { name: "office@example.com · Inbox · last 3 days" }).getAttribute("href"))
      .toBe("#/settings/mailboxes/sch-0000000001");
    expect(query.mock.calls.map((c) => c[0])).toEqual(expect.arrayContaining(["mailbox_schedules", "mailbox_pulls"]));
  });

  it("saves a new schedule of the last days, with no date range to choose, and opens it", async () => {
    service();
    const create = vi.spyOn(api, "createSchedule").mockResolvedValue(SCHEDULE);
    render(<Mailbox item="new" />);
    expect(screen.queryByRole("radio", { name: "Date range" })).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: /Mailbox address/ }), { target: { value: "office@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({ accounts: ["office@example.com"], since_days: 7 }), 60));
    await waitFor(() => expect(window.location.hash).toBe("#/settings/mailboxes/sch-0000000001"));
  });

  it("changes a schedule on its page, deletes it there, and lists its own downloads", async () => {
    const query = service();
    const update = vi.spyOn(api, "updateSchedule").mockResolvedValue({ ...SCHEDULE, enabled: false });
    const remove = vi.spyOn(api, "deleteSchedule").mockResolvedValue({ deleted: SCHEDULE.id });
    render(<Mailbox item="sch-0000000001" />);
    const sheet = await screen.findByRole("region", { name: "Schedule" });
    fireEvent.click(within(sheet).getByRole("checkbox", { name: /On/ }));
    fireEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("sch-0000000001", { interval_min: 60, enabled: false }));
    fireEvent.click(within(sheet).getByRole("button", { name: "Delete" }));
    fireEvent.click(await findConfirmAction());
    await waitFor(() => expect(remove).toHaveBeenCalledWith("sch-0000000001"));
    expect(query.mock.calls.some((c) => c[0] === "mailbox_pulls" && JSON.stringify(c[1]) === JSON.stringify({ schedule_id: "sch-0000000001" })))
      .toBe(true);
  });

  it("has its words in Hungarian", () => {
    const hu = hungarian as Record<string, string>;
    for (const key of ["New schedule", "Download once, in a new case", "Mailbox schedules", "Its downloads", "On (value)",
      "Off (value)", "Last download", "On: it downloads by itself", "Schedule",
      "Delete this schedule? Its downloads so far stay in the log."]) {
      expect(hu[key], key).toBeTruthy();
      expect(hu[key]).not.toBe(key);
    }
  });
});
