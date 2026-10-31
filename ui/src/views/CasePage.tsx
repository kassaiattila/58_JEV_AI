// 231 (plan stage A, A6; DECISIONS 231): a process pack's case. Its tabs are the ones its pack describes, each built
// from registered screen elements (ui/src/elements/registry.tsx) with the data the service sent for them. While a step
// waits for a job or the worker, the page asks again every few seconds.
// 263 (plan E, E2; the owner's decisions of 2026-10-30: one case, one track): the case's page is the one place of its
// work. Its track shows the pack's tabs and a multi-step case's steps left to right (`caseTrack`), the log apart at its
// right end; a step that runs another process's case shows that case's work under it (`StepWork`), and a tab that is
// only a step's document batch shows the batch's stages (`EmbeddedBatch`). A sub-case and a batch of a case have no
// page of their own any more: their addresses lead here. The page's main action stands at the right end of the title
// row: the next step where it is done, when that is not the part shown (there, the part's own solid button is it).
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { api, type CaseElement, type CaseView, type PackageWorkView, type SubCaseData } from "../api";
import { PageActions, PageActionsSlot } from "../components/PageActions";
import { PageHeader } from "../components/PageHeader";
import { ActionButtons } from "../elements/ActionsElement";
import { subCaseStatus } from "../elements/caseStatus";
import { PackageWorkNote } from "../elements/PackageWork";
import { elementOf, type ElementProps } from "../elements/registry";
import { errorText, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { stepLabel, tmap } from "../labels";
import { batchOfCase, caseUnder, go, routeHash, type Route } from "../route";
import { CaseSettingsCard } from "./CaseSettings";
import { batchOf, caseTrack, defaultItem, packageOf, type TrackItem } from "./caseTrack";
import { WorkpackageActions } from "./WorkpackageActions";
import { EmbeddedBatch, OwnerPicker } from "./WorkpackageDetail";

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

/** 261 (B1b): a tab's elements in blocks, each from its place on the tab (`at`): a run of consecutive elements of a
 *  type shown as rows of one table (its spec's `rows`) is one block, any other element a block of its own. */
export function blocksOf(elements: CaseElement[]): { at: number; elements: CaseElement[] }[] {
  const out: { at: number; elements: CaseElement[] }[] = [];
  elements.forEach((e, i) => {
    const last = out[out.length - 1];
    if (last && last.elements[0].type === e.type && elementOf(e.type)?.rows) last.elements.push(e);
    else out.push({ at: i, elements: [e] });
  });
  return out;
}

/** 263 (E2): a case's step's batch on its case's page: the batch's address and the case whose page shows it. */
export interface CaseBatch { wpId: string; route: Extract<Route, { view: "workpackages" }> }

/** 263 (E2): the item of a case's track that shows a batch: the tab of its step's batch, or the step whose sub-case's
 *  work names it. */
export function itemOfBatch(items: TrackItem[], wpId: string): TrackItem | undefined {
  return items.find((x) => x.elements.some((e) => packageOf(e) === wpId
    || (x.kind === "step" && ((e.data as SubCaseData | null)?.case?.work ?? []).some((w) => w.batch === wpId))));
}

/** 263 (E2): where the case's next step is done - its track's item and, for a step that runs a sub-case, the sub-case's
 *  item - and its name: a sub-case's own next step, not "Continue in its sub-case". */
export function nextAt(view: CaseView, items: TrackItem[]): { item: string; sub?: string; label: string } | null {
  const next = view.next;
  if (!next) return null;
  if (next.code === "case_sub_case") {
    for (const x of items) {
      const d = x.kind === "step" ? (x.elements[0].data as SubCaseData | null) : null;
      if (d?.state !== "running" || !d.case) continue;
      const own = d.case.next;
      return own ? { item: x.id, sub: own.tab, label: stepLabel(own.code, own.params, own.label) }
        : { item: x.id, label: stepLabel(next.code, next.params, next.label) };
    }
  }
  return { item: next.tab, label: stepLabel(next.code, next.params, next.label) };
}

/** 263 (E2): a step's line on the track: its sub-case's open to-dos, else its own next step, else its state. */
function stepLine(view: CaseView, e: CaseElement): string {
  const d = e.data as SubCaseData | null;
  const step = e.step ? view.steps[e.step] : undefined;
  if (view.case.status !== "open" && step && step.state !== "done" && step.state !== "failed") return t("Did not run");
  const todos = (d?.case?.work ?? []).reduce((n, w) => n + (w.todos ?? 0), 0);
  if (d?.case?.status === "open" && todos) return t("To-dos: {{n}}", { n: todos });
  const own = d?.case?.status === "open" ? d.case.next : null;
  return own ? stepLabel(own.code, own.params, own.label) : subCaseStatus(d)?.text ?? "";
}

/** 263 (E2): a track - its items left to right, numbered when they are steps, the next one ringed - and its log apart
 *  at the right end. `sub`: a step's track under the case's, quieter. */
function TrackBar({ label, items, shown, next, href, line, log, logShown, sub }: {
  label: string; items: TrackItem[]; shown: string | null; next: string | null; href: (id: string) => string;
  line: (x: TrackItem) => string; log: TrackItem | null; logShown: boolean; sub?: boolean;
}) {
  return (
    <div className="track-row">
      <div className={`stage-tabs ${sub ? "sub-track" : "case-track"}`} role="tablist" aria-label={label}
        style={{ "--tabs": items.length } as CSSProperties}>
        {items.map((x) => {
          const text = line(x);
          return (
            <a key={`${x.kind}-${x.id}`} role="tab" aria-selected={shown === x.id} className={`stage-tab ${next === x.id ? "is-next" : ""}`}
              href={href(x.id)}>
              {x.n !== undefined ? <span className="stage-no" aria-hidden="true">{x.n}</span> : null}
              <span className="stage-text"><strong>{t(x.label)}</strong><span className="small" title={text || undefined}>{text}</span></span>
            </a>
          );
        })}
      </div>
      {log ? <LogLink href={href(log.id)} shown={logShown} line={line(log)} /> : null}
    </div>
  );
}

/** 263 (E2, the plan's rule 8): what is not a step - the case's events and cost - has no number and stands apart. */
function LogLink({ href, shown, line }: { href: string; shown: boolean; line?: string }) {
  return (
    <a className="track-log" href={href} aria-current={shown ? "page" : undefined}>
      <strong>{t("Log")}</strong>{line ? <span className="small">{line}</span> : null}
    </a>
  );
}

/** An item's elements, each block as its element shows it. */
function Blocks({ view, elements, props }: { view: CaseView; elements: CaseElement[]; props: (e: CaseElement) => ElementProps }) {
  return (
    <>
      {blocksOf(elements).map(({ at: i, elements: run }) => {
        const e = run[0];
        const spec = elementOf(e.type);
        const key = `${e.type}-${e.step ?? ""}-${i}`;
        // 261 (B1b): consecutive elements of a type shown as rows of one table (a multi-step case's sub-cases)
        if (spec?.rows) return <div key={key}>{spec.rows(run.map(props))}</div>;
        // U1: a step a closed case never reached is not waiting any more; its card would say it is
        const step = e.step ? view.steps[e.step] : undefined;
        if (view.case.status !== "open" && step && step.state !== "done" && step.state !== "failed") {
          return (
            <section key={key} className="card" aria-label={step.title ? t(step.title) : e.step ?? ""}>
              <div className="card-head"><h2>{step.title ? t(step.title) : e.step}</h2><span className="muted small">{t("Did not run")}</span></div>
              <p className="muted small">{t("The case closed before this step ran.")}</p>
            </section>
          );
        }
        // D0-a: the pack check refuses an element the interface cannot show; one that still comes is named, not hidden
        return <div key={key}>{spec ? spec.render(props(e))
          : <p className="notice error" role="alert">{t("This screen element cannot be shown: {{type}}", { type: e.type })}</p>}</div>;
      })}
    </>
  );
}

const OUTCOME = tmap({ done: "done", cancelled: "cancelled", gone: "deleted" });

/** 231 (U1; the owner's decision of 2026-10-28): what may follow a closed case - another process a person starts from
 *  its documents - or the case started from it; 261: the case it follows (the previous period's, or the closed case
 *  whose follow-up it is) and, for a case of a process repeated by period, its next period. 263 (E2): the links on one
 *  quiet line under the title, the buttons among the page's actions (one follow-up is the page's main action). */
function CaseLinks({ caseId, view }: { caseId: string; view: CaseView }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const items = view.case.status !== "open" ? view.follow_ups ?? [] : [];
  const next = view.next_period;
  const follows = view.case.follows;
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
  const at = (id: string) => `#/cases/${encodeURIComponent(id)}`;
  const links: ReactNode[] = [
    follows ? <a key="follows" href={at(follows)}>{t("Follows: {{case}}", { case: follows })}</a> : null,
    next?.case_id ? <a key="next" href={at(next.case_id)}>{t("Next period: {{case}}", { case: next.case_id })}</a> : null,
    ...items.filter((f) => f.case_id).map((f) => <a key={f.pack} href={at(f.case_id!)}>{t("Followed by: {{case}}", { case: f.case_id })}</a>),
  ].filter(Boolean);
  const starts = items.filter((f) => !f.case_id);
  return (
    <>
      {links.length || error ? (
        <p className="case-links small">
          {links.map((x, i) => <span key={i}>{i ? " · " : ""}{x}</span>)}
          {error ? <span className="notice error small" role="alert">{error}</span> : null}
        </p>
      ) : null}
      {(next && !next.case_id) || starts.length ? (
        <PageActions>
          {next && !next.case_id ? (
            <button type="button" className="secondary" onClick={() => go({ view: "case-list", create: true, pack: view.case.pack, after: caseId })}>
              {t("Next period")} →</button>
          ) : null}
          {starts.map((f) => (
            <button key={f.pack} type="button" className={starts.length === 1 ? "primary" : "secondary"} disabled={busy}
              onClick={() => void start(f.pack)}>{t(f.title)} →</button>
          ))}
        </PageActions>
      ) : null}
    </>
  );
}

/** 263 (E2): a step whose sub-case has not started, or stopped: its state, why, its earlier cases and its retry. */
function StepWaiting({ p, d, title }: { p: ElementProps; d: SubCaseData | null; title: string }) {
  const step = p.element.step ? p.page.steps[p.element.step] : undefined;
  const never = p.page.case.status !== "open" && step && step.state !== "done" && step.state !== "failed";
  const state = never ? { mark: "s-waiting", text: t("Did not run") } : subCaseStatus(d);
  const why = never ? t("The case closed before this step ran.")
    : d?.state === "failed" && step?.note ? t(step.note)
    : d?.state === "waiting" ? t("Starts once the steps before it are done.") : null;
  return (
    <section className="card wide" aria-label={title}>
      <div className="card-head">
        <h2>{title}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      {d?.process ? <p className="small muted">{t(d.process)}</p> : null}
      {why ? <p className="small">{why}</p> : null}
      <EarlierCases p={p} d={d} />
      <ActionButtons p={p} primary="retry" />
    </section>
  );
}

/** U2c / 263 (E2, H9): a retried step's earlier sub-cases, each opening under the step. */
function EarlierCases({ p, d, shown }: { p: ElementProps; d: SubCaseData | null; shown?: string }) {
  if (!d?.earlier.length) return null;
  return (
    <p className="small muted">{t("Earlier cases of the step:")}{" "}
      {d.earlier.map((e, i) => (
        <span key={e.case_id}>{i ? ", " : ""}{shown === e.case_id ? <strong>{OUTCOME[e.outcome] ?? e.outcome}</strong>
          : <a href={routeHash({ view: "cases", caseId: p.caseId, tab: p.element.step ?? "", of: e.case_id })}>{OUTCOME[e.outcome] ?? e.outcome}</a>}</span>
      ))}
    </p>
  );
}

/** 263 (E2; one case, one track): a step that runs a sub-case shows the sub-case's work under it - its batch's stages
 *  when it is only a batch, its own track otherwise - with the sub-case's log at the track's right end. `of`: an
 *  earlier sub-case of the step, read-only. */
function StepWork({ main, item, sub, of, batch, otherwise, onChanged }: {
  main: ElementProps; item: TrackItem; sub?: string; of?: string; batch?: CaseBatch; otherwise: ReactNode;
  onChanged: () => void;
}) {
  useLocale();
  const d = main.element.data as SubCaseData | null;
  const current = d?.case?.id ?? null;
  const earlier = of && of !== current && d?.earlier.some((e) => e.case_id === of) ? of : null;
  const subId = earlier ?? current;
  if (subId) caseUnder(subId, main.caseId);
  const [poll, setPoll] = useState(false);
  const page = useLoad(subId ? `case:${subId}` : null, () => api.casePage(subId!), poll ? 3000 : undefined);
  const active = page.data ? moving(page.data) : false;
  useEffect(() => setPoll(active), [active]);
  const title = t(item.label);
  if (!subId) return <><StepWaiting p={main} d={d} title={title} />{otherwise ? <PageActions>{otherwise}</PageActions> : null}</>;
  if (page.error) return <p className="notice error" role="alert">{page.error.message}</p>;
  if (!page.data) return <p className="muted">{t("Loading…")}</p>;
  const view = page.data;
  const changed = () => { page.reload(); onChanged(); };
  const props = (e: CaseElement): ElementProps => ({ caseId: subId, element: e, page: view, onChanged: changed,
    onView: (fresh) => { page.replace(fresh); onChanged(); } });
  const { items, log } = caseTrack(view);
  const href = (id: string) => routeHash({ view: "cases", caseId: main.caseId, tab: item.id, sub: id, ...(earlier ? { of: earlier } : {}) });
  const logShown = Boolean(log && sub === log.id);
  const statusOf = (x: TrackItem) => x.elements.map((e) => elementOf(e.type)?.status?.(props(e))).find(Boolean) ?? "";
  const head = (
    <>
      {earlier ? <p className="notice small" role="status">{t("An earlier case of this step, kept as it closed.")}</p> : null}
      {d?.state === "failed" ? <StepWaiting p={main} d={d} title={title} /> : null}
      {!earlier && d?.earlier.length && d.state !== "failed" ? <EarlierCases p={main} d={d} /> : null}
      {earlier ? <EarlierCases p={main} d={d} shown={earlier} /> : null}
    </>
  );
  const lone = items.length === 1 ? batchOf(items[0].elements) : null;
  if (lone) {
    batchOfCase(lone, subId);
    return (
      <>
        {head}
        <EmbeddedBatch wpId={lone} route={batch?.route ?? { view: "workpackages", wpId: lone }} onChanged={changed} level="sub"
          otherwise={otherwise} note={<PackageWorkNote data={items[0].elements[0].data as PackageWorkView | null} />}
          side={log ? <LogLink href={href(log.id)} shown={logShown} line={statusOf(log)} /> : null}
          body={logShown && log ? <Blocks view={view} elements={log.elements} props={props} /> : undefined} />
      </>
    );
  }
  const shown = logShown ? null : items.find((x) => x.id === sub) ?? defaultItem(view, items) ?? null;
  const own = view.next && !earlier ? view.next.tab : null;
  const nextButton = own && own !== shown?.id && view.next ? (
    <button type="button" className="primary" onClick={() => go({ view: "cases", caseId: main.caseId, tab: item.id, sub: own })}>
      {stepLabel(view.next.code, view.next.params, view.next.label)} →</button>
  ) : otherwise;
  const shownBatch = shown ? batchOf(shown.elements) : null;
  return (
    <>
      {head}
      <TrackBar label={t("The step's parts")} items={items} shown={shown?.id ?? null} next={own} href={href} line={statusOf}
        log={log} logShown={logShown} sub />
      {shownBatch ? (
        <EmbeddedBatch wpId={shownBatch} route={batch?.route ?? { view: "workpackages", wpId: shownBatch }} onChanged={changed} level="sub"
          otherwise={nextButton} note={<PackageWorkNote data={shown!.elements[0].data as PackageWorkView | null} />} />
      ) : (
        <>
          {nextButton ? <PageActions>{nextButton}</PageActions> : null}
          <div role="tabpanel" aria-label={shown ? t(shown.label) : t("Log")}>
            <Blocks view={view} elements={shown ? shown.elements : log?.elements ?? []} props={props} />
          </div>
        </>
      )}
    </>
  );
}

export function CasePage({ caseId, tab, sub, of, batch }: { caseId: string; tab?: string; sub?: string; of?: string; batch?: CaseBatch }) {
  useLocale();
  const [poll, setPoll] = useState(false);
  const [settleUntil, setSettleUntil] = useState<number | null>(null);
  const [slot, setSlot] = useState<HTMLElement | null>(null);
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
  // 263 (E2): a sub-case's address leads to its main case's page, under the step that runs it
  const parent = page.data?.case.parent;
  useEffect(() => {
    if (!parent) return;
    window.location.replace(batch ? routeHash({ ...batch.route, inCase: parent.id })
      : routeHash({ view: "cases", caseId: parent.id, tab: parent.step, ...(tab ? { sub: tab } : {}), of: caseId }));
  }, [parent, batch, tab, caseId]);

  if (page.error?.status === 404 || page.error?.status === 422) {
    return (
      <PageHeader crumbs={[{ label: t("Cases"), href: "#/cases" }]} title={t("The case was not found")}
        summary={<><span className="mono">{caseId}</span>: {t("there is no case with this identifier.")}</>} />
    );
  }
  if (page.error) return <p className="notice error" role="alert">{page.error.message}</p>;
  if (!page.data || parent) return <p className="muted">{t("Loading…")}</p>;
  const view = page.data;
  const props = (element: CaseElement): ElementProps => ({ caseId, element, page: view, onChanged: changed, onView: answered });
  const all = view.tabs.flatMap((x) => x.elements);
  const summary: ReactNode = all.map((e) => elementOf(e.type)?.summary?.(props(e))).find(Boolean) ?? t(view.case.title);
  const statusOf = (x: TrackItem) => x.kind === "step" ? stepLine(view, x.elements[0])
    : x.elements.map((e) => elementOf(e.type)?.status?.(props(e))).find(Boolean) ?? "";
  const reload = () => { page.reload(); container.reload(); };

  const { items, log } = caseTrack(view);
  const holding = batch ? itemOfBatch(items, batch.wpId) : undefined;
  const logShown = !batch && Boolean(log && tab === log.id);
  const shown = batch ? holding : logShown ? undefined : items.find((x) => x.id === tab) ?? defaultItem(view, items);
  const at = nextAt(view, items);
  const nextButton = at && at.item !== (logShown ? log?.id : shown?.id) ? (
    <button type="button" className="primary" onClick={() => go({ view: "cases", caseId, tab: at.item, ...(at.sub ? { sub: at.sub } : {}) })}>
      {at.label} →</button>
  ) : null;
  const href = (id: string) => routeHash({ view: "cases", caseId, tab: id });
  const logBody = log ? <><Blocks view={view} elements={log.elements} props={props} /><CaseSettingsCard caseId={caseId} pack={view.case.pack} /></> : null;
  // a case that is only its documents' batch (a Documents case): the batch's stages are its track
  const lone = items.length === 1 ? batchOf(items[0].elements) : null;
  if (lone) batchOfCase(lone, caseId);
  const shownBatch = shown && !lone ? (batch && holding === shown ? batch.wpId : batchOf(shown.elements)) : null;

  let body: ReactNode;
  if (lone) {
    body = (
      <EmbeddedBatch wpId={lone} route={batch?.route ?? { view: "workpackages", wpId: lone }} onChanged={changed} level="main"
        otherwise={nextButton} note={<PackageWorkNote data={items[0].elements[0].data as PackageWorkView | null} />}
        side={log ? <LogLink href={href(log.id)} shown={logShown} line={statusOf(log)} /> : null}
        body={logShown ? logBody : undefined} />
    );
  } else {
    const element = shown?.kind === "step" ? shown.elements[0] : null;
    body = (
      <>
        <TrackBar label={t("The case's steps")} items={items} shown={shown?.id ?? null} next={at?.item ?? null} href={href}
          line={statusOf} log={log} logShown={logShown} />
        {element && shown ? (
          <StepWork main={props(element)} item={shown} sub={tab === shown.id ? sub : undefined} of={of}
            batch={batch && holding === shown ? batch : undefined} otherwise={nextButton} onChanged={changed} />
        ) : shownBatch || (batch && !holding) ? (
          // a tab that is only a step's batch, or the batch of a step shown among other elements (its tab's), or a batch
          // the case's track does not name (an earlier sub-case's): its stages
          <EmbeddedBatch wpId={shownBatch ?? batch!.wpId} route={batch?.route ?? { view: "workpackages", wpId: shownBatch! }}
            onChanged={changed} level="sub" otherwise={nextButton}
            note={shown && batchOf(shown.elements) ? <PackageWorkNote data={shown.elements[0].data as PackageWorkView | null} /> : null} />
        ) : (
          <>
            {nextButton ? <PageActions>{nextButton}</PageActions> : null}
            <div role="tabpanel" aria-label={shown ? t(shown.label) : t("Log")}>
              {shown ? <Blocks view={view} elements={shown.elements} props={props} /> : logBody}
            </div>
          </>
        )}
      </>
    );
  }
  return (
    <div className="case-page">
      <PageHeader compact crumbs={[{ label: t("Cases"), href: "#/cases" }]} title={view.case.name ?? t(view.case.title)}
        summary={summary} actionsSlot={setSlot}
        actions={container.data ? <><OwnerPicker view={container.data} onChanged={reload} /><WorkpackageActions view={container.data} onChanged={reload} /></> : null} />
      <PageActionsSlot value={slot}>
        <CaseLinks caseId={caseId} view={view} />
        {body}
      </PageActionsSlot>
    </div>
  );
}
