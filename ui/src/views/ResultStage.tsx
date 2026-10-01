// Result section (057, replacing Riportok (Reports) and Adatok (Data)): by default the work package's latest run; a run
// picker only if the work package has more than one run, and only from the work package's own runs. View switcher:
// Iratok · Adatpontok · Tételsorok · Közmű-költség · Fájlnevek (Documents · Data points · Line items · Utility cost ·
// File names, 078), with the shared table and download panel. The live run's approval is here (release, decision of
// 2026-09-28).
import { useState } from "react";
import { api, ApiError, getActor, type WorkpackageView } from "../api";
import { DataTable } from "../components/DataTable";
import { DatasetPicker, runOption } from "../components/DatasetPicker";
import { useLoad, useRunView } from "../hooks";
import { t, useLocale } from "../i18n";
import { nextFlowText, tmap, when } from "../labels";
import { go, type ResultTable } from "../route";
import { UtilityPanel } from "./UtilityReport";
import { Icon } from "../components/Icon";
import { ConfirmButton } from "../components/ConfirmButton";

const TABLES: { key: ResultTable; dataset: string }[] = [
  { key: "emails", dataset: "emails" },
  { key: "tasks", dataset: "email_tasks" },
  { key: "documents", dataset: "documents" },
  { key: "datapoints", dataset: "datapoints" },
  { key: "line_items", dataset: "line_items" },
  { key: "utility", dataset: "utility_cost" },
  { key: "file_names", dataset: "file_names" },
];
// the views' labels are translated when read (tmap)
const TABLE_LABEL = tmap({ emails: "Levelek", tasks: "Feladatok", documents: "Iratok", datapoints: "Adatpontok", line_items: "Tételsorok",
  utility: "Közmű-költség", file_names: "Fájlnevek" }) as Record<ResultTable, string>;

/** The default tab (062): Levelek (Emails) for an email work package, otherwise Adatpontok (Data points), failing
 *  that the first available view. */
export function defaultResultTable(available: ResultTable[]): ResultTable {
  if (available.includes("emails")) return "emails";
  if (available.includes("datapoints")) return "datapoints";
  return available[0] ?? "datapoints";
}

export function ResultStage({ view, table, runId, onChanged }: {
  view: WorkpackageView; table?: ResultTable; runId?: string; onChanged: () => void;
}) {
  useLocale();
  const wp = view.workpackage;
  const chosen = runId ?? view.last_run?.run_id ?? null;
  const run = useRunView(chosen);
  // 058: only the views that contain data (e.g. utility cost only for utility invoices); the local service says which
  const available = run.data?.tables ? TABLES.filter((x) => run.data!.tables!.includes(x.key)) : TABLES;
  const current: ResultTable = table && available.some((x) => x.key === table) ? table : defaultResultTable(available.map((x) => x.key));
  const nav = (next: { table?: ResultTable; runId?: string }) =>
    go({ view: "workpackages", wpId: wp.id, stage: "result", table: next.table ?? current, runId: next.runId ?? runId });

  if (!chosen) {
    return <div className="empty">{t("Még nincs eredmény: előbb futtasd a csomagot a")} <a href={`#/workpackages/${wp.id}/process`}>{t("Feldolgozás")}</a> {t("szakaszban.")}</div>;
  }
  const spec = TABLES.find((x) => x.key === current) ?? TABLES[1];
  return (
    <div className="stage-stack">
      <div className="result-bar">
        {view.runs > 1 ? (
          <DatasetPicker dataset="runs" scope={{ workpackage_id: wp.id }} label={t("Futás")} value={chosen} valueCol="run_id"
            toOption={runOption} onChange={(v) => nav({ runId: v })} />
        ) : null}
        <div className="segmented-tabs" role="tablist" aria-label={t("Eredmény nézetei")}>
          {available.map((x) => (
            <button key={x.key} type="button" role="tab" aria-selected={x.key === current} className="seg" onClick={() => nav({ table: x.key })}>{TABLE_LABEL[x.key]}</button>
          ))}
        </div>
        <span className="dt-spacer" />
        <a className="secondary dl-btn small-btn" href={api.exportUrl(chosen, "xlsx")} download><Icon name="download" />{t("Teljes Excel-csomag")}</a>
      </div>
      <Approval runId={chosen} onChanged={onChanged} />
      {run.data && !available.length ? <p className="notice">{t("Ennek a futásnak nincs irat-eredménye (például csak leveleket dolgozott fel).")}</p> : null}
      {current === "utility" ? <UtilityPanel runId={chosen} wpId={wp.id} /> : null}
      {current === "file_names" ? <NamedCopiesBar runId={chosen} /> : null}
      {available.length ? <DataTable key={`${spec.dataset}:${chosen}`} dataset={spec.dataset} scope={{ run_id: chosen }} label={TABLE_LABEL[spec.key]} selectable
        storageId={`result-${spec.dataset}`}
        // proposed next step in the chosen language (the local service gives the code; search uses the Hungarian label)
        cell={spec.key === "emails" ? (col, row) => (col.key === "next_flow" ? nextFlowText(row.next_flow as string | null) : undefined) : undefined}
        downloadExtras={<a className="small" href={api.exportUrl(chosen, "xlsx")} download>{t("A futás teljes Excel-csomagja (minden tábla és a közmű-költség)")}</a>} /> : null}
    </div>
  );
}

