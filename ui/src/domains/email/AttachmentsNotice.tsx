// 058 K5.2: in an email package from before 058 the PDF attachments are not items yet; once added, the email recipe
// extracts their data. 261: the email domain's notice in a package's Processing section (until then the section's own,
// `ui/src/views/ProcessStage.tsx`), its action run as the section's buttons (`ui/src/logic/processNotices.ts`).
import { api } from "../../api";
import { Icon } from "../../components/Icon";
import { t } from "../../i18n";
import type { ProcessNoticeProps } from "../../logic/processNotices";

export function AttachmentsNotice({ view, disabled, run }: ProcessNoticeProps) {
  const wp = view.workpackage;
  if (!view.attachments_missing) return null;
  return (
    <p className="notice">{t("{{n}} PDF attachments of the emails are not yet in the batch. Once added, the next run also extracts their data.", { n: view.attachments_missing })}
      {" "}<button type="button" className="secondary small-btn" disabled={disabled} onClick={() => void run(() => api.addAttachments(wp.id, wp.revision))}><Icon name="plus" />{t("Add attachments")}</button></p>
  );
}
