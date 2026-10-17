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
import { EngineMark } from "../components/EngineMark";
import { ConfirmButton } from "../components/ConfirmButton";

const TABLES: { key: ResultTable; dataset: string }[] = [
  { key: "emails", dataset: "emails" },
  { key: "tasks", dataset: "email_tasks" },
  { key: "documents", dataset: "documents" },
  { key: "datapoints", dataset: "datapoints" },
  { key: "native_facts", dataset: "native_facts" },
  { key: "line_items", dataset: "line_items" },
  { key: "utility", dataset: "utility_cost" },
  { key: "file_names", dataset: "file_names" },
];
// 156: columns a person seldom reads, hidden by default so that a view fits a laptop screen without sideways
// scrolling; the column menu shows them again, and the full Excel package always has them
const DEFAULT_HIDDEN: Record<string, string[]> = {
  emails: ["corrected", "attachments", "body_status"],
  native_facts: ["unit", "role", "related_entity", "reading_status", "interpretation_status"], // the last two: per document
};
// the views' labels are translated when read (tmap)
const TABLE_LABEL = tmap({ emails: "Levelek", tasks: "Feladatok", documents: "Iratok", datapoints: "Adatpontok", line_items: "Tételsorok",
  utility: "Közmű-költség", file_names: "Fájlnevek", native_facts: "Native facts" }) as Record<ResultTable, string>;

/** The default tab (062): Levelek (Emails) for an email work package, otherwise Adatpontok (Data points), failing
 *  that the first available view. */
export function defaultResultTable(available: ResultTable[]): ResultTable {
  if (available.includes("emails")) return "emails";
  if (available.includes("datapoints")) return "datapoints";
  if (available.includes("native_facts")) return "native_facts";
  return available[0] ?? "datapoints";
}

