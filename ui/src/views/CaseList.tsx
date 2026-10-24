// 231 (plan stage A, A7e; DECISIONS 231): the cases of the process packs. Every open case with the step it is at and
// what that step waits for (a person's start or decision, the other side's reply, the machine's work); the closed ones
// on request. Above them, only while there are some, the handovers to check: the cases whose last attempt to send
// something failed or has an unknown outcome. The rows come from the `cases` and `handovers` datasets
// (jav/app/case_lists.py); a case's name opens its page.
import { useState } from "react";
import { api, type DsColumn, type DsRow } from "../api";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";

/** The pack's own texts (its title, its steps' titles) and a handover's error are the interface's to translate. */
const TRANSLATED = new Set(["process", "step", "error"]);
/** What a case waits for as a state mark: a person's turn orange, the other side grey, the machine blue, a failure red. */
const WAIT_MARK: Record<string, string> = {
  person_start: "s-review", person: "s-review", reply: "s-waiting", work: "s-running", failed: "s-failed",
};
const cell = (col: DsColumn, row: DsRow) => {
  const value = row[col.key];
  if (col.key === "waits_for" && typeof value === "string" && WAIT_MARK[value]) {
    return <span className={`status ${WAIT_MARK[value]}`}>{t(col.labels?.[value] ?? value)}</span>;
  }
  return TRANSLATED.has(col.key) && typeof value === "string" && value ? t(value) : undefined;
};

export function CaseList() {
  useLocale();
  const [closed, setClosed] = useState(false);
  const toCheck = useLoad("handovers:count", () => api.datasetQuery("handovers", {}, { limit: 1 }), 30000);
  const title = t("Cases");
  return (
    <>
      <PageHeader title={title}
        summary={t("Every case of the processes: the step it is at and what that step waits for.")}
        actions={
          <label className="check small">
            <input type="checkbox" checked={closed} onChange={(e) => setClosed(e.target.checked)} />
            {t("Closed cases too")}
          </label>
        } />
      {toCheck.data && toCheck.data.total > 0 ? (
        <section className="case-list-check" aria-label={t("Handovers to check")}>
          <h2>{t("Handovers to check")}</h2>
          <DataTable dataset="handovers" label={t("Handovers to check")} storageId="handovers" pollMs={30000}
            emptyText={t("No handover waits for a check.")} cell={cell} />
        </section>
      ) : null}
      <DataTable dataset="cases" scope={closed ? { include_closed: "1" } : {}} label={title} storageId="cases" pollMs={30000}
        emptyText={closed ? t("There is no case yet.") : t("No case is open.")} cell={cell} />
    </>
  );
}
