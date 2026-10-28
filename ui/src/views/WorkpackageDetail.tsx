// One work package (057): a header with the next-step button, and below it the stages of the work — Feldolgozás ·
// Ellenőrzés · Eredmény (Processing · Review · Result) —, each with its own status (modelled on the old V4 stage tabs).
// Without an address the work package opens at the next step's stage; the step is computed in one place by the local
// service (the list column shows the same).
import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, USERS_EVENT, type WorkpackageView } from "../api";
import { lazyPage } from "../components/LazyPage";
import { PageHeader } from "../components/PageHeader";
import { Picker } from "../components/Picker";
import { useEvent, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { itemCountText, MODE, RUN_STATUS, stepLabel, tmap, when } from "../labels";
import { partOf } from "../logic/packageParts";
import { go, routeHash, type Route, type Stage } from "../route";
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
const STAGE_LABEL = tmap({ process: "Feldolgozás", review: "Ellenőrzés", result: "Eredmény" }) as Record<Stage, string>;
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
      : view.readiness.ready ? t("indítható") : t("nem indítható"),
    review: current ? (current.open_reasons ? t("{{n}} teendő", { n: current.open_reasons }) : t("nincs teendő")) : itemCountText(view.workpackage.items),
    // 167: a stopped or failed live run waits for no approval (the release line says so too). 172: released only once a
    // version holds the approval (the next step says Approve and release until then)
    result: current && current.mode !== "shadow" && !current.approval && (current.status === "failed" || current.status === "cancelled")
      ? t("cannot be approved")
      // 181: a trial after a release does not hide the release (backlog J-szakaszsav-kiadott-proba)
      : !current ? t("még nincs") : current.mode === "shadow" ? (view.release ? RELEASE_STATE[view.release.state] : t("próba-eredmény"))
        : current.approval && view.next?.code !== "release" ? t("kiadva") : t("awaiting release"),
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
  const options = [{ value: "", label: t("nincs felelős") }, ...list.map((u) => ({ value: u, label: u }))];
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
      <Picker label={t("Felelős")} value={owner} options={options} compact onChange={(v) => void change(v)}
        emptyText={t("Még nincs név a listában (Beállítások › Felhasználók).")} />
      {error ? <span className="small error-text" role="alert">{error}</span> : null}
    </div>
  );
}

