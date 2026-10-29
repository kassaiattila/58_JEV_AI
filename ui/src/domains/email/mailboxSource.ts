// 231 (plan stage C, C3e): a mailbox download as a workflow step's source in the new work wizard - the step's draft,
// the stored source it makes and its words on the workflow's page. Until C3e the wizard (`views/workflows/NewWork.tsx`)
// and the workflow's words (`views/workflows/labels.ts`) held them; the email domain registers them with its chooser
// (`./index.tsx`). A small module, so the interface's start does not load the mailbox screens.
import type { CaseSource, WorkflowSource, WorkflowStep } from "../../api";
import type { MailboxRequest } from "./api";
import { t } from "../../i18n";

/** The part of the new work wizard's step draft a mailbox download fills. */
export type MailboxStepDraft = { accounts: string; folders: string; maxItems: number; usePeriod: boolean; days: number };

export function splitAccounts(value: string): string[] {
  return value.split(",").map((a) => a.trim()).filter(Boolean);
}

/** 147: a repeated workflow's step from its stored download; a new step's takes the workflow's period when it has one. */
export function stepDraft(stored: WorkflowSource | null, hasPeriod: boolean): MailboxStepDraft {
  const r = stored?.request;
  if (!r) return { accounts: "", folders: "Inbox", usePeriod: hasPeriod, days: 31, maxItems: 0 };
  return { accounts: r.accounts.join(", "), folders: (r.folders ?? ["Inbox"]).join(", "), usePeriod: !r.since_days,
    days: r.since_days ?? 31, maxItems: r.max_items ?? 0 };
}

/** 181: the stored source (null while no address is given): the workflow's period, or (no period) a number of days. */
export function stepSource(d: MailboxStepDraft, period: [string, string]): WorkflowSource | null {
  const accounts = splitAccounts(d.accounts);
  if (!accounts.length) return null;
  const request: MailboxRequest = {
    accounts, folders: d.folders.split(",").map((f) => f.trim()).filter(Boolean), max_items: d.maxItems,
    ...(d.usePeriod ? { received_from: period[0], received_to: period[1] } : { since_days: d.days }),
  };
  return { kind: "mailbox", request };
}

export function stepWords(s: WorkflowStep["source"]): string {
  return t("mailbox {{accounts}}", { accounts: (s.accounts ?? []).join(", ") });
}

/** 231 (U3): a mailbox case's download in a few words, for its name when a person gives none: the mailbox and the
 *  period ("anna@example.com · 2026-10-01 – 2026-10-28", or the last days). */
export function caseName(source: CaseSource): string {
  const r = source.request;
  if (!r) return "";
  const period = r.since_days ? t("the last {{n}} days", { n: r.since_days })
    : [r.received_from, r.received_to].filter(Boolean).join(" – ");
  return [r.accounts.join(", "), period].filter(Boolean).join(" · ");
}
