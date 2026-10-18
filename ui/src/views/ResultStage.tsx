// Result section (057, replacing Riportok (Reports) and Adatok (Data)). 172 (plan 170 L1, DECISIONS 167, 172): by
// default the package's current result — each item from the run whose result counts now — with the package's one
// Approve and release and its released versions; the picker also offers each run's own result, which shows the run's
// state but is not approved on its own. View switcher: Iratok · Adatpontok · Tételsorok · Közmű-költség · Fájlnevek
// (Documents · Data points · Line items · Utility cost · File names, 078), with the shared table and download panel.
import { useEffect, useRef, useState } from "react";
import { api, ApiError, getActor, type PackageResult, type PackageVersion, type WorkpackageView } from "../api";
import { DataTable } from "../components/DataTable";
import { DatasetPicker, runOption } from "../components/DatasetPicker";
import { ACTIVE_RUN, useLoad, useRunView } from "../hooks";
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
/** 172: the picker's value for the package's current result (a run's value is its id) */
const PACKAGE = "package";

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
  if (!view.runs) {
    return <div className="empty">{t("Még nincs eredmény: előbb futtasd a csomagot a")} <a href={`#/workpackages/${wp.id}/process`}>{t("Feldolgozás")}</a> {t("szakaszban.")}</div>;
  }
  return runId ? <RunResult view={view} table={table} runId={runId} />
    : <PackageResultStage view={view} table={table} onChanged={onChanged} />;
}

/** The picker of the result shown: the package's current result first, then the package's own runs. */
function ResultPicker({ wpId, runId, table }: { wpId: string; runId?: string; table: ResultTable }) {
  return (
    <DatasetPicker dataset="runs" scope={{ workpackage_id: wpId }} label={t("Result shown")} hideLabel value={runId ?? PACKAGE}
      valueCol="run_id" toOption={runOption}
      extra={[{ value: PACKAGE, label: t("The package's current result"), detail: t("each item from the run whose result counts now") }]}
      onChange={(v) => go({ view: "workpackages", wpId, stage: "result", table, runId: v === PACKAGE ? undefined : v })} />
  );
}

function ViewTabs({ available, current, onPick }: { available: ResultTable[]; current: ResultTable; onPick: (x: ResultTable) => void }) {
  return (
    <div className="segmented-tabs" role="tablist" aria-label={t("Eredmény nézetei")}>
      {available.map((x) => (
        <button key={x} type="button" role="tab" aria-selected={x === current} className="seg" onClick={() => onPick(x)}>{TABLE_LABEL[x]}</button>
      ))}
    </div>
  );
}

const pick = (available: ResultTable[], table?: ResultTable): ResultTable =>
  table && available.includes(table) ? table : defaultResultTable(available);

// --- the package's current result ------------------------------------------------------------------------------

