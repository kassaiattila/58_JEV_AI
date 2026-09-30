// Mai munkám (My work today; 061 decision: active user + assignment): the daily actions of the „Ki dolgozik?” (Who is
// working?) person — recipe, starting and approving a run, correction, closing a to-do, task proposal decision, work
// package events, mailbox download. Modelled on the old V4 „Mai munkám” view; the day can be chosen (today by default).
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { useActor } from "../hooks";
import { t, useLocale } from "../i18n";
import { MODE, reasonText } from "../labels";
import { go } from "../route";

/** The local calendar day in YYYY-MM-DD form. */
export function localDay(d = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The action's detail as a label (062): the to-do's reason as an everyday sentence, the decision and the mode in
 *  Hungarian; the recipe title comes from the local service (the UI translates it). The rest (e.g. a mailbox address)
 *  is unchanged. */
export function activityDetail(action: string, detail: string | null | undefined): string {
  if (!detail) return "";
  switch (action) {
    case "reason_resolve": return reasonText(detail);
    case "task_decision": return detail === "accepted" ? t("elfogadva") : detail === "rejected" ? t("elvetve") : detail;
    case "run_start": return MODE[detail] ?? detail;
    case "run_approve": return t("jóváhagyva");
    case "recipe": return t(detail);
    default: return detail;
  }
}

export function Activity({ day }: { day?: string }) {
  useLocale();
  const actor = useActor();
  const today = localDay();
  const d = day ?? today;
  const title = d === today ? t("Mai munkám") : t("Munkám: {{day}}", { day: d });
  if (!actor) {
    return <PageHeader title={title} summary={t("Válaszd ki fent a neved a „Ki dolgozik?” mezőben; itt a napi műveleteidet látod.")} />;
  }
  return (
    <>
      <PageHeader title={title} summary={t("{{name}} műveletei a napon: recept, futás indítása és jóváhagyása, javítás, teendő lezárása, feladatjavaslat-döntés, csomag-módosítás, postafiók-letöltés.", { name: actor })}
        actions={
          <label className="check small">{t("Nap")}
            <input type="date" value={d} max={today} onChange={(e) => go({ view: "activity", day: e.target.value && e.target.value !== today ? e.target.value : undefined })} />
          </label>
        } />
      <DataTable dataset="activity" scope={{ actor, day: d }} label={t("Tevékenységnapló")} storageId="activity"
        emptyText={t("Ezen a napon nincs rögzített műveleted.")}
        cell={(col, row) => (col.key === "detail" ? activityDetail(String(row.action), row.detail as string | null) || undefined : undefined)} />
    </>
  );
}