export function WorkpackageDetail({ route, wpId }: { route: Extract<Route, { view: "workpackages" }>; wpId: string }) {
  useLocale();
  const [poll, setPoll] = useState(false);
  const wp = useLoad(`wp:${wpId}`, () => api.workpackage(wpId), poll ? 4000 : undefined);
  const lastStatus = wp.data?.last_run?.status;
  useEffect(() => setPoll(lastStatus ? ACTIVE.has(lastStatus) : false), [lastStatus]); // auto-refreshes only during a run

  if (wp.error?.status === 404 || wp.error?.status === 422) {
    // The work package requested in the address does not exist: we say so, and do not open another one instead.
    return (
      <PageHeader crumbs={[{ label: t("All document batches"), href: "#/workpackages" }]} title={t("A munkacsomag nem található")}
        summary={<><span className="mono">{wpId}</span>: {t("nincs ilyen azonosítójú munkacsomag (vagy törölték). Válassz a listából.")}</>} />
    );
  }
  if (wp.error) return <p className="notice error" role="alert">{wp.error.message}</p>;
  if (!wp.data) return <p className="muted">{t("Betöltés…")}</p>;
  const view = wp.data;
  if (view.case) return <CasePage caseId={view.case.id} />;  // 231 (A6): a case's container shows its case
  const { workpackage, next, last_run: last } = view;
  const stage: Stage = route.stage ?? next.stage;
  const status = stageStatus(view);
  // 176: what the package's rule shows (231 C3b5a: by its page part; none for a package of no rule)
  const part = partOf(view);
  const labels = STAGE_LABEL;

  const summary: ReactNode = (
    <>
      {part?.summary?.(view) ?? null}
      {itemCountText(workpackage.items)}
      {last ? ` · ${t("utolsó futás: {{mode}}, {{when}}", { mode: MODE[last.mode].toLowerCase(), when: when(last.created_at) })}` : ` · ${t("még nem futott")}`}
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
  // the next-step button; not needed if we are already on that stage's page
  const nextButton = next.stage !== stage || route.stage === undefined ? (
    <button type="button" className="primary" onClick={() => go({ view: "workpackages", wpId, stage: next.stage })}>{nextStepText(view)} →</button>
  ) : <span className="next-hint">{t("Következő lépés: {{step}}", { step: nextStepText(view) })}</span>;

  // U2a (the owner's decision of 2026-10-28: one work list): a case step's batch leads back to its case and step; any
  // other batch to the list of every batch
  const owner = view.owner_case;
  const crumbs = owner
    ? [{ label: t("Cases"), href: "#/cases" },
       { label: owner.name, href: routeHash({ view: "cases", caseId: owner.id, tab: owner.tab ?? undefined }) },
       ...(owner.step_title ? [{ label: t(owner.step_title) }] : [])]
    : [{ label: t("All document batches"), href: "#/workpackages" }];
  return (
    <>
      <PageHeader compact crumbs={crumbs} title={workpackage.name}
        summary={<>{summary}{scopeOf}{workflowOf}</>}
        actions={<><OwnerPicker view={view} onChanged={wp.reload} />{nextButton}<WorkpackageActions view={view} onChanged={wp.reload} /></>} />
      {workpackage.status === "archived" ? (
        <p className="notice">{t("Ez a csomag el van rejtve a listából; a futásai és az eredményei megmaradtak. Visszahozni a „Csomag kezelése” gombbal lehet.")}</p>
      ) : null}
      <div className="stage-tabs" role="tablist" aria-label={t("A csomag szakaszai")}>
        {(Object.keys(labels) as Stage[]).map((s, i) => (
          <a key={s} role="tab" aria-selected={stage === s} className={`stage-tab ${next.stage === s ? "is-next" : ""}`} href={`#/workpackages/${wpId}/${s}`}>
            <span className="stage-no" aria-hidden="true">{i + 1}</span>
            <span className="stage-text"><strong>{labels[s]}</strong><span className="small">{status[s]}</span></span>
          </a>
        ))}
      </div>
      <div role="tabpanel" aria-label={labels[stage]}>
        {stage === "process" && route.start ? <StartConfirm view={view} mode={route.start.mode} rerun={route.start.rerun} pending={route.start.pending} onChanged={wp.reload} /> : null}
        {stage === "process" && !route.start ? <ProcessStage view={view} adding={!!route.add} onChanged={wp.reload} /> : null}
        {stage === "review" ? (
          view.runs ? (
            <>
              <ReviewWorkspace wp={workpackage} itemId={route.itemId} onChanged={wp.reload} currentRunId={view.current_run?.run_id}
                openRuns={view.open_runs} />
              <details className="details mt">
                {/* 167: the title names adding too (the owner did not find it behind "Manage documents"); 168: the same
                    item list as in Processing (DECISIONS 168) */}
                <summary>{t("The package's items: add, open, download, remove")}</summary>
                <PackageItemsPanel view={view} onChanged={wp.reload} />
              </details>
            </>
          ) : (
            <>
              <p className="notice">{t("A csomagon még nem futott feldolgozás, ezért nincs mit ellenőrizni. Az iratok itt megnyithatók és letölthetők; a feldolgozást a")}{" "}
                <a href={`#/workpackages/${wpId}/process`}>{STAGE_LABEL.process}</a> {t("szakaszban indíthatod.")}</p>
              <PackageItemsPanel view={view} onChanged={wp.reload} />
            </>
          )
        ) : null}
        {/* 140: what a logic pack shows above the result (a statement package: its statements and its party's months) */}
        {stage === "result" ? part?.resultPanel?.(view) ?? null : null}
        {/* 231 (C1c): a package offers the cases of the processes that read it (an email package: the email routing) */}
        {stage === "result" && view.intake?.length ? <PackageIntake offers={view.intake} /> : null}
        {stage === "result" ? <ResultStage view={view} table={route.table} runId={route.runId} onChanged={wp.reload} /> : null}
      </div>
    </>
  );
}