function PackageResultStage({ view, table, onChanged }: { view: WorkpackageView; table?: ResultTable; onChanged: () => void }) {
  useLocale();
  const wp = view.workpackage;
  const result = useLoad(`package-result:${wp.id}`, () => api.packageResult(wp.id));
  // loaded again when the package or its runs change (an item added or removed, a run finished or approved)
  const cur = view.current_run;
  const signature = [wp.revision, cur?.run_id, cur?.status, cur?.approval, cur?.open_reasons, view.open_runs?.length].join("|");
  const seen = useRef(signature);
  const { reload } = result;
  useEffect(() => {
    if (seen.current === signature) return;
    seen.current = signature;
    reload();
  }, [signature, reload]);
  // the release names the mark of the result the table on screen shows (as a run's approval did, 086); after a
  // conflict the table is loaded again, and until it has arrived there is nothing to release
  const [reloads, setReloads] = useState(0);
  const [shown, setShown] = useState<{ table: string; mark?: string } | null>(null);
  const data = result.data;
  const available = data ? TABLES.map((x) => x.key).filter((k) => data.tables.includes(k)) : [];
  const current = pick(available, table);
  const spec = TABLES.find((x) => x.key === current) ?? TABLES[3];
  // the named copies are made per run: the File names view is there only when one run gives every item's result
  const runs = data ? [...new Set(data.items.map((i) => i.run_id).filter((r): r is string => !!r))] : [];
  const single = runs.length === 1 ? runs[0] : null;
  const ofPackage = current !== "file_names";
  const tableId = `${spec.dataset}:${wp.id}:${reloads}`;
  const mark = !available.length || !ofPackage ? null : shown?.table === tableId ? shown.mark ?? null : undefined;
  const nav = (next: ResultTable) => go({ view: "workpackages", wpId: wp.id, stage: "result", table: next });
  const again = () => { reload(); setReloads((n) => n + 1); };
  const xlsx = api.packageResultXlsxUrl(wp.id);

  return (
    <div className="stage-stack result-stage">
      <div className="result-bar">
        <ResultPicker wpId={wp.id} table={current} />
        {available.length ? <ViewTabs available={available} current={current} onPick={nav} /> : null}
        <span className="dt-spacer" />
        {data && available.length ? (
          <a className="secondary dl-btn small-btn" href={xlsx} download><Icon name="download" />{t("Teljes Excel-csomag")}</a>
        ) : null}
      </div>
      {result.error ? <p className="notice error" role="alert">{result.error.message}</p> : null}
      {!data && !result.error ? <p className="muted">{t("Betöltés…")}</p> : null}
      {data ? (
        <PackageRelease wpId={wp.id} data={data} running={!!cur && ACTIVE_RUN.has(cur.status)} mark={mark}
          onReleased={() => { again(); onChanged(); }} onConflict={again} />
      ) : null}
      {data && data.versions.length ? <ReleasedVersions wpId={wp.id} versions={data.versions} /> : null}
      {data && !available.length ? <p className="notice">{t("No item of the package has a finished document result yet.")}</p> : null}
      {current === "utility" ? <UtilityPanel wpId={wp.id} /> : null}
      {current === "file_names" && single ? <NamedCopiesBar runId={single} /> : null}
      {available.length && (ofPackage || single) ? (
        <DataTable key={tableId} dataset={spec.dataset} scope={ofPackage ? { workpackage_id: wp.id } : { run_id: single! }}
          label={TABLE_LABEL[spec.key]} selectable onPage={(page) => setShown({ table: tableId, mark: page.result_mark })}
          storageId={`result-${spec.dataset}`} defaultHidden={DEFAULT_HIDDEN[spec.dataset]}
          // proposed next step in the chosen language (the local service gives the code; search uses the Hungarian label)
          cell={spec.key === "emails" ? (col, row) => (col.key === "next_flow" ? nextFlowText(row.next_flow as string | null) : undefined) : undefined}
          downloadExtras={<a className="small" href={xlsx} download>{t("The package's current result in one workbook (every table)")}</a>} />
      ) : null}
    </div>
  );
}

type PackageLine = "ready" | "released" | "todo" | "running" | "failed" | "trial" | "empty" | "off";
const PACKAGE_MARK: Record<PackageLine, string> = { ready: "s-review", released: "s-done", todo: "s-needs_review", running: "s-running",
  failed: "s-failed", trial: "", empty: "", off: "s-warn" };

/** 172: what the package's release line says (the mark of DESIGN.md §4): a release can be given (orange: a person's
 *  turn), released (green), open to-dos (orange), a live run not finished (blue) or failed (red), only a trial's result
 *  or none (neutral), or partly released / changed since the release with nothing to release now (amber). */
export function packageLine(data: PackageResult, running: boolean): PackageLine {
  const waiting = data.blockers.filter((b) => b.code === "run_not_ready");
  const nothing = data.blockers.some((b) => b.code === "nothing_to_release" || b.code === "own_approval");
  if (waiting.some((b) => b.status === "failed")) return "failed";
  if (waiting.some((b) => (b.open_reasons ?? 0) > 0)) return "todo";
  if (waiting.length || (running && nothing)) return "running";
  if (!nothing) return "ready";
  if (data.state === "released") return "released";
  if (data.state === "not_released") return data.items.some((i) => i.tier) ? "trial" : "empty";
  return "off";
}

