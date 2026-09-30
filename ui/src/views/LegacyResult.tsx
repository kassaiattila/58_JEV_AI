// Redirect of the old report and data addresses (054–056) (057): to the Result section of the run's work package, with
// the run and the table. Replacing the address does not add a new history entry (the Back button does not jump back
// here).
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
