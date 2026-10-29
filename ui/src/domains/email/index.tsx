// 231 (plan stage C, C3e; DECISIONS 231): the email domain's screens on the interface, registered when it loads, as the
// service's email domain registers its addresses and source kind (`jav/domains/email/__init__.py`): a mailbox download
// as a source (a mailbox case's general form, a workflow step in the new work wizard) and Settings › Mailboxes. The
// screens load on first use; only the step's draft and words (`./mailboxSource.ts`) load with the interface.
// 261 (the consolidation round, DECISIONS 261): the rest of the domain's interface, until then in the shared code: its
// calls on the shared client (`./api.ts`), an email item's review, the file placement's element of a case's tabs, a
// mailbox package's origin, an old email package's notice in Processing and the mailboxes' old address (`#/mailbox`).
import { lazy } from "react";
import { registerCalls } from "../../api";
import { lazyPage } from "../../components/LazyPage";
import { lazily, registerElement } from "../../elements/registry";
import { registerSourceChooser } from "../../elements/sourceChoosers";
import { registerProcessNotice } from "../../logic/processNotices";
import { registerSettingsSection } from "../../logic/settingsSections";
import { registerItemReview } from "../../review/itemReviews";
import { emailApi } from "./api";
import { AttachmentsNotice } from "./AttachmentsNotice";
import { EmailReview } from "./EmailReview";
import { mailboxOrigin } from "./labels";
import { caseName, stepDraft, stepSource, stepWords, type MailboxStepDraft } from "./mailboxSource";
import { placementLine, placementSummary } from "./placementStatus";

registerCalls(emailApi);

const screens = () => import("./Mailbox");
const MailboxRequestFields = lazyPage(() => screens().then((m) => m.MailboxRequestFields));
const MailboxStepFields = lazyPage(() => screens().then((m) => m.MailboxStepFields));
const Mailbox = lazyPage(() => screens().then((m) => m.Mailbox));

// 048 T2 / 231 C3d: a mailbox download (its addresses, folders and period); 183: a mailbox package's origin
registerSourceChooser<MailboxStepDraft>("mailbox", {
  label: "A mailbox",
  Case: ({ onChange, initial }) => <MailboxRequestFields initial={initial?.request ?? null}
    onChange={(req) => onChange(req ? { kind: "mailbox", request: req } : null)} />,
  step: { draft: stepDraft, Fields: (p) => <MailboxStepFields {...p} />, source: stepSource },
  words: stepWords,
  name: caseName,
  createdFrom: mailboxOrigin,
});

registerSettingsSection({
  key: "mailboxes", label: "Mailboxes", hint: "Outlook accounts, scheduled download, download log", group: "system", order: 340, Panel: Mailbox,
  aliases: ["mailbox"],  // 057: the old address leads to Settings
});

// 048 T2: an email item's review: the email, its intent, the next step and the task proposals (with the review page,
// as before 261)
registerItemReview("email", ({ data, wpId, onChanged }) => (data.email ? <EmailReview data={data} wpId={wpId} onChanged={onChanged} /> : null));

// 231 (C1c): the file placement capability's element (its page loads only when a case shows it)
const FilePlacement = lazy(() => import("./FilePlacement").then((m) => ({ default: m.FilePlacement })));
registerElement("file_placement", { render: lazily(FilePlacement), status: placementLine, summary: placementSummary });

// 058 K5.2: an email package from before 058 whose PDF attachments are not items yet
registerProcessNotice(AttachmentsNotice);