export function ResultStage({ view, table, runId, onChanged }: {
  view: WorkpackageView; table?: ResultTable; runId?: string; onChanged: () => void;
}) {
  useLocale();
  const wp = view.workpackage;
  const chosen = runId ?? view.current_run?.run_id ?? view.last_run?.run_id ?? null; // 153: the run the next step is about
  const run = useRunView(chosen);
  // 058: only the views that contain data (e.g. utility cost only for utility invoices); the local service says which
  const available = run.data?.tables ? TABLES.filter((x) => run.data!.tables!.includes(x.key)) : TABLES;
  const current: ResultTable = table && available.some((x) => x.key === table) ? table : defaultResultTable(available.map((x) => x.key));
  const nav = (next: { table?: ResultTable; runId?: string }) =>
    go({ view: "workpackages", wpId: wp.id, stage: "result", table: next.table ?? current, runId: next.runId ?? runId });
  // 086 (audit N01): the approval names the version of the result the table on screen shows; after a conflict the
  // table is loaded again, and until it has arrived there is nothing to approve
  const [reloads, setReloads] = useState(0);
  const [shown, setShown] = useState<{ table: string; version?: string } | null>(null);

  if (!chosen) {
    return <div className="empty">{t("Még nincs eredmény: előbb futtasd a csomagot a")} <a href={`#/workpackages/${wp.id}/process`}>{t("Feldolgozás")}</a> {t("szakaszban.")}</div>;
  }
  const spec = TABLES.find((x) => x.key === current) ?? TABLES[1];
  const tableId = `${spec.dataset}:${chosen}:${reloads}`;
  const tableVersion = shown?.table === tableId ? shown.version ?? null : undefined; // undefined: not loaded yet
  return (
    <div className="stage-stack result-stage">
      <div className="result-bar">
        {view.runs > 1 ? (
          <DatasetPicker dataset="runs" scope={{ workpackage_id: wp.id }} label={t("Futás")} hideLabel value={chosen} valueCol="run_id"
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
      <Approval runId={chosen} onChanged={onChanged} hasTable={available.length > 0} tableVersion={tableVersion}
        onConflict={() => setReloads((n) => n + 1)} />
      {run.data && !available.length ? <p className="notice">{t("Ennek a futásnak nincs irat-eredménye (például csak leveleket dolgozott fel).")}</p> : null}
      {current === "utility" ? <UtilityPanel runId={chosen} wpId={wp.id} /> : null}
      {current === "file_names" ? <NamedCopiesBar runId={chosen} /> : null}
      {available.length ? <DataTable key={tableId} dataset={spec.dataset} scope={{ run_id: chosen }} label={TABLE_LABEL[spec.key]} selectable
        onPage={(page) => setShown({ table: tableId, version: page.review_version })}
        storageId={`result-${spec.dataset}`} defaultHidden={DEFAULT_HIDDEN[spec.dataset]}
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
    <div className="named-copies">
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

/** Releasing the run: a person approves the live run, once it has finished, with no open to-dos.
 *  086 (audit N01): with a result table on screen the approval names the version of the result that table shows
 *  (`tableVersion`; undefined while it loads, so there is nothing to approve yet); a conflict loads the table again
 *  (`onConflict`). Without a table, the run's version. */
function Approval({ runId, onChanged, hasTable, tableVersion, onConflict }: {
  runId: string; onChanged: () => void; hasTable: boolean; tableVersion: string | null | undefined; onConflict: () => void;
}) {
  useLocale();
  const run = useRunView(runId);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (!run.data) return null;
  const r = run.data.run;
  // 160-C (decision 163 D7): items removed from the package are left out of the release; their to-dos do not count
  const removed = run.data.removed_items ?? [];
  const open = Object.entries(run.data.open_reasons).reduce((n, [item, x]) => n + (removed.includes(item) ? 0 : x.length), 0);
  const loading = hasTable && tableVersion === undefined;
  const version = hasTable && tableVersion ? tableVersion : run.data.review_version;

  async function approve() {
    setBusy(true);
    setMsg(null);
    try {
      await api.approve(runId, version, removed.length);
      setMsg({ error: false, text: t("Jóváhagyva: az eredmény kiadható.") });
      run.reload();
      onChanged();
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409 && err.blockers.some((b) => b.code === "removed_items")) {
        setMsg({ error: true, text: t("Another item was removed from the package meanwhile. Check the count, then approve again.") });
        run.reload();
        return;
      }
      if (err.status === 409 && err.code === "not_ready") {
        // 167 (review 160 U-4): the run is not ready (an open to-do, an unfinished item): its reason, not a correction
        setMsg({ error: true, text: t("The run cannot be approved: {{reason}}", { reason: err.message }) });
        run.reload();
        return;
      }
      if (err.status === 409) {
        // 085: a correction was saved since this page loaded (e.g. in another tab): the new state has to be seen first;
        // 086: the table is loaded again, and the approval waits for it
        setMsg({ error: true, text: t("Az eredmény a megtekintés óta változott (valaki javított rajta). Nézd át újra, majd hagyd jóvá.") });
        onConflict();
        run.reload();
        return;
      }
      setMsg({ error: true, text: err.status === 422 && !getActor() ? t("A jóváhagyáshoz válaszd ki a neved a fejlécben.") : err.message });
    } finally {
      setBusy(false);
    }
  }

  // 156: one line with the state's own mark; the approval is the solid main action only when it can be given
  // 167 (review 160 U-5): a stopped, failed or superseded live run is not "not finished": it cannot be approved at all
  const state: ReleaseState = r.mode === "shadow" ? "trial" : r.approval ? "released" : r.status === "failed" ? "failed"
    : r.status === "cancelled" ? (run.data.superseded ? "superseded" : "stopped")
    : r.status === "done" ? "ready" : open ? "todo" : "running";
  const [label, detail] = {
    trial: [t("Trial result"), t("{{when}} · it can be viewed and downloaded but not released; a release needs a live run", { when: when(r.created_at) })],
    released: [t("Released"), t("approved by {{who}}, {{when}}", { who: r.approved_by, when: when(r.approved_at) })],
    ready: [t("Awaiting approval"), t("the live run has finished with no open to-dos")],
    todo: [t("{{n}} open to-dos", { n: open }), t("settle them in the Review section before the approval")],
    running: [t("Not finished"), t("the live run has not finished yet")],
    stopped: [t("Stopped"), t("a person stopped the run; it cannot be approved — rerun it in Processing")],
    failed: [t("Failed"), t("the run ended with an error; it cannot be approved — rerun it in Processing")],
    superseded: [t("Superseded"), t("a later live run repeated it; it cannot be approved")],
  }[state];
  return (
    <div className="release-line" data-state={state}>
      <span className={`status ${RELEASE_MARK[state]}`}>{label}</span>
      <span className="release-detail">{detail}</span>
      <EngineMark engine={run.data.engine} />
      {removed.length && state !== "trial" ? (
        <span className="release-removed">
          <span className="status s-warn">{t("{{n}} removed", { n: removed.length })}</span>
          <span className="release-detail">{state === "released" ? t("removed from the package before the approval; not in the released result")
            : t("removed from the package; left out of the released result")}</span>
        </span>
      ) : null}
      {state === "trial" || state === "released" || FINAL.has(state) ? null : (
        <ConfirmButton className={state === "ready" ? "primary" : "secondary"} disabled={busy || loading || state !== "ready"}
          onConfirm={() => void approve()}>{t("Jóváhagyás és kiadás")}</ConfirmButton>
      )}
      {msg ? <span role="status" className={msg.error ? "error-text" : ""}>{msg.text}</span> : null}
    </div>
  );
}

type ReleaseState = "trial" | "released" | "ready" | "todo" | "running" | "stopped" | "failed" | "superseded";
// the state marks of DESIGN.md §4: a person has to act (orange), done (green), running (blue), an error (red); a trial
// and a superseded run are neutral
const RELEASE_MARK: Record<ReleaseState, string> = { trial: "", released: "s-done", ready: "s-review", todo: "s-needs_review",
  running: "s-running", stopped: "s-cancelled", failed: "s-failed", superseded: "" };
/** 167: the states a live run ends in without a release (it cannot be approved) */
const FINAL = new Set<ReleaseState>(["stopped", "failed", "superseded"]);
