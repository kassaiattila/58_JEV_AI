// Mai munkám (My work today; 061 decision: active user + assignment): the daily actions of the „Ki dolgozik?” (Who is
// working?) person — recipe, starting and approving a run, correction, closing a to-do, task proposal decision, work
// package events, mailbox download; 231 (U2d): a person's steps and decisions on the cases. Modelled on the old V4 „Mai munkám” view; the day can be chosen (today by default).
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { useActor } from "../hooks";
import { t, useLocale } from "../i18n";
import { fieldLabel, MODE, reasonText } from "../labels";
import { go } from "../route";

/** The local calendar day in YYYY-MM-DD form. */
export function localDay(d = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The action's detail as a label (062): the to-do's reason as an everyday sentence, the decision and the mode in
 *  Hungarian; the processing's title comes from the local service (the UI translates it). The rest (e.g. a mailbox address)
 *  is unchanged. */
export function activityDetail(action: string, detail: string | null | undefined): string {
  if (!detail) return "";
  switch (action) {
    case "reason_resolve": return reasonText(detail);
    case "task_decision": return detail === "accepted" ? t("accepted") : detail === "rejected" ? t("rejected") : detail;
    case "run_start": return MODE[detail] ?? detail;
    case "run_approve": return t("approved");
    case "recipe": return t(detail);
    // 167 (review 153 E): the corrected fields by their labels
    case "correction": return detail.split(",").map((f) => fieldLabel(f)).join(", ");
    default: return detail;
  }
}

export function Activity({ day }: { day?: string }) {
  useLocale();
  const actor = useActor();
  const today = localDay();
  const d = day ?? today;
  const title = d === today ? t("My work today") : t("My work: {{day}}", { day: d });
  if (!actor) {
    return <PageHeader title={title} summary={t("Select your name above in the “Who is working?” field; your actions of the day are shown here.")} />;
  }
  return (
    <>
      <PageHeader title={title} summary={t("{{name}}'s actions on the day: steps and decisions on the cases, processing settings, starting and approving runs, corrections, closing to-dos, task-proposal decisions, batch changes, mailbox downloads.", { name: actor })} />
      {/* 263 (F3): the list keeps its state; the day stands in its toolbar */}
      <DataTable dataset="activity" scope={{ actor, day: d }} label={t("Activity log")} storageId="activity" persist="activity"
        toolbar={
          <label className="check small">{t("Day")}
            <input type="date" value={d} max={today} onChange={(e) => go({ view: "activity", day: e.target.value && e.target.value !== today ? e.target.value : undefined })} />
          </label>
        }
        emptyText={t("You have no recorded actions on this day.")}
        cell={(col, row) => (col.key === "detail" ? activityDetail(String(row.action), row.detail as string | null) || undefined : undefined)} />
    </>
  );
}
