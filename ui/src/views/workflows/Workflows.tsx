// 146 (backlog F-package-kind-chooser; DECISIONS 146): the Workflows main menu. The list (filtered by party, state and a
// search), the new work wizard, and a workflow's control view: its steps as a chain, each with its state, its package
// and the package's next step, what needs a person first, the switch of the automatic chain, a step's start (with a new
// budget when its run's estimate did not fit) and an existing package linked as a step. 147: a workflow is repeated for
// the next period (the wizard opens filled in), and the two are linked both ways.
import { Fragment, useEffect, useState } from "react";
import {
  api, ApiError, type WorkflowBrief, type WorkflowBudget, type WorkflowRow, type WorkflowStep, type WorkflowView,
} from "../../api";
import { PageHeader } from "../../components/PageHeader";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { ENGINE, stepLabel, usdBudget } from "../../labels";
import { go, wpHash, type Route } from "../../route";
import { budgetSum, budgetText, PROVIDER, sourceText, STEP_STATUS, stepMark, stepNote } from "./labels";
import { NewWork } from "./NewWork";

export function Workflows({ route }: { route: Extract<Route, { view: "workflows" }> }) {
  if (route.wfId) return <WorkflowControl wfId={route.wfId} />;
  return <WorkflowList creating={Boolean(route.create)} repeatOf={route.repeat} />;
}

/** 157: a step's state as a state mark in its own colour, never the action colour. */
function StepState({ status }: { status: WorkflowStep["status"] }) {
  useLocale();
  return <span className={`status s-${stepMark(status)}`}>{STEP_STATUS[status] ?? status}</span>;
}

