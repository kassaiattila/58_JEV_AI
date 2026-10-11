import { useState } from "react";
import { DataTable, linkOf } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { useActor } from "../hooks";
import { t, useLocale } from "../i18n";
import { RUN_STATUS, stepLabel } from "../labels";
import { go, type Route } from "../route";
import { WorkpackageDetail } from "./WorkpackageDetail";
import { NewWork } from "./workflows/NewWork";

export function Workpackages({ route }: { route: Extract<Route, { view: "workpackages" }> }) {
  if (route.wpId) return <WorkpackageDetail route={route} wpId={route.wpId} />;
  return <WorkpackageList />;
}

function WorkpackageList() {
  useLocale();
  const [creating, setCreating] = useState(false);
  const [count, setCount] = useState<number | null>(null);
  const [archived, setArchived] = useState(false); // 058: hidden work packages are only shown on request
  const [mine, setMine] = useState(false); // 061: only those whose owner is the „Ki dolgozik?” (Who is working?) person
  const actor = useActor();
  const scope = { ...(archived ? { include_archived: "1" } : {}), ...(mine && actor ? { owner: actor } : {}) };
  return (
    <>
      <PageHeader title={t("Munkacsomagok")} badge={count !== null ? <span className="count">{count}</span> : null}
        summary={t("Egy munkacsomag iratai együtt futnak: feldolgozás, ellenőrzés, eredmény. A „Következő lépés” oszlop megmutatja, hol tart.")}
        actions={<button type="button" className="primary" onClick={() => setCreating((v) => !v)} aria-expanded={creating}>{t("Új munkacsomag")}</button>} />
      {creating ? <CreateForm onDone={(id) => go({ view: "workpackages", wpId: id, stage: "process" })} /> : null}
      <DataTable dataset="workpackages" label={t("Munkacsomagok")} onPage={(pg) => setCount(pg.total)} pollMs={10000}
        scope={Object.keys(scope).length ? scope : undefined}
        toolbar={<>
          <label className="check small" title={actor ? undefined : t("Előbb válaszd ki a neved fent")}>
            <input type="checkbox" checked={mine && Boolean(actor)} disabled={!actor} onChange={(e) => setMine(e.target.checked)} /> {t("Csak a saját csomagjaim")}
          </label>
          <label className="check small"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> {t("Elrejtett csomagok is")}</label>
        </>}
        cell={(col, row) => (col.key === "next_label" ? (
          // the next step in the chosen language (from the local service's code), with a link to the stage
          <a href={linkOf(col, row) ?? "#/workpackages"}>{stepLabel(String(row.next_code), row._next_params as Record<string, unknown>, String(row.next_label))}</a>
        ) : undefined)}
        emptyText={t("Még nincs munkacsomag. Az „Új munkacsomag” gombbal mappából, fájlokból vagy postafiókból hozhatsz létre.")} />
    </>
  );
}

// 081: exported for its tests. 140: the goal first, then its source. 146 (DECISIONS 146): the new work wizard over the
// templates of `configs/workflows.json` (a single kind makes a work package as before; a workflow goes to its page);
// `initialTemplate` opens a template's form at once.
export function CreateForm({ onDone, initialTemplate }: { onDone: (id: string) => void; initialTemplate?: string }) {
  return <NewWork onPackage={onDone} onWorkflow={(id) => go({ view: "workflows", wfId: id })} initialTemplate={initialTemplate} />;
}

export function RunStatus({ status }: { status: string }) {
  useLocale();
  return <span className={`status s-${status}`}>{RUN_STATUS[status] ?? status}</span>;
}
