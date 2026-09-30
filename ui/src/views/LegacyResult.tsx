// Régi riport- és adat-címek (054–056) átirányítása (057): a futás csomagjának Eredmény szakaszára, a futással és a
// táblával együtt. A címsor cseréje nem hoz új előzmény-bejegyzést (a Vissza gomb nem ide ugrik vissza).
import { useEffect } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { routeHash, type ResultTable } from "../route";

export function LegacyResult({ runId, table }: { runId?: string; table?: ResultTable }) {
  useLocale();
  const run = useLoad(runId ? `run:${runId}` : null, () => api.run(runId!));
  const wpId = run.data?.run.workpackage_id;
  useEffect(() => {
    if (!runId) window.location.replace(routeHash({ view: "workpackages" }));
    else if (wpId) window.location.replace(routeHash({ view: "workpackages", wpId, stage: "result", runId, table }));
  }, [runId, wpId, table]);
  if (run.error) return <p className="notice error" role="alert">{t("A régi címben szereplő futás nem található.")} <a href="#/workpackages">{t("Munkacsomagok")}</a></p>;
  return <p className="muted">{t("Átirányítás a munkacsomag eredményéhez…")}</p>;
}