/** 172 (DECISIONS 167, 172): the package's one Approve and release. It approves every open live run together and
 *  records the next released version, whose downloads never change; it names the result on screen (`mark`; undefined
 *  while the table loads) and the count of removed items it leaves out. */
function PackageRelease({ wpId, data, running, mark, onReleased, onConflict }: {
  wpId: string; data: PackageResult; running: boolean; mark: string | null | undefined; onReleased: () => void; onConflict: () => void;
}) {
  useLocale();
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const line = packageLine(data, running);
  const latest = data.versions[0];
  const todos = data.blockers.reduce((n, b) => n + (b.code === "run_not_ready" ? b.open_reasons ?? 0 : 0), 0);
  const trial = data.items.filter((i) => i.tier === "trial").length;
  const unreleased = data.items.filter((i) => !i.released).length;

  async function release() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.releasePackage(wpId, mark ?? data.mark, data.removed_items || undefined);
      setMsg({ error: false, text: t("Released: version {{n}}. Its downloads are stored and do not change.", { n: r.version.version }) });
      onReleased();
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409 && err.blockers.some((b) => b.code === "removed_items")) {
        setMsg({ error: true, text: t("Another item was removed from the package meanwhile. Check the count, then approve again.") });
      } else if (err.status === 409 && err.code === "not_ready") {
        setMsg({ error: true, text: t("The package cannot be released: {{reason}}", { reason: err.message }) });
      } else if (err.status === 409) {
        setMsg({ error: true, text: t("The package's result changed since it was shown. Check it again, then release it.") });
      } else {
        setMsg({ error: true, text: err.status === 422 && !getActor() ? t("A jóváhagyáshoz válaszd ki a neved a fejlécben.") : err.message });
        return;
      }
      onConflict();
    } finally {
      setBusy(false);
    }
  }

  const readyLabel = { not_released: t("Awaiting release"), partly_released: t("Partly released"),
    changed_since_release: t("Changed since the release"), released: t("Awaiting release") }[data.state];
  const readyDetail = data.open_live_runs.length
    ? t("the live results have finished with no open to-dos; the release approves them and records version {{n}}", { n: (latest?.version ?? 0) + 1 })
    : t("an approved result is not in a released version yet; the release records version {{n}}", { n: (latest?.version ?? 0) + 1 });
  const [label, detail] = {
    ready: [readyLabel, readyDetail],
    released: [t("Released"), latest ? t("version {{n}} · released by {{who}}, {{when}}", { n: latest.version, who: latest.released_by, when: when(latest.released_at) }) : ""],
    todo: [t("{{n}} open to-dos", { n: todos }), t("settle them in the Review section before the release")],
    running: [t("Not finished"), t("a live run of the package has not finished yet")],
    failed: [t("Failed"), t("a live run ended with an error; it cannot be released — rerun it in Processing")],
    trial: [t("Trial result"), t("it can be viewed and downloaded but not released; a release needs a live run")],
    empty: [t("No result yet"), t("no item of the package has a finished result")],
    off: data.state === "partly_released"
      ? [t("Partly released"), t("{{n}} item(s) have no released result; a live run over them can be released", { n: unreleased })]
      : [t("Changed since the release"), t("a released item was removed or another result replaced it")],
  }[line];
  return (
    <div className="release-line" data-state={line}>
      <span className={`status ${PACKAGE_MARK[line]}`}>{label}</span>
      <span className="release-detail">
        {detail}
        {line === "released" && latest?.backfilled_at ? <> · {t("recorded afterwards")}</> : null}
      </span>
      {line === "released" && latest ? (
        <a className="small" href={api.packageVersionFileUrl(wpId, latest.version, "result.xlsx")} download>{t("Download version {{n}} (Excel)", { n: latest.version })}</a>
      ) : null}
      {data.open_live_runs.map((r) => <RunEngine key={r} runId={r} />)}
      {trial && line !== "trial" ? (
        <span className="release-removed">
          <span className="status s-trial">{t("{{n}} from a trial", { n: trial })}</span>
          <span className="release-detail">{t("shown here, not released")}</span>
        </span>
      ) : null}
      {data.removed_items && line !== "trial" ? (
        <span className="release-removed">
          <span className="status s-warn">{t("{{n}} removed", { n: data.removed_items })}</span>
          <span className="release-detail">{t("removed from the package; left out of the released result")}</span>
        </span>
      ) : null}
      {line === "ready" || line === "todo" || line === "running" ? (
        <ConfirmButton className={line === "ready" ? "primary" : "secondary"} disabled={busy || line !== "ready" || mark === undefined}
          onConfirm={() => void release()}>{t("Jóváhagyás és kiadás")}</ConfirmButton>
      ) : null}
      {msg ? <span role="status" className={msg.error ? "error-text" : ""}>{msg.text}</span> : null}
    </div>
  );
}