/** 078: copies of the documents under content-based names — as a ZIP, or into a new subfolder of the output folder
 *  (Settings › Work folders). The originals are never changed; uncertain names go to the review subfolder. */
export function NamedCopiesBar({ runId }: { runId: string }) {
  useLocale();
  const out = useLoad("output-folder", api.outputFolder);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const folder = out.data?.path ?? null;

  async function write() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.writeNamedCopies(runId);
      setMsg({ error: false, text: t("Kiírva: {{path}} — {{ready}} kész, {{review}} ellenőrzendő, {{skipped}} kimaradt.",
        { path: r.path, ready: r.ready, review: r.review, skipped: r.skipped }) });
    } catch (e) {
      const err = e as ApiError;
      setMsg({ error: true, text: err.code === "no_output_folder" ? t("Nincs kimeneti mappa; add meg a Beállítások › Munkamappák oldalon.")
        : err.status === 422 && !getActor() ? t("A kiíráshoz válaszd ki a neved a fejlécben.") : err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="notice named-copies">
      <span>{t("Az iratok másolatai egységes, tartalom szerinti névvel; az eredeti fájlok nem változnak. A bizonytalan nevűek az „ellenorzendo” almappába kerülnek, a jegyzék (jegyzek.csv) mutatja, melyik eredetiből melyik név lett.")}</span>
      <span className="button-row">
        <a className="secondary dl-btn small-btn" href={api.namedCopiesZipUrl(runId)} download><Icon name="download" />{t("Letöltés ZIP-ben")}</a>
        <button type="button" className="secondary small-btn" disabled={busy || !folder} onClick={() => void write()}
          title={folder ?? t("Előbb adj meg kimeneti mappát a Beállítások › Munkamappák oldalon.")}>{busy ? t("Kiírás…") : t("Kiírás a kimeneti mappába")}</button>
        {out.data && !folder ? <span className="muted small">{t("Nincs kimeneti mappa:")} <a href="#/settings/folders">{t("Beállítások › Munkamappák")}</a></span> : null}
      </span>
      {msg ? <span role="status" className={msg.error ? "error-text" : ""}>{msg.text}</span> : null}
    </div>
  );
}

/** Releasing the run: a person approves the live run, once it has finished, with no open to-dos. */
function Approval({ runId, onChanged }: { runId: string; onChanged: () => void }) {
  useLocale();
  const run = useRunView(runId);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (!run.data) return null;
  const r = run.data.run;
  const open = Object.values(run.data.open_reasons).reduce((n, x) => n + x.length, 0);

  async function approve() {
    setBusy(true);
    setMsg(null);
    try {
      await api.approve(runId, run.data?.review_version);
      setMsg({ error: false, text: t("Jóváhagyva: az eredmény kiadható.") });
      run.reload();
      onChanged();
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409) {
        // 085: a correction was saved since this page loaded (e.g. in another tab): the new state has to be seen first
        setMsg({ error: true, text: t("Az eredmény a megtekintés óta változott (valaki javított rajta). Nézd át újra, majd hagyd jóvá.") });
        run.reload();
        return;
      }
      setMsg({ error: true, text: err.status === 422 && !getActor() ? t("A jóváhagyáshoz válaszd ki a neved a fejlécben.") : err.message });
    } finally {
      setBusy(false);
    }
  }

  if (r.mode === "shadow") {
    return <p className="notice">{t("Próbafutás eredménye ({{when}}): megtekinthető és letölthető, de nem adható ki. Kiadáshoz éles futás kell a Feldolgozás szakaszban.", { when: when(r.created_at) })}</p>;
  }
  if (r.approval) return <p className="notice ok-box">{t("Kiadva: jóváhagyta {{who}}, {{when}}.", { who: r.approved_by, when: when(r.approved_at) })}</p>;
  return (
    <div className="notice approval-box">
      <span>
        {r.status === "done" ? t("Az éles futás lezárult, nyitott teendő nélkül: jóváhagyható.")
          : open ? t("Még {{n}} nyitott teendő van; jóváhagyás előtt rendezd őket az Ellenőrzés szakaszban.", { n: open })
            : t("Az éles futás még nem zárult le.")}
      </span>
      <ConfirmButton className="primary" disabled={busy || r.status !== "done"} onConfirm={() => void approve()}>{t("Jóváhagyás és kiadás")}</ConfirmButton>
      {msg ? <span role="status" className={msg.error ? "error-text" : ""}>{msg.text}</span> : null}
    </div>
  );
}
