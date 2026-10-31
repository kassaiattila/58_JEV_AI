// One work package (057): a header with the next-step button, and below it the stages of the work — Feldolgozás ·
// Ellenőrzés · Eredmény (Processing · Review · Result) —, each with its own status (modelled on the old V4 stage tabs).
// Without an address the work package opens at the next step's stage; the step is computed in one place by the local
// service (the list column shows the same). 263 (plan E, E2; the owner's decisions of 2026-10-30: one case, one track):
// a case's step's batch opens on its case's page, under the step (`CasePage` with the batch embedded); the stages are a
// shared part (`BatchStages`), and a batch of no case keeps its own page.
import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, USERS_EVENT, type WorkpackageView } from "../api";
import { lazyPage } from "../components/LazyPage";
import { PageHeader } from "../components/PageHeader";
import { Picker } from "../components/Picker";
import { useEvent, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { itemCountText, MODE, RUN_STATUS, stepLabel, tmap, when } from "../labels";
import { partOf } from "../logic/packageParts";
import { PageActions, PageActionsSlot } from "../components/PageActions";
import { batchOfCase, caseUnder, go, routeHash, wpHash, type Route, type Stage } from "../route";
import { PackageItemsPanel } from "./PackageItems";
import { ProcessStage } from "./ProcessStage";
import { scopeText } from "./PackageScope";
import { ResultStage } from "./ResultStage";
import { ReviewWorkspace } from "./ReviewWorkspace";
import { StartConfirm } from "./StartConfirm";
import { WorkpackageActions } from "./WorkpackageActions";

// 231 (C1c): the processes whose case may read this package (until then the email routing's own offer)
const PackageIntake = lazyPage(() => import("../elements/ProcessStart").then((m) => m.PackageIntake));
const CasePage = lazyPage(() => import("./CasePage").then((m) => m.CasePage));  // 231 (A6)
const STAGE_LABEL = tmap({ process: "Processing", review: "Review", result: "Result" }) as Record<Stage, string>;
// 181: a released package's release state on the stage bar, as its release line says it
const RELEASE_STATE = tmap({ released: "released", partly_released: "partly released",
  changed_since_release: "changed since the release", not_released: "awaiting release" });
const ACTIVE = new Set(["queued", "running"]);

export function stageStatus(view: WorkpackageView): Record<Stage, string> {
  const last = view.last_run;
  // 153: the to-dos and the approval are the current run's (a later run a person stopped does not hide them)
  const current = view.current_run ?? last;
  return {
    // 080: without saved settings the default processing settings apply, so readiness alone decides
    process: last ? `${MODE[last.mode]} · ${(RUN_STATUS[last.status] ?? last.status).toLowerCase()} · ${last.items_done}/${last.items}`
      : view.readiness.ready ? t("ready to start") : t("cannot start"),
    review: current ? (current.open_reasons ? t("To-dos: {{n}}", { n: current.open_reasons }) : t("no to-dos")) : itemCountText(view.workpackage.items),
    // 167: a stopped or failed live run waits for no approval (the release line says so too). 172: released only once a
    // version holds the approval (the next step says Approve and release until then)
    result: current && current.mode !== "shadow" && !current.approval && (current.status === "failed" || current.status === "cancelled")
      ? t("cannot be approved")
      // 181: a trial after a release does not hide the release (backlog J-szakaszsav-kiadott-proba)
      : !current ? t("none yet") : current.mode === "shadow" ? (view.release ? RELEASE_STATE[view.release.state] : t("trial result"))
        : current.approval && view.next?.code !== "release" ? t("released") : t("awaiting release"),
  };
}

/** The next step's label in the chosen language (the shared `stepLabel`, from the local service's code and
 *  parameters). */
export function nextStepText(view: WorkpackageView): string {
  return stepLabel(view.next.code, view.next.params, view.next.label);
}

/** 061: the work package's owner, from the list of names (the „Saját csomagjaim” (My work packages) filter uses it). */
export function OwnerPicker({ view, onChanged }: { view: WorkpackageView; onChanged: () => void }) {
  useLocale();
  const users = useLoad("users", api.users);
  useEvent(USERS_EVENT, users.reload);
  const [error, setError] = useState<string | null>(null);
  const owner = view.workpackage.owner ?? "";
  const list = users.data?.users ?? [];
  const options = [{ value: "", label: t("no owner") }, ...list.map((u) => ({ value: u, label: u }))];
  if (owner && !list.includes(owner)) options.push({ value: owner, label: owner });
  async function change(v: string) {
    setError(null);
    try {
      await api.setOwner(view.workpackage.id, v || null);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }
  return (
    <div className="owner-picker">
      <Picker label={t("Assignee")} value={owner} options={options} compact onChange={(v) => void change(v)}
        emptyText={t("No names in the list yet (Settings › Users).")} />
      {error ? <span className="small error-text" role="alert">{error}</span> : null}
    </div>
  );
}

export function WorkpackageDetail({ route, wpId }: { route: Extract<Route, { view: "workpackages" }>; wpId: string }) {
  useLocale();
  const [poll, setPoll] = useState(false);
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const wp = useLoad(`wp:${wpId}`, () => api.workpackage(wpId), poll ? 4000 : undefined);
  const lastStatus = wp.data?.last_run?.status;
  const ofCase = Boolean(wp.data?.owner_case || wp.data?.case);  // its case's page asks again itself
  useEffect(() => setPoll(!ofCase && lastStatus ? ACTIVE.has(lastStatus) : false), [lastStatus, ofCase]); // auto-refreshes only during a run

  if (wp.error?.status === 404 || wp.error?.status === 422) {
    // The work package requested in the address does not exist: we say so, and do not open another one instead.
    return (
      <PageHeader crumbs={[{ label: t("All document batches"), href: "#/workpackages" }]} title={t("Document batch not found")}
        summary={<><span className="mono">{wpId}</span>: {t("no document batch exists with this ID (or it was deleted). Choose one from the list.")}</>} />
    );
  }
  if (wp.error) return <p className="notice error" role="alert">{wp.error.message}</p>;
  if (!wp.data) return <p className="muted">{t("Loading…")}</p>;
  const view = wp.data;
  if (view.case) return <CasePage caseId={view.case.id} />;  // 231 (A6): a case's container shows its case
  // 261 (plan B, B1c; the owner's decision of 2026-10-29): a case's step's batch opens under its case's address, an
  // older address of it leads there. 263 (E2; one case, one track): a sub-case's batch under its main case, on whose
  // page its step shows it
  const owner = view.owner_case;
  const main = owner ? owner.parent?.id ?? owner.id : null;
  if (owner && main) {
    batchOfCase(wpId, owner.id);
    if (main !== owner.id) caseUnder(owner.id, main);
    if (route.inCase !== main) {
      window.location.replace(routeHash({ ...route, inCase: main }));
      return <p className="muted">{t("Loading…")}</p>;
    }
    return <CasePage caseId={main} batch={{ wpId, route }} />;
  }
  const { workpackage, last_run: last } = view;
  // 176: what the package's rule shows (231 C3b5a: by its page part; none for a package of no rule)
  const part = partOf(view);

  const summary: ReactNode = (
    <>
      {part?.summary?.(view) ?? null}
      {itemCountText(workpackage.items)}
      {last ? ` · ${t("last run: {{mode}}, {{when}}", { mode: MODE[last.mode].toLowerCase(), when: when(last.created_at) })}` : ` · ${t("not run yet")}`}
    </>
  );
  // 146: the workflow the package is a step of, with a link to its control view (155: on the summary line)
  const workflowOf: ReactNode = view.workflow ? (
    <>{" · "}{t("Step {{step}} of the workflow", { step: t(view.workflow.step_title) })}{" "}
      <a href={`#/workflows/${encodeURIComponent(view.workflow.id)}`}>{view.workflow.name}</a></>
  ) : null;
  // 181: the party, period and role a person gave the package (a statement package's own is on its summary already, a
  // workflow step's is the workflow's, linked on the same line)
  const scopeOf: ReactNode = view.scope && view.scope.from === "own" ? <>{" · "}{scopeText(view.scope)}</> : null;
  const crumbs = [{ label: t("All document batches"), href: "#/workpackages" }];
  return (
    <>
      <PageHeader compact crumbs={crumbs} title={workpackage.name}
        summary={<>{summary}{scopeOf}{workflowOf}</>} actionsSlot={setSlot}
        actions={<><OwnerPicker view={view} onChanged={wp.reload} /><WorkpackageActions view={view} onChanged={wp.reload} /></>} />
      <PageActionsSlot value={slot}><BatchStages view={view} route={route} onChanged={wp.reload} /></PageActionsSlot>
    </>
  );
}

/** 263 (E2): a batch's three stages - the bar with each stage's state, and the chosen stage's work - the same on a
 *  batch's own page and under its case's step. Its next step is the page's main action (`PageActions`), at the right
 *  end of the title row, when it is done on another stage; on its own stage the stage's own solid button is the action,
 *  and only when the batch has nothing for a person to do (it runs, or it is released) is `otherwise` (the case's next
 *  step, done elsewhere) the page's. `extra` stands at the bar's right end (the
 *  batch's management and the step's log, under a case); `note` above the Processing stage's work (what the case's step
 *  says of the batch's run: the cost cap a person approved); `body` in place of a stage's work, with no stage chosen
 *  (the step's log). `level`: "sub" under a case's track, quieter; "main" when the stages are the page's track. */
export function BatchStages({ view, route, onChanged, extra, otherwise, note, body, level = "main" }: {
  view: WorkpackageView; route: Extract<Route, { view: "workpackages" }>; onChanged: () => void; extra?: ReactNode;
  otherwise?: ReactNode; note?: ReactNode; body?: ReactNode; level?: "main" | "sub";
}) {
  useLocale();
  const { workpackage, next } = view;
  const wpId = workpackage.id;
  const stage: Stage | null = body !== undefined ? null : route.stage ?? next.stage;
  const status = stageStatus(view);
  const part = partOf(view);
  const labels = STAGE_LABEL;
  return (
    <>
      {next.stage !== stage ? (
        <PageActions>
          <button type="button" className="primary" onClick={() => go({ view: "workpackages", wpId, stage: next.stage })}>{nextStepText(view)} →</button>
        </PageActions>
      ) : otherwise && (next.code === "running" || next.code === "done") ? <PageActions>{otherwise}</PageActions> : null}
      {workpackage.status === "archived" ? (
        <p className="notice">{t("This batch is hidden from the list; its runs and results are kept. Use “Manage batch” to bring it back.")}</p>
      ) : null}
      <div className="track-row">
        <div className={`stage-tabs ${level === "sub" ? "sub-track" : "case-track"}`} role="tablist" aria-label={t("Document batch stages")}>
          {(Object.keys(labels) as Stage[]).map((s, i) => (
            <a key={s} role="tab" aria-selected={stage === s} className={`stage-tab ${next.stage === s ? "is-next" : ""}`} href={wpHash(wpId, s)}>
              <span className="stage-no" aria-hidden="true">{i + 1}</span>
              <span className="stage-text"><strong>{labels[s]}</strong><span className="small">{status[s]}</span></span>
            </a>
          ))}
        </div>
        {extra}
      </div>
      {stage === null ? body : (
      <div role="tabpanel" aria-label={labels[stage]}>
        {stage === "process" && !route.start ? note ?? null : null}
        {stage === "process" && route.start ? <StartConfirm view={view} mode={route.start.mode} rerun={route.start.rerun} pending={route.start.pending} onChanged={onChanged} /> : null}
        {stage === "process" && !route.start ? <ProcessStage view={view} adding={!!route.add} onChanged={onChanged} /> : null}
        {stage === "review" ? (
          view.runs ? (
            <>
              <ReviewWorkspace wp={workpackage} itemId={route.itemId} onChanged={onChanged} currentRunId={view.current_run?.run_id}
                openRuns={view.open_runs} />
              <details className="details mt">
                {/* 167: the title names adding too (the owner did not find it behind "Manage documents"); 168: the same
                    item list as in Processing (DECISIONS 168) */}
                <summary>{t("The package's items: add, open, download, remove")}</summary>
                <PackageItemsPanel view={view} onChanged={onChanged} />
              </details>
            </>
          ) : (
            <>
              <p className="notice">{t("No processing has run on this batch yet, so there is nothing to review. The documents can be opened and downloaded here; start the processing in the")}{" "}
                <a href={wpHash(wpId, "process")}>{STAGE_LABEL.process}</a> {t("section.")}</p>
              <PackageItemsPanel view={view} onChanged={onChanged} />
            </>
          )
        ) : null}
        {/* 140: what a logic pack shows above the result (a statement package: its statements and its party's months) */}
        {stage === "result" ? part?.resultPanel?.(view) ?? null : null}
        {/* 231 (C1c): a package offers the cases of the processes that read it (an email package: the email routing) */}
        {stage === "result" && view.intake?.length ? <PackageIntake offers={view.intake} /> : null}
        {stage === "result" ? <ResultStage view={view} table={route.table} runId={route.runId} onChanged={onChanged} /> : null}
      </div>
      )}
    </>
  );
}

/** 263 (E2): a case's step's batch on its case's page: its stages (`BatchStages`), its management at the bar's right
 *  end, asking again while it runs; a person's action on it tells the case's page too. */
export function EmbeddedBatch({ wpId, route, onChanged, side, otherwise, note, body, level }: {
  wpId: string; route: Extract<Route, { view: "workpackages" }>; onChanged: () => void; side?: ReactNode;
  otherwise?: ReactNode; note?: ReactNode; body?: ReactNode; level: "main" | "sub";
}) {
  useLocale();
  const [poll, setPoll] = useState(false);
  const wp = useLoad(`wp:${wpId}`, () => api.workpackage(wpId), poll ? 4000 : undefined);
  const lastStatus = wp.data?.last_run?.status;
  useEffect(() => setPoll(lastStatus ? ACTIVE.has(lastStatus) : false), [lastStatus]);
  if (wp.error) return <p className="notice error" role="alert">{wp.error.message}</p>;
  if (!wp.data) return <p className="muted">{t("Loading…")}</p>;
  const changed = () => { wp.reload(); onChanged(); };
  return (
    <BatchStages view={wp.data} route={route} onChanged={changed} otherwise={otherwise} note={note} body={body} level={level}
      extra={<div className="track-side">{side}<WorkpackageActions view={wp.data} onChanged={changed} /></div>} />
  );
}
