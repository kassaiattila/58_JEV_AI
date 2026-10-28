// 231 (plan stage C, C3e; DECISIONS 231): the email domain's screens on the interface, registered when it loads, as the
// service's email domain registers its addresses and source kind (`jav/domains/email/__init__.py`): a mailbox download
// as a source (a mailbox case's general form, a workflow step in the new work wizard) and Settings › Mailboxes. The
// screens load on first use; only the step's draft and words (`./mailboxSource.ts`) load with the interface.
import { lazyPage } from "../../components/LazyPage";
import { registerSourceChooser } from "../../elements/sourceChoosers";
import { registerSettingsSection } from "../../logic/settingsSections";
import { stepDraft, stepSource, stepWords, type MailboxStepDraft } from "./mailboxSource";

const screens = () => import("./Mailbox");
const MailboxRequestFields = lazyPage(() => screens().then((m) => m.MailboxRequestFields));
const MailboxStepFields = lazyPage(() => screens().then((m) => m.MailboxStepFields));
const Mailbox = lazyPage(() => screens().then((m) => m.Mailbox));

// 048 T2 / 231 C3d: a mailbox download (its addresses, folders and period)
registerSourceChooser<MailboxStepDraft>("mailbox", {
  label: "A mailbox",
  Case: ({ onChange }) => <MailboxRequestFields onChange={(req) => onChange(req ? { kind: "mailbox", request: req } : null)} />,
  step: { draft: stepDraft, Fields: (p) => <MailboxStepFields {...p} />, source: stepSource },
  words: stepWords,
});

registerSettingsSection({
  key: "mailboxes", label: "Postafiókok", hint: "Outlook-fiókok, ütemezett letöltés, letöltési napló", group: "system", order: 340, Panel: Mailbox,
});
