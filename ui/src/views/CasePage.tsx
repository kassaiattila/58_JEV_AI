// 231 (plan stage A, A6; DECISIONS 231): a process pack's case. Its tabs are the ones its pack describes, each built
// from registered screen elements (ui/src/elements/registry.tsx) with the data the service sent for them; the page
// looks like a work package's (the same header and numbered tabs). While a step waits for a job or the worker, the
// page asks again every few seconds.
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { api, type CaseView } from "../api";
import { PageHeader } from "../components/PageHeader";
import { ELEMENTS, type ElementProps } from "../elements/registry";
import { useLoad } from "../hooks";
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

/** Whether a step waits for a job or the worker (not for a person), so the page should ask again soon. */
const moving = (page: CaseView) => page.case.status === "open"
  && Object.values(page.steps).some((s) => s.state === "ready" || (s.state === "running" && !s.awaiting_start && !PEOPLE.has(s.waiting_for ?? "")));

export function CasePage({ caseId, tab }: { caseId: string; tab?: string }) {
  useLocale();
  const [poll, setPoll] = useState(false);
  const page = useLoad(`case:${caseId}`, () => api.casePage(caseId), poll ? 3000 : undefined);
  // the case's container is a work package: its owner and its actions menu, as on a work package's page
  const container = useLoad(`wp:${caseId}`, () => api.workpackage(caseId));
  const active = page.data ? moving(page.data) : false;
  useEffect(() => setPoll(active), [active]);

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
  const props = (element: ElementProps["element"]): ElementProps => ({ caseId, element, page: view, onChanged: page.reload });
  const all = view.tabs.flatMap((x) => x.elements);
  const summary: ReactNode = all.map((e) => ELEMENTS[e.type]?.summary?.(props(e))).find(Boolean) ?? t(view.case.title);
  const statusOf = (elements: ElementProps["element"][]) => elements.map((e) => ELEMENTS[e.type]?.status?.(props(e))).find(Boolean) ?? "";
  const next = view.next?.tab ?? defaultTab(view);
  const reload = () => { page.reload(); container.reload(); };
  // the next-step button; a hint instead when its tab is the one shown (as on a work package's page)
  const nextStep = view.next ? stepLabel(view.next.code, view.next.params, view.next.label) : null;
  const nextButton = !view.next || !nextStep ? null : view.next.tab !== shown.id || tab === undefined ? (
    <button type="button" className="primary" onClick={() => go({ view: "cases", caseId, tab: view.next!.tab })}>{nextStep} →</button>
  ) : <span className="next-hint">{t("Next step: {{step}}", { step: nextStep })}</span>;

  return (
    <>
      <PageHeader compact crumbs={[{ label: t("Cases"), href: "#/cases" }]} title={view.case.name ?? t(view.case.title)}
        summary={summary}
        actions={container.data ? <><OwnerPicker view={container.data} onChanged={reload} />{nextButton}<WorkpackageActions view={container.data} onChanged={reload} /></> : nextButton} />
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
          const spec = ELEMENTS[e.type];
          return <div key={`${e.type}-${e.step ?? ""}-${i}`}>{spec ? spec.render(props(e)) : null}</div>;
        })}
      </div>
    </>
  );
}