/** 160-D: the AI engine of an open live run, shown at its approval. */
function RunEngine({ runId }: { runId: string }) {
  const run = useRunView(runId);
  return run.data ? <EngineMark engine={run.data.engine} /> : null;
}

// the stored downloads of a version, by their file names, the workbook first (a CSV table only when it has rows)
const FILE_LABEL: Record<string, string> = tmap({ "result.xlsx": "Excel", "documents.csv": "Documents (CSV)", "datapoints.csv": "Data points (CSV)",
  "line_items.csv": "Line items (CSV)", "native_facts.csv": "Native facts (CSV)", "result.json": "JSON" });
const FILE_ORDER = Object.keys(FILE_LABEL);
const fileRank = (name: string) => (FILE_ORDER.includes(name) ? FILE_ORDER.indexOf(name) : FILE_ORDER.length);

/** 172: the package's released versions, newest first, each with its stored downloads (they never change). */
function ReleasedVersions({ wpId, versions }: { wpId: string; versions: PackageVersion[] }) {
  useLocale();
  return (
    <details className="release-versions">
      <summary>{t("Released versions ({{n}})", { n: versions.length })}</summary>
      <table className="table compact">
        <thead>
          <tr><th>{t("Version")}</th><th>{t("Released by")}</th><th>{t("Released at")}</th><th className="num">{t("Items")}</th><th>{t("Downloads")}</th></tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.version}>
              <td className="tnum">{t("version {{n}}", { n: v.version })}</td>
              <td>{v.released_by}</td>
              <td className="tnum">
                {when(v.released_at)}
                {v.backfilled_at ? <span className="muted"> · {t("recorded afterwards, {{when}}", { when: when(v.backfilled_at) })}</span> : null}
              </td>
              <td className="num">{v.items.length}</td>
              <td>
                <span className="release-files">
                  {v.files.filter((f) => f.rows || !f.name.endsWith(".csv")).sort((a, b) => fileRank(a.name) - fileRank(b.name)).map((f) => (
                    <a key={f.name} href={api.packageVersionFileUrl(wpId, v.version, f.name)} download>{FILE_LABEL[f.name] ?? f.name}</a>
                  ))}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

// --- a run's own result ----------------------------------------------------------------------------------------

function RunResult({ view, table, runId }: { view: WorkpackageView; table?: ResultTable; runId: string }) {
  useLocale();
  const wp = view.workpackage;
  const run = useRunView(runId);
  // 058: only the views that contain data (e.g. utility cost only for utility invoices); the local service says which
  const available = (run.data?.tables ? TABLES.filter((x) => run.data!.tables!.includes(x.key)) : TABLES).map((x) => x.key);
  const current = pick(available, table);
  const spec = TABLES.find((x) => x.key === current) ?? TABLES[3];
  const nav = (next: ResultTable) => go({ view: "workpackages", wpId: wp.id, stage: "result", table: next, runId });
  return (
    <div className="stage-stack result-stage">
      <div className="result-bar">
        <ResultPicker wpId={wp.id} runId={runId} table={current} />
        <ViewTabs available={available} current={current} onPick={nav} />
        <span className="dt-spacer" />
        <a className="secondary dl-btn small-btn" href={api.exportUrl(runId, "xlsx")} download><Icon name="download" />{t("Teljes Excel-csomag")}</a>
      </div>
      <RunState runId={runId} wpId={wp.id} />
      {run.data && !available.length ? <p className="notice">{t("Ennek a futásnak nincs irat-eredménye (például csak leveleket dolgozott fel).")}</p> : null}
      {current === "utility" ? <UtilityPanel runId={runId} wpId={wp.id} /> : null}
      {current === "file_names" ? <NamedCopiesBar runId={runId} /> : null}
      {available.length ? <DataTable key={`${spec.dataset}:${runId}`} dataset={spec.dataset} scope={{ run_id: runId }} label={TABLE_LABEL[spec.key]} selectable
        storageId={`result-${spec.dataset}`} defaultHidden={DEFAULT_HIDDEN[spec.dataset]}
        cell={spec.key === "emails" ? (col, row) => (col.key === "next_flow" ? nextFlowText(row.next_flow as string | null) : undefined) : undefined}
        downloadExtras={<a className="small" href={api.exportUrl(runId, "xlsx")} download>{t("A futás teljes Excel-csomagja (minden tábla és a közmű-költség)")}</a>} /> : null}
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

/** A run's own state (DECISIONS 172): the run is viewed here, and its approval is the package's Approve and release.
 *  The state's own mark (156): released, awaiting the release, open to-dos, not finished, stopped, failed, superseded,
 *  a trial's result. */
function RunState({ runId, wpId }: { runId: string; wpId: string }) {
  useLocale();
  const run = useRunView(runId);
  if (!run.data) return null;
  const r = run.data.run;
  // 160-C (decision 163 D7): items removed from the package are left out of the release; their to-dos do not count
  const removed = run.data.removed_items ?? [];
  const open = Object.entries(run.data.open_reasons).reduce((n, [item, x]) => n + (removed.includes(item) ? 0 : x.length), 0);
  // 167 (review 160 U-5): a stopped, failed or superseded live run is not "not finished": it cannot be approved at all
  const state: RunLine = r.mode === "shadow" ? "trial" : r.approval ? "released" : r.status === "failed" ? "failed"
    : r.status === "cancelled" ? (run.data.superseded ? "superseded" : "stopped")
    : r.status === "done" ? "ready" : open ? "todo" : "running";
  const [label, detail] = {
    trial: [t("Trial result"), t("{{when}} · it can be viewed and downloaded but not released; a release needs a live run", { when: when(r.created_at) })],
    released: [t("Approved"), t("approved by {{who}}, {{when}}", { who: r.approved_by, when: when(r.approved_at) })],
    ready: [t("Awaiting release"), t("the live run has finished with no open to-dos; it is approved with the package's result")],
    todo: [t("{{n}} open to-dos", { n: open }), t("settle them in the Review section before the release")],
    running: [t("Not finished"), t("the live run has not finished yet")],
    stopped: [t("Stopped"), t("a person stopped the run; it cannot be approved — rerun it in Processing")],
    failed: [t("Failed"), t("the run ended with an error; it cannot be approved — rerun it in Processing")],
    superseded: [t("Superseded"), t("a later live run repeated it; it cannot be approved")],
  }[state];
  return (
    <div className="release-line" data-state={state}>
      <span className={`status ${RUN_MARK[state]}`}>{label}</span>
      <span className="release-detail">{detail}</span>
      <EngineMark engine={run.data.engine} />
      {removed.length && state !== "trial" ? (
        <span className="release-removed">
          <span className="status s-warn">{t("{{n}} removed", { n: removed.length })}</span>
          <span className="release-detail">{state === "released" ? t("removed from the package before the approval; not in the released result")
            : t("removed from the package; left out of the released result")}</span>
        </span>
      ) : null}
      {state === "ready" ? (
        <a className="secondary small-btn" href={`#/workpackages/${encodeURIComponent(wpId)}/result`}>{t("To the package's result")}</a>
      ) : null}
    </div>
  );
}

type RunLine = "trial" | "released" | "ready" | "todo" | "running" | "stopped" | "failed" | "superseded";
// the state marks of DESIGN.md §4: a person has to act (orange), done (green), running (blue), an error (red); a trial
// and a superseded run are neutral
const RUN_MARK: Record<RunLine, string> = { trial: "", released: "s-done", ready: "s-review", todo: "s-needs_review",
  running: "s-running", stopped: "s-cancelled", failed: "s-failed", superseded: "" };
