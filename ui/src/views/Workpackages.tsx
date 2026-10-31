import { useState } from "react";
import { DataTable, linkOf } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { useActor } from "../hooks";
import { t, useLocale } from "../i18n";
import { RUN_STATUS, stepLabel } from "../labels";
import { type Route } from "../route";
import { WorkpackageDetail } from "./WorkpackageDetail";

export function Workpackages({ route }: { route: Extract<Route, { view: "workpackages" }> }) {
  if (route.wpId) return <WorkpackageDetail route={route} wpId={route.wpId} />;
  return <WorkpackageList />;
}

/** 231 (U2a; the owner's decision of 2026-10-28: one work list, the cases): every document batch, to find an old one
 *  (reached from Settings › System); new work starts as a case, so the list starts nothing. */
function WorkpackageList() {
  useLocale();
  const [count, setCount] = useState<number | null>(null);
  const [archived, setArchived] = useState(false); // 058: hidden work packages are only shown on request
  const [mine, setMine] = useState(false); // 061: only those whose owner is the „Ki dolgozik?” (Who is working?) person
  const actor = useActor();
  const scope = { ...(archived ? { include_archived: "1" } : {}), ...(mine && actor ? { owner: actor } : {}) };
  return (
    <>
      <PageHeader crumbs={[{ label: t("Settings"), href: "#/settings" }, { label: t("Operations"), href: "#/settings/system" }]} title={t("All document batches")}
        badge={count !== null ? <span className="count">{count}</span> : null}
        summary={t("Every document batch that is not a case step's, to find an old one; the documents of a batch run together: processing, review, result. New work starts as a case, under Cases.")}
        actions={<a className="button secondary" href="#/cases/new">{t("New case")}</a>} />
      <DataTable dataset="workpackages" label={t("All document batches")} onPage={(pg) => setCount(pg.matched)} pollMs={10000}
        scope={Object.keys(scope).length ? scope : undefined}
        toolbar={<>
          <label className="check small" title={actor ? undefined : t("First select your name above")}>
            <input type="checkbox" checked={mine && Boolean(actor)} disabled={!actor} onChange={(e) => setMine(e.target.checked)} /> {t("Only my document batches")}
          </label>
          <label className="check small"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> {t("Hidden batches too")}</label>
        </>}
        cell={(col, row) => (col.key === "next_label" ? (
          // the next step in the chosen language (from the local service's code), with a link to the stage
          <a className="next-step" href={linkOf(col, row) ?? "#/workpackages"}>
            <StageTrack stage={String(row._stage)} code={String(row.next_code)} />
            <span>{stepLabel(String(row.next_code), row._next_params as Record<string, unknown>, String(row.next_label))}</span>
          </a>
        ) : undefined)}
        emptyText={t("No document batch outside the cases.")} />
    </>
  );
}

const STAGE_ORDER = ["process", "review", "result"];
const TRACK_TONE: Record<string, string> = {
  running: "t-running", review: "t-todo", pending: "t-todo", reconcile_pair: "t-todo", rerun: "t-failed", blocked: "t-failed",
  done: "t-done", reconcile_approved: "t-done", quote_approved: "t-done",
};

/** 155: where the package stands on its way — Processing · Review · Result — as three short segments before the next
 *  step; the current one takes the state's colour. Purely visual: the step's text says the same in words. */
function StageTrack({ stage, code }: { stage: string; code: string }) {
  const at = Math.max(0, STAGE_ORDER.indexOf(stage));
  return (
    <span className={`track ${TRACK_TONE[code] ?? ""}`} aria-hidden="true">
      {STAGE_ORDER.map((s, i) => <i key={s} className={i < at ? "passed" : i === at ? "current" : undefined} />)}
    </span>
  );
}

export function RunStatus({ status }: { status: string }) {
  useLocale();
  return <span className={`status s-${status}`}>{RUN_STATUS[status] ?? status}</span>;
}
