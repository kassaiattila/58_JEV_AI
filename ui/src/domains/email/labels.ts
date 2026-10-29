// 183: a mailbox download's words in the interface's language. 261: the email domain's (until then in the shared
// `ui/src/labels.ts`); the domain gives a mailbox package's origin to the shared item list through its source chooser
// (`./index.tsx`).
import type { Workpackage, WorkpackageView } from "../../api";
import { t } from "../../i18n";
import type { MailboxRequest } from "./api";

/** 183: a download's mailbox, folders and period in one line, in the interface's language (the service's label and a
 *  package's stored source are English or, before 183, Hungarian text). */
export function mailboxLabel(r: MailboxRequest): string {
  const period = r.received_from ? `${r.received_from}–${r.received_to ?? ""}` : t("last {{n}} days", { n: r.since_days ?? 1 });
  return [r.accounts.join(", "), (r.folders?.length ? r.folders : ["Inbox"]).join(", "), period].join(" · ");
}

/** 183: a stored download label (a mailbox package's source when no recorded download made it) with its last-days
 *  period in the interface's language; the service wrote it in Hungarian before 183 and in English since. */
export function storedMailboxLabel(label: string): string {
  // the Hungarian period is matched with the accented letter escaped (stored data, not interface text)
  return label.replace(/(?:utols\u00f3 (\d+) nap|last (\d+) days)$/, (_m, hu: string | undefined, en: string | undefined) =>
    t("last {{n}} days", { n: Number(hu ?? en) }));
}

/** 183: where a mailbox package came from: the download that made it, or its stored label. */
export function mailboxOrigin(wp: Workpackage, view?: Pick<WorkpackageView, "mailbox_request"> | null): string {
  const ref = wp.source_ref ?? "";
  const file = ref.split(/[\\/]/).pop() ?? ref;
  const request = view?.mailbox_request;
  return t("mailbox {{name}}", { name: request ? mailboxLabel(request) : storedMailboxLabel(file) });
}
