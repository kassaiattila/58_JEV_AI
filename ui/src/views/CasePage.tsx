// 231 (plan stage A, A6; DECISIONS 231): a process pack's case. Its tabs are the ones its pack describes, each built
// from registered screen elements (ui/src/elements/registry.tsx) with the data the service sent for them; the page
// looks like a work package's (the same header and numbered tabs). While a step waits for a job or the worker, the
// page asks again every few seconds.
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { api, type CaseView } from "../api";
import { PageHeader } from "../components/PageHeader";
import { elementOf, type ElementProps } from "../elements/registry";
import { errorText, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { stepLabel } from "../labels";
import { go } from "../route";
import { WorkpackageActions } from "./WorkpackageActions";
import { OwnerPicker } from "./WorkpackageDetail";

/** The tab a case opens on: the tab of its first step not done yet (its last tab when every step is done). */
function defaultTab(page: CaseView): string {
  const open = Object.entries(page.steps).find(([, s]) => s.state !== "done");
  const tab = open ? page.tabs.find((x) => x.elements.some((e) => e.step === open[0])) : undefined;
  return (tab ?? page.tabs[page.tabs.length - 1]).id;
}

/** What a step may wait for that only a person or the other side ends (A7e: a task, the letter's acceptance, a reply). */
const PEOPLE = new Set(["approval", "task_closed", "acceptance", "reply"]);

/** Whether a step waits for a job or the worker (not for a person), so the page should ask again soon; 231 (C2d): a
 *  step of a capability that waits for a person's decisions (the pairing, the routing) does not. U-A8: nor while the
 *  worker has something to do for the case (`due`: a person's decision it takes at its next round). */
export const moving = (page: CaseView) => page.case.status === "open" && (page.case.due === true
  || Object.values(page.steps).some((s) => s.state === "ready"
    || (s.state === "running" && s.waits_on === "work")  // U1: a person's step whose wait is the machine's (a live run)
    || (s.state === "running" && !s.awaiting_start && !s.by_person && !PEOPLE.has(s.waiting_for ?? ""))));

/** U1: how long the page asks again after a person's action, for a step that looks again on its own (a letter's step
 *  checks for its acceptance every few seconds rather than being told), so the next step shows without a reload. */
const SETTLE_MS = 12000;
export const settling = (until: number | null, now: number) => until !== null && now <= until;

/** 231 (U1; the owner's decision of 2026-10-28): what may follow a closed case - another process a person starts from
 *  its documents - or the case started from it. */
function FollowUps({ caseId, view }: { caseId: string; view: CaseView }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const items = view.case.status !== "open" ? view.follow_ups ?? [] : [];
  if (!items.length) return null;
  const start = async (pack: string) => {
    setBusy(true);
    setError(null);
    try {
      const made = await api.caseFollowUp(caseId, pack);
      go({ view: "cases", caseId: made.case_id });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="button-row">
      {items.map((f) => f.case_id
        ? <a key={f.pack} href={`#/cases/${encodeURIComponent(f.case_id)}`}>{t("Followed by: {{case}}", { case: f.case_id })}</a>
        : <button key={f.pack} type="button" className="primary" disabled={busy} onClick={() => void start(f.pack)}>{t(f.title)} →</button>)}
      {error ? <span className="notice error small" role="alert">{error}</span> : null}
    </div>
  );
}

export function CasePage({ caseId, tab }: { caseId: string; tab?: string }) {
  useLocale();
  const [poll, setPoll] = useState(false);
  const [settleUntil, setSettleUntil] = useState<number | null>(null);
  const page = useLoad(`case:${caseId}`, () => api.casePage(caseId), poll ? 3000 : undefined);
  // the case's container is a work package: its owner and its actions menu, as on a work package's page
  const container = useLoad(`wp:${caseId}`, () => api.workpackage(caseId));
  const active = (page.data ? moving(page.data) : false) || settling(settleUntil, Date.now());
  useEffect(() => setPoll(active), [active]);
  useEffect(() => {  // U1: the settling ends by itself
    if (settleUntil === null) return;
    const timer = setTimeout(() => setSettleUntil(null), Math.max(0, settleUntil - Date.now()) + 50);
    return () => clearTimeout(timer);
  }, [settleUntil]);
  const changed = () => { page.reload(); setSettleUntil(Date.now() + SETTLE_MS); };
  // 261 (Q-rogzites-409): an action's answer is the case's page after it: shown at once, before any reload ends
  const answered = (fresh: CaseView) => { page.replace(fresh); setSettleUntil(Date.now() + SETTLE_MS); };

  if (page.error?.status === 404 || page.error?.status === 422) {
    return (
      <PageHeader crumbs={[{ label: t("Cases"), href: "#/cases" }]} title={t("The case was not found")}
        summary={<><span className="mono">{caseId}</span>: {t("there is no case with this identifier.")}</>} />
    );
  }
  if (page.error) return <p className="notice error" role="alert">{page.error.message}</p>;
  if (!page.data) return <p className="muted">{t("Loading…")}</p>;
  const view = page.data;
  const shown = view.tabs.find((x) => x.id === tab) ?? view.tabs.find((x) => x.id === defaultTab(view)) ?? view.tabs[0];
  const props = (element: ElementProps["element"]): ElementProps => ({ caseId, element, page: view, onChanged: changed, onView: answered });
  const all = view.tabs.flatMap((x) => x.elements);
  const summary: ReactNode = all.map((e) => elementOf(e.type)?.summary?.(props(e))).find(Boolean) ?? t(view.case.title);
  const statusOf = (elements: ElementProps["element"][]) => elements.map((e) => elementOf(e.type)?.status?.(props(e))).find(Boolean) ?? "";
  const next = view.next?.tab ?? defaultTab(view);
  const reload = () => { page.reload(); container.reload(); };
  // the next-step button; a hint instead when its tab is the one shown (as on a work package's page)
  const nextStep = view.next ? stepLabel(view.next.code, view.next.params, view.next.label) : null;
  const nextButton = !view.next || !nextStep ? null : view.next.tab !== shown.id || tab === undefined ? (
    <button type="button" className="primary" onClick={() => go({ view: "cases", caseId, tab: view.next!.tab })}>{nextStep} →</button>
  ) : <span className="next-hint">{t("Next step: {{step}}", { step: nextStep })}</span>;

  // 231 (U2c): a sub-case leads back to the case it is part of, at the step that runs it
  const parent = view.case.parent;
  const crumbs = [{ label: t("Cases"), href: "#/cases" },
    ...(parent ? [{ label: `${parent.name} · ${t(parent.step_title)}`, href: `#/cases/${encodeURIComponent(parent.id)}` }] : [])];
  return (
    <>
      <PageHeader compact crumbs={crumbs} title={view.case.name ?? t(view.case.title)}
        summary={summary}
        actions={container.data ? <><OwnerPicker view={container.data} onChanged={reload} />{nextButton}<WorkpackageActions view={container.data} onChanged={reload} /></> : nextButton} />
      <FollowUps caseId={caseId} view={view} />
      {/* A7e: one row however many tabs the pack has (the package page's three by default) */}
      <div className="stage-tabs" role="tablist" aria-label={t("The case's steps")} style={{ "--tabs": view.tabs.length } as CSSProperties}>
        {view.tabs.map((x, i) => (
          <a key={x.id} role="tab" aria-selected={shown.id === x.id} className={`stage-tab ${next === x.id ? "is-next" : ""}`}
            href={`#/cases/${encodeURIComponent(caseId)}/${encodeURIComponent(x.id)}`}>
            <span className="stage-no" aria-hidden="true">{i + 1}</span>
            <span className="stage-text"><strong>{t(x.label)}</strong><span className="small" title={statusOf(x.elements) || undefined}>{statusOf(x.elements)}</span></span>
          </a>
        ))}
      </div>
      <div role="tabpanel" aria-label={t(shown.label)}>
        {shown.elements.map((e, i) => {
          const spec = elementOf(e.type);
          // U1: a step a closed case never reached is not waiting any more; its card would say it is
          const step = e.step ? view.steps[e.step] : undefined;
          if (view.case.status !== "open" && step && step.state !== "done" && step.state !== "failed") {
            return (
              <section key={`${e.type}-${e.step ?? ""}-${i}`} className="card" aria-label={step.title ? t(step.title) : e.step ?? ""}>
                <div className="card-head"><h2>{step.title ? t(step.title) : e.step}</h2><span className="muted small">{t("Did not run")}</span></div>
                <p className="muted small">{t("The case closed before this step ran.")}</p>
              </section>
            );
          }
          // D0-a: the pack check refuses an element the interface cannot show; one that still comes is named, not hidden
          return <div key={`${e.type}-${e.step ?? ""}-${i}`}>{spec ? spec.render(props(e))
            : <p className="notice error" role="alert">{t("This screen element cannot be shown: {{type}}", { type: e.type })}</p>}</div>;
        })}
      </div>
    </>
  );
}