function WorkflowList({ creating, repeatOf }: { creating: boolean; repeatOf?: string }) {
  useLocale();
  const [archived, setArchived] = useState(false);
  const [party, setParty] = useState("");
  const [state, setState] = useState<"all" | "attention" | "done">("all");
  const [search, setSearch] = useState("");
  const list = useLoad(`workflows:${archived}`, () => api.workflows(archived), 10000);
  const rows = (list.data?.workflows ?? []).filter((w) =>
    (!party || w.party_id === party)
    && (state === "all" || (state === "done" ? w.done === w.total : w.done < w.total && w.next !== null))
    && (!search.trim() || `${w.name} ${w.party} ${w.template_title}`.toLowerCase().includes(search.trim().toLowerCase())));
  const parties = [...new Map((list.data?.workflows ?? []).map((w) => [w.party_id, w.party])).entries()];
  return (
    <>
      <PageHeader title={t("Workflows")} badge={list.data ? <span className="count">{list.data.workflows.length}</span> : null}
        summary={t("A workflow chains the work packages of one job for an own party and a period: invoices, statements and their reconciliation. Its page shows where the chain stands and what needs you.")}
        actions={<a className={creating ? "button secondary" : "button primary"} href={creating ? "#/workflows" : "#/workflows/new"} aria-expanded={creating}>{t("New workflow")}</a>} />
      {creating ? <NewWork key={repeatOf ?? "new"} initialGroup="monthly" repeatOf={repeatOf}
        onPackage={(id) => go({ view: "workpackages", wpId: id, stage: "process" })}
        onWorkflow={(id) => go({ view: "workflows", wfId: id })} /> : null}
      <div className="toolbar wf-filters">
        <label className="inline small">{t("Search")}<input value={search} onChange={(e) => setSearch(e.target.value)} /></label>
        <label className="inline small">{t("Own party")}
          <select value={party} onChange={(e) => setParty(e.target.value)}>
            <option value="">{t("All")}</option>
            {parties.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label className="inline small">{t("State")}
          <select value={state} onChange={(e) => setState(e.target.value as typeof state)}>
            <option value="all">{t("All")}</option>
            <option value="attention">{t("Needs a person")}</option>
            <option value="done">{t("Every step done")}</option>
          </select>
        </label>
        <label className="check small"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> {t("Archived ones too")}</label>
      </div>
      {list.error ? <p className="notice error" role="alert">{list.error.message}</p> : null}
      {list.data && !rows.length ? <p className="muted">{list.data.workflows.length ? t("No workflow matches the filters.") : t("No workflow yet. Make one with New workflow.")}</p> : null}
      {rows.length ? (
        <table className="table compact wf-list" aria-label={t("Workflows")}>
          <thead><tr><th>{t("Name")}</th><th>{t("Own party")}</th><th>{t("Period")}</th><th>{t("Steps")}</th><th>{t("Next")}</th></tr></thead>
          <tbody>{rows.map((w) => <WorkflowListRow key={w.id} w={w} />)}</tbody>
        </table>
      ) : null}
    </>
  );
}

function WorkflowListRow({ w }: { w: WorkflowRow }) {
  useLocale();
  const next = w.next ? w.steps.find((s) => s.id === w.next!.step) : null;
  return (
    <tr className={w.status === "archived" ? "muted" : undefined}>
      <td><a href={`#/workflows/${encodeURIComponent(w.id)}`}><strong>{w.name}</strong></a><div className="small muted">{t(w.template_title)}</div></td>
      <td>{w.party}</td>
      <td className="wf-period">{w.period_start} – {w.period_end}</td>
      <td>
        <span className="small">{t("{{done}} of {{total}} done", { done: w.done, total: w.total })}</span>
        <div className="wz-chain small">{w.steps.map((s, i) => (
          <Fragment key={s.id}>{i ? <span aria-hidden="true"> → </span> : null}<span title={STEP_STATUS[s.status]} className={`status s-${stepMark(s.status)}`}>{t(s.title)}</span></Fragment>
        ))}</div>
      </td>
      <td>{next && w.next ? <div className="wf-next-cell"><span>{t(next.title)}</span> <StepState status={w.next.status} /></div> : w.done === w.total ? t("Every step done") : "–"}</td>
    </tr>
  );
}

// --- the control view -----------------------------------------------------------------------------------------------------

function WorkflowControl({ wfId }: { wfId: string }) {
  useLocale();
  const loaded = useLoad(`workflow:${wfId}`, () => api.workflowView(wfId), 5000);
  const [view, setView] = useState<WorkflowView | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 153 (review D3): an action's answer is shown until the next loaded view arrives (asked for right after the action).
  // Before, it was kept while its `updated_at` was not older, and the steps' states are computed live, so the view
  // froze after any action until the page was reloaded.
  useEffect(() => setView(null), [loaded.data]);
  const v = view && view.workflow.id === wfId ? view : loaded.data;

  async function act(fn: () => Promise<WorkflowView>) {
    setError(null);
    try {
      setView(await fn());
      loaded.reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  if (loaded.error) return <p className="notice error" role="alert">{loaded.error.status === 404 ? t("The workflow was not found.") : loaded.error.message}</p>;
  if (!v) return <p className="muted">{t("Loading…")}</p>;
  const wf = v.workflow;
  const nextStep = v.next ? v.steps.find((s) => s.id === v.next!.step) : null;
  return (
    <>
      <PageHeader title={wf.name}
        summary={t("{{template}} · {{party}}, {{from}} – {{to}} · {{done}} of {{total}} steps done", {
          template: t(wf.template_title), party: wf.party, from: wf.period_start, to: wf.period_end, done: v.done, total: v.total })}
        actions={<>
          <label className="check small"><input type="checkbox" checked={wf.auto} disabled={wf.status !== "open"}
            onChange={(e) => void act(() => api.updateWorkflow(wf.id, { auto: e.target.checked }))} /> {t("Start the steps by themselves")}</label>
          <a className="button secondary small-btn" href={`#/workflows/${encodeURIComponent(wf.id)}/repeat`}>{t("Repeat for the next period")}</a>
          <button type="button" className="secondary small-btn" onClick={() => void act(() => api.updateWorkflow(wf.id, { archived: wf.status === "open" }))}>
            {wf.status === "open" ? t("Archive") : t("Restore")}
          </button>
        </>} />
      {v.repeat_of || v.repeated_as?.length ? (
        <p className="small wf-repeats">
          {v.repeat_of ? <>{t("Repeats:")} <BriefLink w={v.repeat_of} /></> : null}
          {v.repeat_of && v.repeated_as?.length ? " · " : null}
          {v.repeated_as?.length ? <>{t("Repeated as:")} {v.repeated_as.map((w, i) => <Fragment key={w.id}>{i ? ", " : null}<BriefLink w={w} /></Fragment>)}</> : null}
        </p>
      ) : null}
      {wf.status === "archived" ? <p className="notice">{t("This workflow is archived: its steps do not start. Its packages stay as they are.")}</p> : null}
      {nextStep && v.next ? (
        <p className="notice wf-next" role="status">
          <strong>{t("Next: {{step}}", { step: t(nextStep.title) })}</strong> <StepState status={v.next.status} />
          {nextStep.package ? <> · <a href={wpHash(nextStep.package.id, nextStep.package.next?.stage)}>{t("Open its package")}</a></> : null}
        </p>
      ) : v.done === v.total ? <p className="notice ok" role="status">{t("Every step is done.")}</p> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      <ol className="wf-chain" aria-label={t("Steps")}>
        {v.steps.map((s, i) => (
          <Fragment key={s.id}>
            {i ? <li className="wf-arrow" aria-hidden="true">→</li> : null}
            {/* 157: the step that needs a person first has a firm border and the view's one solid button */}
            <li className="wf-step" aria-current={v.next?.step === s.id ? "step" : undefined}>
              {/* 153 (review D3): a step that turns to another status gets a new form (a budget it now needs) */}
              <StepCard key={`${s.id}:${s.status}`} step={s} steps={v.steps} open={wf.status === "open"} isNext={v.next?.step === s.id}
                onStart={(budget) => void act(() => api.startWorkflowStep(wf.id, s.id, budget))}
                onLink={(wpId) => void act(() => api.linkWorkflowStep(wf.id, s.id, wpId))} />
            </li>
          </Fragment>
        ))}
      </ol>
      <details>
        <summary className="small">{t("What happened ({{n}})", { n: v.events.length })}</summary>
        <ul className="small wf-events">
          {v.events.map((e, i) => (
            <li key={i}><span className="wf-when">{e.created_at.replace("T", " ").slice(0, 16)}</span> · {e.actor} · {e.step ? `${t(v.steps.find((s) => s.id === e.step)?.title ?? e.step)}: ` : ""}{eventText(e.action, e.detail)}</li>
          ))}
        </ul>
      </details>
    </>
  );
}

function BriefLink({ w }: { w: WorkflowBrief }) {
  return <a href={`#/workflows/${encodeURIComponent(w.id)}`}>{w.name}</a>;
}

function eventText(action: string, detail: Record<string, unknown>): string {
  if (action === "left_out") {  // 147: only the new documents of the folder
    return t("{{new}} new document(s); {{left}} already processed by a live run, left out", { new: Number(detail.new ?? 0), left: Number(detail.left_out ?? 0) });
  }
  const words: Record<string, string> = {
    create: "the workflow was made", update: "the workflow was changed", pull: "the mailbox download was queued",
    pull_interrupted: "the mailbox download was interrupted; the emails that arrived were packaged",  // 160 (review R-1)
    run: "its live run started", package: "its package was made", needs_budget: "its run's estimate is over its budget",
    budget: "its budget was changed", nothing_new: "nothing new", failed: "it did not start", link: "an existing package was linked",
  };
  return words[action] ? t(words[action]) : action;
}

function StepCard({ step, steps, open, isNext, onStart, onLink }: {
  step: WorkflowStep; steps: WorkflowStep[]; open: boolean; isNext: boolean; onStart: (budget?: WorkflowBudget) => void;
  onLink: (wpId: string) => void;
}) {
  useLocale();
  const waitsFor = steps.filter((s) => step.after.includes(s.id) && !s.done).map((s) => t(s.title));
  const over = step.status === "needs_budget" && step.note && typeof step.note === "object" ? step.note : null;
  const [budget, setBudget] = useState<WorkflowBudget>(() => (over ? roundedUp(over.estimate) : step.budget));
  const canStart = open && ["ready", "waiting", "failed", "needs_budget"].includes(step.status);
  // 155/157: a button that starts a run shows what the run may spend (the budget given here, or the step's)
  const cap = budgetSum(over ? clean(budget) : step.budget);
  const spendNote = cap > 0 ? t("Starts a run that can spend up to {{usd}}", { usd: usdBudget(cap) }) : undefined;
  return (
    <div className="wf-card">
      <div className="wf-card-head">
        <strong>{t(step.title)}</strong>
        <StepState status={step.status} />
      </div>
      <div className="small muted">{t(step.kind_title)} · {sourceText(step)}</div>
      {step.status === "waiting" && waitsFor.length ? <div className="small">{t("Waits for: {{steps}}", { steps: waitsFor.join(", ") })}</div> : null}
      {step.package ? (
        <div className="small">
          <a href={wpHash(step.package.id, step.package.next?.stage)}>{step.package.name ?? step.package.id}</a>
          {step.package.next ? <> · {stepLabel(step.package.next.code, step.package.next.params as Record<string, unknown> | undefined, step.package.next.label)}</> : null}
        </div>
      ) : null}
      {step.status === "failed" && typeof step.note === "string" ? <div className="small warn-text">{step.note}</div> : null}
      {step.status === "nothing_new" && typeof step.note === "string" ? <div className="small muted">{stepNote(step.note)}</div> : null}
      {step.engine ? <div className="small">{t("AI engine: {{engine}}", { engine: ENGINE[step.engine] })}</div> : null}
      {Object.keys(step.budget).length || over ? <div className="small">{t("Budget: {{budget}}", { budget: budgetText(step.budget) })}</div> : null}
      {over ? (
        <div className="wz-budget">
          <span className="small warn-text">{t("Its run would reserve at most {{estimate}}: more than its budget.", { estimate: budgetText(over.estimate) })}</span>
          {(["jev", "openai", "azure_di"] as const).map((p) => (
            <label key={p} className="inline small">{PROVIDER[p]}
              <input type="number" min={0} max={1000} step={0.01} value={budget[p] ?? ""} aria-label={t("{{provider}} budget of {{step}}", { provider: PROVIDER[p], step: t(step.title) })}
                onChange={(e) => setBudget({ ...budget, [p]: e.target.value })} />
            </label>
          ))}
        </div>
      ) : null}
      {canStart ? (
        <div className="button-row">
          <button type="button" className={isNext && step.status !== "waiting" ? "primary small-btn" : "secondary small-btn"}
            title={spendNote} onClick={() => onStart(over ? clean(budget) : undefined)}>
            {over ? t("Start with this budget") : step.status === "failed" ? t("Try again") : step.status === "waiting" ? t("Start now anyway") : t("Start")}
            {cap > 0 ? <span className="spend" aria-hidden="true">≤ {usdBudget(cap)}</span> : null}
          </button>
          {["ready", "waiting", "failed"].includes(step.status) ? <LinkPackage step={step} onLink={onLink} /> : null}
        </div>
      ) : null}
    </div>
  );
}

function roundedUp(budget: WorkflowBudget): WorkflowBudget {
  return Object.fromEntries(Object.entries(budget).map(([p, v]) => [p, (Math.ceil(Number(v) * 100) / 100).toFixed(2)]));
}

function clean(budget: WorkflowBudget): WorkflowBudget {
  return Object.fromEntries(Object.entries(budget).filter(([, v]) => v !== undefined && v !== "" && Number(v) >= 0));
}

const PACKAGE_KINDS: Record<string, string[]> = {
  documents: ["folder", "manual", "watch", "upload"], emails: ["mailbox"], statements: ["statements"], reconcile: ["reconcile"],
};

function LinkPackage({ step, onLink }: { step: WorkflowStep; onLink: (wpId: string) => void }) {
  useLocale();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState("");
  const list = useLoad(open ? "workpackages-brief" : null, api.workpackagesBrief);  // 154: the name and the kind are enough
  if (!open) return <button type="button" className="secondary small-btn" onClick={() => setOpen(true)}>{t("Use an existing package…")}</button>;
  const options = (list.data?.workpackages ?? []).filter((w) => PACKAGE_KINDS[step.kind].includes(w.source_kind));
  return (
    <span className="inline small">
      <select value={choice} onChange={(e) => setChoice(e.target.value)} aria-label={t("Work package for {{step}}", { step: t(step.title) })}>
        <option value="">{t("Choose…")}</option>
        {options.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
      <button type="button" className="secondary small-btn" disabled={!choice} onClick={() => onLink(choice)}>{t("Link")}</button>
    </span>
  );
}
