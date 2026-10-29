// 183 (backlog N-angol-felulet-maradek): a download's label and a mailbox package's source in the interface's language,
// from the download's request (they were stored Hungarian text). Artificial data, no service.
import { afterEach, expect, it } from "vitest";
import type { Workpackage, WorkpackageView } from "../../api";
import { setLanguage } from "../../i18n";
import { mailboxLabel, storedMailboxLabel } from "./labels";
import { createdFrom } from "../../views/PackageItems";

afterEach(async () => { await setLanguage("hu"); });

const RECENT = { accounts: ["office@example.com"], folders: ["Sent Items"], since_days: 90 };
const RANGE = { accounts: ["office@example.com"], received_from: "2026-09-01", received_to: "2026-09-10" };
const WP = { id: "wp-000000000001", name: "Mailbox", source_kind: "mailbox", source_ref: "office@example.com · Sent Items · utols\u00f3 90 nap",
  revision: 1, status: "open" } as unknown as Workpackage;

it("writes a download's label in the interface's language", async () => {
  await setLanguage("en");
  expect(mailboxLabel(RECENT)).toBe("office@example.com · Sent Items · last 90 days");
  expect(mailboxLabel(RANGE)).toBe("office@example.com · Inbox · 2026-09-01–2026-09-10");
  await setLanguage("hu");
  expect(mailboxLabel(RECENT)).toBe("office@example.com · Sent Items · utols\u00f3 90 nap");
});

it("names a mailbox package's source from the request of the download that made it", async () => {
  await setLanguage("en");
  expect(createdFrom(WP, { mailbox_request: RECENT } as WorkpackageView)).toBe("mailbox office@example.com · Sent Items · last 90 days");
  // no recorded download: the stored label, its period (Hungarian before 183, English since) in the interface's language
  expect(createdFrom(WP)).toBe("mailbox office@example.com · Sent Items · last 90 days");
  expect(storedMailboxLabel("office@example.com · Inbox · last 3 days")).toBe("office@example.com · Inbox · last 3 days");
  await setLanguage("hu");
  expect(storedMailboxLabel("office@example.com · Inbox · last 3 days")).toBe("office@example.com · Inbox · utols\u00f3 3 nap");
  expect(storedMailboxLabel("office@example.com · Inbox · 2026-09-01–2026-09-10")).toBe("office@example.com · Inbox · 2026-09-01–2026-09-10");
});
