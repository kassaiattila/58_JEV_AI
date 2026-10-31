// 231 (plan stage A, A7e; DECISIONS 231): the cases of the process packs. Every open case with the step it is at and
// what that step waits for (a person's start or decision, the other side's reply, the machine's work); the closed ones
// on request. Above them, only while there are some, the handovers to check: the cases whose last attempt to send
// something failed or has an unknown outcome. The rows come from the `cases` and `handovers` datasets
// (jav/app/case_lists.py); a case's name opens its page. 231 (U0): "New case" starts a case of any process.
// 263 (plan E, F3; the owner's decisions of 2026-10-30: views, groups and a period grid): only the main cases have a
// row, with their party, period and their steps' states; the views - the cases waiting for the person, their own, every
// open one, the closed ones, and each process's - stand in the left panel with their counts; the list is grouped by
// process at first and keeps its state; a process repeated by period also shows its period grid (a party's row, a
// month's column, the case's state in the cell).
import { useState, type ReactNode } from "react";
import { api, type DsColumn, type DsRow, type DsScope } from "../api";
import { DataTable } from "../components/DataTable";
import { Icon } from "../components/Icon";
import { Navigator, type NavNode } from "../components/Navigator";
import { PageActions, PageActionsSlot } from "../components/PageActions";
import { PageHeader } from "../components/PageHeader";
import { SidePanel } from "../components/SidePanel";
import { useActor, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { routeHash, type CaseListView } from "../route";

/** The pack's own texts (its title, its steps' titles) and a handover's error are the interface's to translate. */
const TRANSLATED = new Set(["process", "step", "error"]);
/** What a case waits for as a state mark: a person's turn orange, the other side grey, the machine blue, a failure red;
 *  263 (F3): its sub-case, the machine's blue (the sub-case's own step is named when a person must act). */
const WAIT_MARK: Record<string, string> = {
  person_start: "s-review", person: "s-review", reply: "s-waiting", work: "s-running", failed: "s-failed", sub_case: "s-running",
};
const TRACK_MARK: Record<string, string> = { done: "s-done", running: "s-running", failed: "s-failed", waiting: "s-waiting" };
const TRACK_TEXT: Record<string, string> = { done: "done", running: "in progress", failed: "failed", waiting: "not started" };

/** 263 (F3): a case's steps as small marks, each named in its tooltip. */
function TrackMarks({ track }: { track: { title: string; state: string }[] }) {
  return (
    <span className="track-marks" aria-label={track.map((x) => `${t(x.title)}: ${t(TRACK_TEXT[x.state] ?? x.state)}`).join("; ")}>
      {track.map((x, i) => <span key={i} className={`track-mark ${TRACK_MARK[x.state] ?? "s-waiting"}`} title={`${t(x.title)}: ${t(TRACK_TEXT[x.state] ?? x.state)}`} />)}
    </span>
  );
}

const cell = (col: DsColumn, row: DsRow): ReactNode | undefined => {
  const value = row[col.key];
  if (col.key === "waits_for" && typeof value === "string" && WAIT_MARK[value]) {
    return <span className={`status ${WAIT_MARK[value]}`}>{t(col.labels?.[value] ?? value)}</span>;
  }
  if (col.key === "steps" && Array.isArray(row._track)) return <TrackMarks track={row._track as { title: string; state: string }[]} />;
  if (col.key === "step" && typeof value === "string" && value) return value.split(" › ").map((x) => t(x)).join(" › ");
  return TRANSLATED.has(col.key) && typeof value === "string" && value ? t(value) : undefined;
};

const VIEW_LABEL: Record<CaseListView, string> = {
  waiting: "Cases waiting for me", mine: "My cases", open: "Every open case", closed: "Closed cases",
};

export function CaseList({ shown, process }: { shown?: CaseListView; process?: string }) {
  useLocale();
  const actor = useActor();
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const [open, setOpen] = useState<Set<string>>(() => new Set(["by-process"]));
  const counts = useLoad(`case-views:${actor}`, () => api.caseViews(actor || undefined), 30000);
  const toCheck = useLoad("handovers:count", () => api.datasetQuery("handovers", {}, { limit: 1 }), 30000);
  const view: CaseListView = shown ?? "open";
  const proc = process ? counts.data?.processes.find((p) => p.pack === process) : undefined;
  const v = counts.data?.views;
  const nodes: NavNode[] = [
    ...(Object.keys(VIEW_LABEL) as CaseListView[]).map((k) => ({
      key: k, label: t(VIEW_LABEL[k]), href: routeHash({ view: "case-list", ...(k === "open" ? {} : { shown: k }) }), count: v ? v[k] : null,
    })),
    { key: "by-process", label: t("By process"), children: (counts.data?.processes ?? []).map((p) => ({
      key: `p:${p.pack}`, label: t(p.title), href: routeHash({ view: "case-list", process: p.pack }), count: p.open })) },
  ];
  const selected = process ? `p:${process}` : view;
  const title = process ? (proc ? t(proc.title) : process) : t(VIEW_LABEL[view]);
  const scope: DsScope = process ? { pack: process, include_closed: "1" } : { view, ...(actor ? { actor } : {}) };
  const toggle = (key: string) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  return (
    <div className="settings-layout case-list-layout">
      <SidePanel id="cases" label={t("Views")}>
        <Navigator nodes={nodes} selected={selected} open={open} onToggle={toggle} label={t("Views")} />
      </SidePanel>
      <div className="settings-page">
        <PageHeader compact crumbs={[{ label: t("Cases"), href: "#/cases" }]} title={title} actionsSlot={setSlot}
          summary={t("Every case of the processes: the step it is at and what that step waits for.")} />
        <PageActionsSlot value={slot}>
          <PageActions><a className="button primary" href="#/cases/new"><Icon name="plus" />{t("New case")}</a></PageActions>
          {toCheck.data && toCheck.data.total > 0 ? (
            <section className="case-list-check" aria-label={t("Handovers to check")}>
              <h2>{t("Handovers to check")}</h2>
              <DataTable dataset="handovers" label={t("Handovers to check")} storageId="handovers" pollMs={30000}
                emptyText={t("No handover waits for a check.")} cell={cell} />
            </section>
          ) : null}
          {proc?.repeats ? <PeriodGrid pack={proc.pack} /> : null}
          <DataTable key={selected} dataset="cases" scope={scope} label={title} storageId="cases" persist={`cases:${selected}`} pollMs={30000}
            defaultGroup={process ? undefined : "process"} cell={cell} defaultHidden={process ? ["process", "created_at"] : ["created_at"]}
            emptyText={view === "closed" ? t("No case is closed yet.") : view === "waiting" ? t("No case waits for you.") : t("No case is open.")} />
        </PageActionsSlot>
      </div>
    </div>
  );
}

/** 263 (F3): a process repeated by period - a party's row, a month's column (the months its cases cover), the case's
 *  state in the cell, linked to it. */
function PeriodGrid({ pack }: { pack: string }) {
  useLocale();
  const data = useLoad(`case-grid:${pack}`, () => api.datasetQuery("cases", { pack, include_closed: "1" }, { limit: 1000 }), 30000);
  const rows = data.data?.rows ?? [];
  const months = [...new Set(rows.map((r) => String(r.period ?? "").slice(0, 7)).filter((m) => /^\d{4}-\d{2}$/.test(m)))].sort().slice(-12);
  if (!months.length) return null;
  const parties = [...new Set(rows.map((r) => String(r.party ?? "")))].sort((a, b) => a.localeCompare(b));
  const at = (party: string, month: string) => rows.filter((r) => String(r.party ?? "") === party && String(r.period ?? "").startsWith(month));
  return (
    <section className="card wide period-grid" aria-label={t("Period grid")}>
      <div className="card-head"><h2>{t("Period grid")}</h2></div>
      <table className="table compact">
        <thead><tr><th>{t("Party")}</th>{months.map((m) => <th key={m} className="num">{m}</th>)}</tr></thead>
        <tbody>
          {parties.map((party) => (
            <tr key={party}>
              <th scope="row">{party || "–"}</th>
              {months.map((m) => {
                const cases = at(party, m);
                return (
                  <td key={m} className="num">
                    {cases.length ? cases.map((r) => {
                      const mark = r.status !== "open" ? "s-done" : WAIT_MARK[String(r.waits_for ?? "")] ?? "s-running";
                      return <a key={String(r._key)} href={`#/cases/${encodeURIComponent(String(r._key))}`} title={String(r.name)}
                        className={`status ${mark}`}>{r.status !== "open" ? t("closed") : String(r.steps ?? "")}</a>;
                    }) : <span className="muted">–</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
