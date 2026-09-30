// Mai munkám (061 döntés: aktív felhasználó + kiosztás): a „Ki dolgozik?” személy napi műveletei — recept, futás
// indítása és jóváhagyása, javítás, teendő lezárása, feladatjavaslat-döntés, csomag-események, postafiók-letöltés.
// A régi V4 „Mai munkám” nézetének mintája; a nap választható (alapból a mai).
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { useActor } from "../hooks";
import { t, useLocale } from "../i18n";
import { MODE, reasonText } from "../labels";
import { go } from "../route";

/** A helyi naptári nap ÉÉÉÉ-HH-NN alakban. */
export function localDay(d = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** A művelet részlete feliratként (062): a teendő oka hétköznapi mondatban, a döntés és a mód magyarul; a recept címét
 *  a szolgáltatás adja (a felület fordítja). A többi (pl. postafiók címe) változatlan. */
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
