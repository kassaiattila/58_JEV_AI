// 231 (plan stage A, A7e; DECISIONS 231): the general elements of a case's page, any process pack may show them: what a
// send step sent (handover_view), a reply step's wait (reply_wait), the case's events (timeline) and what its steps
// spent (cost). Each renders the data its step's capability gives (jav/app/sending.py, jav/app/replies.py,
// jav/app/case_views.py); a person's actions are the step's own (`actions`), and the send itself is the step's start.
import { useState, type ReactNode } from "react";
import { api, ApiError, type ApprovalState, type CaseCost, type CaseEvent, type CaseKept, type CasePartnerLink, type HandoverAttempt, type HandoverData, type ReplyData, type StartedCase, type SubCaseData } from "../api";
import { ApprovalStateNotes, EarlierVersions, ReturnControl } from "../components/ApprovalPanel";
import { errorText } from "../hooks";
import { t, useLocale } from "../i18n";
import { fileName, MODE as MODE_OF_RUN, moneyText, providerName, RUN_STATUS, saidText, stepLabel, tmap, when } from "../labels";
import { handoverStatus, replyStatus, subCaseStatus } from "./caseStatus";
import type { ElementProps } from "./registry";

const loading = <p className="muted">{t("Loading…")}</p>;

const MODE = tmap({ output_folder: "Into the output folder", outlook_draft: "As an Outlook draft", outlook_send: "Out through Outlook" });
const MODE_HELP = tmap({
  output_folder: "The message is written into the output folder as an email file; Outlook opens it as a message to send.",
  outlook_draft: "The message is put among the drafts of your Outlook; you send it from there.",
  outlook_send: "The message goes out through Outlook, only to the addresses an owner allowed.",
});
const ATTEMPT = tmap({ recorded: "Recorded", sent: "Being handed over", acknowledged: "Handed over", uncertain: "Arrival unknown",
                       failed: "Failed" });
const ATTEMPT_MARK: Record<HandoverAttempt["status"], string> = {
  recorded: "s-queued", sent: "s-running", acknowledged: "s-done", uncertain: "s-warn", failed: "s-failed",
};

/** A step's actions as buttons (the step's own: a failed step's retry, whether a message arrived, a reply). */
function StepActions({ p, primary }: { p: ElementProps; primary?: string }) {
  useLocale();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const step = p.element.step;
  // D-f2: an action with a form is its step's own element's, not a button here
  const actions = ((step && p.page.steps[step]?.actions) || []).filter((a) => !a.form);
  if (!step || !actions.length) return null;
  const act = async (name: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.caseStepAction(p.caseId, step, name);
      p.onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="button-row">
        {actions.map((a) => (
          <button key={a.name} type="button" className={a.name === primary ? "primary" : "secondary"} disabled={busy}
            onClick={() => void act(a.name)}>{t(a.label)}</button>
        ))}
      </div>
      {error ? <p className="notice error small" role="alert">{error}</p> : null}
    </>
  );
}

export function HandoverView(p: ElementProps) {
  useLocale();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const d = p.element.data as HandoverData | null;
  const stepId = p.element.step;
  const step = stepId ? p.page.steps[stepId] : undefined;
  if (!d || !stepId || !step) return loading;
  const state = handoverStatus(p);
  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.startCaseStep(p.caseId, stepId);
      p.onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const settling = (step.actions ?? []).some((a) => a.name === "delivered");
  return (
    <section className="card" aria-label={t("Sending")}>
      <div className="card-head">
        <h2>{t("Sending")}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      <dl className="kv">
        <dt>{t("Way")}</dt><dd>{MODE[d.mode] ?? d.mode}</dd>
        {d.mode === "output_folder" ? (
          <><dt>{t("Output folder")}</dt>
            <dd>{d.output_folder ? <span className="mono">{d.output_folder}</span>
              : <span className="status s-warn">{t("Not set: Settings › Work folders")}</span>}</dd></>
        ) : null}
      </dl>
      {step.awaiting_start ? (
        <>
          <p className="muted small">{MODE_HELP[d.mode]}</p>
          <div className="button-row">
            <button type="button" className="primary" disabled={busy} onClick={() => void send()}>{t("Send")}</button>
          </div>
        </>
      ) : null}
      {settling ? (
        <p className="status long s-warn">
          {t("The handover was interrupted, so it is not known whether the message arrived. Check it, then say what happened.")}
        </p>
      ) : null}
      {step.state === "failed" && step.note && step.note !== d.attempts[d.attempts.length - 1]?.error
        ? <p className="status long s-failed">{t(step.note)}</p> : null}
      <StepActions p={p} />
      {d.attempts.length ? (
        <table className="table compact" aria-label={t("Handovers")}>
          <thead><tr><th>{t("Attempt")}</th><th>{t("Outcome")}</th><th>{t("File")}</th><th>{t("Recipient")}</th><th>{t("When")}</th></tr></thead>
          <tbody>
            {d.attempts.map((a) => (
              <tr key={a.attempt}>
                <td className="num">{a.attempt}</td>
                <td><span className={`status ${ATTEMPT_MARK[a.status]}`}>{ATTEMPT[a.status]}</span>
                  {a.error ? <div className="muted small">{t(a.error)}</div> : null}</td>
                <td>{a.file_name ?? "–"}{a.receipt?.path ? <div className="muted small mono" title={a.receipt.path}>{fileName(dirOf(a.receipt.path))}</div> : null}</td>
                <td>{a.to ?? "–"}</td>
                <td className="tnum">{when(a.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {error ? <p className="notice error small" role="alert">{error}</p> : null}
    </section>
  );
}

const dirOf = (path: string) => path.replace(/[\\/][^\\/]*$/, "");

export function ReplyWait(p: ElementProps) {
  useLocale();
  const d = p.element.data as ReplyData | null;
  if (!d) return loading;
  const state = replyStatus(p);
  const rows: [string, ReactNode][] = [];
  if (d.since) rows.push([t("Waiting since"), <span className="tnum">{when(d.since)}</span>]);
  if (d.reminded_at) rows.push([t("Follow-up opened"), <span className="tnum">{when(d.reminded_at)}</span>]);
  else if (d.remind_at && !d.reply) rows.push([t("Follow-up on"), <span className="tnum">{when(d.remind_at)}</span>]);
  if (d.reply) rows.push([t("Recorded by"), <>{d.by ?? "–"} · <span className="tnum">{when(d.at)}</span></>]);
  if (d.note) rows.push([t("Note"), d.note]);
  return (
    <section className="card" aria-label={t("Follow-up")}>
      <div className="card-head">
        <h2>{t("Follow-up")}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      {rows.length ? <dl className="kv">{rows.map(([k, v]) => <FragmentRow key={k} label={k} value={v} />)}</dl> : null}
      {d.follow_up === "open" ? (
        <p className="muted small">{t("No reply came in the days the process sets. Record the reply, or remind them and keep waiting (there is no further reminder).")}</p>
      ) : d.state === "running" ? (
        <p className="muted small">{t("When the reply arrives, record it here. If none comes, a follow-up task opens in Waiting for me.")}</p>
      ) : null}
      <StepActions p={p} primary={d.follow_up === "open" ? "replied" : undefined} />
    </section>
  );
}

function FragmentRow({ label, value }: { label: string; value: ReactNode }) {
  return <><dt>{label}</dt><dd>{value}</dd></>;
}

const EVENT = tmap({
  started: "The case started", step_started: "Started", step_done: "Done", step_failed: "Failed", step_retried: "Started again",
  handover_acknowledged: "Handed over", handover_failed: "The handover failed", handover_uncertain: "Arrival unknown",
  timer_fired: "The follow-up time came", closed: "The case closed", case_reopened: "The case reopened", reopened: "Reopened",
  order_overridden: "Started out of order", held: "Held", resumed: "Resumed", stale: "To redo",
  task_opened: "Waits for a person", task_reopened: "Waits for a person again", task_decided: "A person decided",
  task_withdrawn: "No longer needed", task_expired: "The deadline passed", task_assigned: "Assigned", task_due_set: "Deadline set",
});
/** A person's decision on a task, by the task's kind: what they did (the answer follows). */
const DECIDED = tmap({ step_start: "Started the step", handover_settle: "Said whether it arrived", follow_up: "Closed the follow-up" });
const TASK = tmap({ step_start: "the step's start", handover_settle: "whether it arrived", follow_up: "the follow-up",
                    approval: "the approval" });
const ANSWER = tmap({ acknowledged: "it arrived", failed: "it did not arrive", replied: "a reply arrived",
                     not_needed: "no reply is needed", keep_waiting: "reminded, keep waiting" });

function eventText(e: CaseEvent): string {
  const task = e.detail.task_kind;
  const answer = e.detail.answer ? ANSWER[e.detail.answer] ?? e.detail.answer : undefined;
  const what = e.kind === "task_decided" && task && DECIDED[task] ? DECIDED[task]
    : task && TASK[task] ? `${EVENT[e.kind] ?? e.kind}: ${TASK[task]}` : EVENT[e.kind] ?? e.kind;
  return [what, answer].filter(Boolean).join(" — ");
}

/** D0-d: the shared approval of a step whose domain shows no approval of its own: its state (approved with its version,
 *  out of date, returned, or not approved yet), the earlier versions, and returning it with a reason while it is not
 *  approved. Approving is the step's domain's (it shows what is approved). */
export function GeneralApproval(p: ElementProps) {
  useLocale();
  const state = (p.element.data as { approval?: ApprovalState } | null)?.approval ?? null;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!state) return <p className="muted">{t("Loading…")}</p>;
  const step = p.element.step ?? "";
  const back = (reason: string) => {
    setBusy(true);
    setError(null);
    return api.returnCaseStep(p.caseId, step, reason)
      .then(() => { p.onChanged(); return true; })
      .catch((e) => { setError(errorText(e)); return false; })
      .finally(() => setBusy(false));
  };
  const active = state.active;
  return (
    <section className="card" aria-label={t("Approval")}>
      <div className="card-head"><h2>{t("Approval")}</h2></div>
      {active ? (
        <p className="notice ok-box">
          {t("Approved: version {{n}}, by {{who}}, {{when}}.", { n: active.version, who: active.approved_by, when: when(active.approved_at) })}
        </p>
      ) : <p className="muted small">{t("Not approved yet.")}</p>}
      <ApprovalStateNotes state={state} />
      {!active && p.page.case.status !== "archived" ? <ReturnControl busy={busy} onReturn={back} /> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      <EarlierVersions versions={state.versions} />
    </section>
  );
}

/** D0-z: the process core's own notes in the interface's language (a person's note is shown as written). */
const MACHINE_NOTES = tmap({ "the case closed": "the case closed", "the step moved on": "the step moved on",
  "the case's other steps are done": "the case's other steps are done", "the package was deleted": "the package was deleted",
  "its case's approving step has its own task": "its case's approving step has its own task",
  "its package was brought with the workflow": "its package was brought with the workflow" });
const noteText = (note: string) => MACHINE_NOTES[note] ?? note;

/** D0-e: the versions a case keeps from its start to its end: a price list's, a template's, the rule files'. */
function KeptLine({ kept }: { kept: CaseKept }) {
  const parts = kept.resources.map((r) => r.version != null
    ? t("{{label}}: {{name}}, version {{n}}", { label: t(r.label), name: t(r.name), n: r.version })
    : t("{{label}}: {{name}}", { label: t(r.label), name: t(r.name) }));
  if (kept.rules.length) {
    parts.push(t("rule files: {{files}}", { files: kept.rules.map((f) => `${f.file} ${f.version ?? ""}`.trim()).join(", ") }));
  }
  return <div className="muted small">{t("It keeps from its start: {{what}}", { what: parts.join(" · ") })}</div>;
}

export function Timeline(p: ElementProps) {
  useLocale();
  const d = p.element.data as { events: CaseEvent[] } | null;
  if (!d) return loading;
  return (
    <section className="card wide" aria-label={t("Events")}>
      <div className="card-head"><h2>{t("Events")}</h2><span className="muted small tnum">{t("{{n}} event(s)", { n: d.events.length })}</span></div>
      <table className="table compact">
        <thead><tr><th>{t("When")}</th><th>{t("Step")}</th><th>{t("What happened")}</th><th>{t("Who")}</th></tr></thead>
        <tbody>
          {d.events.map((e, i) => (
            <tr key={`${e.at}-${i}`}>
              <td className="tnum">{when(e.at)}</td>
              <td>{e.step_title ? t(e.step_title) : "–"}</td>
              <td>{eventText(e)}{e.detail.reasons?.length
                ? <div className="muted small">{e.detail.reasons.map(saidText).join("; ")}</div>
                : e.detail.note ? <div className="muted small">{noteText(e.detail.note)}</div> : null}
                {e.detail.kept ? <KeptLine kept={e.detail.kept} /> : null}</td>
              <td>{e.who ?? <span className="muted">{t("The system")}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function CostView(p: ElementProps) {
  useLocale();
  const d = p.element.data as CaseCost | null;
  if (!d) return loading;
  return (
    <section className="card" aria-label={t("Cost")}>
      <div className="card-head"><h2>{t("Cost")}</h2><span className="tnum">{moneyText(d.total_usd)} USD</span></div>
      {d.lines.length ? (
        <table className="table compact">
          <thead><tr><th>{t("Step")}</th><th>{t("Service")}</th><th className="num">{t("Calls")}</th>
            <th className="num">{t("Earlier answers")}</th><th className="num">{t("Cost (USD)")}</th></tr></thead>
          <tbody>
            {d.lines.map((l) => (
              <tr key={`${l.step}-${l.provider}`}>
                <td>{t(l.step_title)}</td><td>{providerName(l.provider)}</td><td className="num">{l.calls}</td>
                <td className="num">{l.reused}</td>
                <td className="num">{moneyText(l.cost_usd)}{Number(l.open_usd) > 0
                  ? <div className="muted small">{t("+ up to {{usd}} not settled", { usd: moneyText(l.open_usd) })}</div> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted small">{t("No step of this case has called a paid service.")}</p>}
    </section>
  );
}

/** 231 (C1c): the cases started from an item of the work packages the case reads (an email routing's emails started
 *  IT quotes): each with its process and state, linked to its page. */
export function StartedCases({ element }: ElementProps) {
  useLocale();
  const rows = element.data as StartedCase[] | null;
  if (!rows) return loading;
  if (!rows.length) return <p className="muted">{t("No case has been started from these emails yet.")}</p>;
  return (
    <table className="table compact" aria-label={t("Started cases")}>
      <thead><tr><th>{t("Case")}</th><th>{t("Process")}</th><th>{t("State")}</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td><a href={`#/cases/${encodeURIComponent(r.id)}`}>{r.name}</a></td>
            <td>{r.process ? t(r.process) : "–"}</td>
            <td>{r.status === "closed" ? t("Case closed") : t("Case open")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const OUTCOME = tmap({ done: "done", cancelled: "cancelled", gone: "deleted" });

/** 261 (B1a): a sub-case's work in a few words: its documents, its current run's open to-dos and the run's state. */
export function workText(work: NonNullable<SubCaseData["case"]>["work"]): string | null {
  const parts = (work ?? []).flatMap((w) => [
    w.documents != null ? t("{{n}} documents", { n: w.documents }) : null,
    w.todos != null ? (w.todos ? t("To-dos: {{n}}", { n: w.todos }) : t("no to-dos")) : null,
    w.run ? `${MODE_OF_RUN[w.run.mode] ?? w.run.mode}: ${(w.run.approved ? t("approved") : RUN_STATUS[w.run.status] ?? t(w.run.status)).toLowerCase()}` : null,
  ]).filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** 261 (plan B, B1b; the owner's decision of 2026-10-29: one sub-work table): a multi-step case's sub-cases as rows of
 *  one table, each with its step, its state and why, its work and its case (with its own next step), and a stopped
 *  step's retry. */
export function SubWorkTable({ rows }: { rows: ElementProps[] }) {
  useLocale();
  if (!rows.length) return null;
  const at = (id: string, tab?: string) => `#/cases/${encodeURIComponent(id)}${tab ? `/${encodeURIComponent(tab)}` : ""}`;
  return (
    <section className="card wide" aria-label={t("Sub-work")}>
      <div className="card-head"><h2>{t("Sub-work")}</h2></div>
      <table className="table compact" aria-label={t("Sub-work")}>
        <thead><tr><th>{t("Step")}</th><th>{t("State")}</th><th>{t("Work")}</th><th>{t("Its case")}</th><th aria-label={t("Actions")} /></tr></thead>
        <tbody>
          {rows.map((p) => {
            const d = p.element.data as SubCaseData | null;
            const step = p.element.step ? p.page.steps[p.element.step] : undefined;
            const title = step?.title ? t(step.title) : d?.process ? t(d.process) : t("Sub-case");
            // U1: a step a closed case never reached is not waiting any more
            const never = p.page.case.status !== "open" && step && step.state !== "done" && step.state !== "failed";
            const state = never ? { mark: "s-waiting", text: t("Did not run") } : subCaseStatus(d);
            const sub = d?.case;
            const next = sub?.next;
            const why = never ? t("The case closed before this step ran.")
              : !sub && d?.state === "waiting" ? t("Starts once the steps before it are done.")
              : d?.state === "failed" && step?.note ? t(step.note) : null;
            return (
              <tr key={p.element.step ?? title} aria-label={title}>
                <th scope="row">{title}{d?.process ? <div className="small muted">{t(d.process)}</div> : null}</th>
                <td>
                  {state ? <span className={`status ${state.mark}`}>{state.text}</span> : "–"}
                  {next && sub ? <div className="small"><a href={at(sub.id, next.tab)}>{stepLabel(next.code, next.params, next.label)}</a></div> : null}
                  {why ? <div className="small muted">{why}</div> : null}
                </td>
                <td className="small">{workText(sub?.work) ?? "–"}</td>
                <td>
                  {sub ? <a href={at(sub.id)}>{sub.name}</a> : "–"}
                  {d?.earlier.length ? (
                    <div className="small muted">{t("Earlier cases of the step:")}{" "}
                      {d.earlier.map((e, i) => (
                        <span key={e.case_id}>{i ? ", " : ""}<a href={at(e.case_id)}>{OUTCOME[e.outcome] ?? e.outcome}</a></span>
                      ))}
                    </div>
                  ) : null}
                </td>
                <td><StepActions p={p} primary="retry" /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

/** 231 (B1): the partners the case is about (its pack's partner links): linked, or what its record gives with the
 *  partner it seems to be; a person links that one, or records the values as a new partner and links it. */
export function PartnerLink(p: ElementProps) {
  useLocale();
  const d = p.element.data as { links: CasePartnerLink[] } | null;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ text: string; other: string | null } | null>(null);
  if (!d) return loading;
  if (!d.links.length) return null;
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      p.onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? { text: e.message, other: e.code === "partner_conflict" ? e.detail.other ?? null : null }
        : { text: String(e), other: null });
    } finally {
      setBusy(false);
    }
  };
  const record = (link: CasePartnerLink) => act(async () => {
    const made = await api.createPartner({ name: link.proposal!.name, tax_number: link.proposal!.tax_number ?? null,
      email: link.proposal!.email ?? null, phone: link.proposal!.phone ?? null, address: link.proposal!.address ?? null,
      note: null, roles: [link.role] });
    await api.linkCasePartner(p.caseId, link.role, made.partner_id);
  });
  return (
    <section className="card" aria-label={t("Partners")}>
      <div className="card-head"><h2>{t("Partners")}</h2><a className="small" href="#/settings/partners">{t("The partner register")}</a></div>
      {d.links.map((link) => (
        <div key={link.role} className="partner-link">
          <dl className="kv">
            <dt>{t(link.role_label)}</dt>
            <dd>
              {link.partner ? (
                <><strong>{link.partner.name}</strong>{link.partner.tax_number ? <span className="mono muted"> · {link.partner.tax_number}</span> : null}
                  {" "}<span className="status s-done">{t("Linked")}</span></>
              ) : link.proposal ? (
                <><strong>{link.proposal.name}</strong>{link.proposal.tax_number ? <span className="mono muted"> · {link.proposal.tax_number}</span> : null}
                  {link.proposal.email ? <span className="muted"> · {link.proposal.email}</span> : null}</>
              ) : <span className="muted">{t("The record names none.")}</span>}
            </dd>
          </dl>
          {!link.partner && link.match ? (
            <div className="button-row">
              <span className="small">{t("It seems to be {{name}} in the partner register.", { name: link.match.name })}</span>
              <button type="button" className="secondary small-btn" disabled={busy}
                onClick={() => void act(() => api.linkCasePartner(p.caseId, link.role, link.match!.partner_id))}>{t("Link it")}</button>
            </div>
          ) : !link.partner && link.proposal ? (
            <div className="button-row">
              <span className="muted small">{t("Not in the partner register yet.")}</span>
              <button type="button" className="secondary small-btn" disabled={busy} onClick={() => void record(link)}>{t("Record as a partner")}</button>
            </div>
          ) : null}
          {error ? (
            <p className="notice error small" role="alert">
              {error.text}
              {error.other ? <> {" "}<button type="button" className="link-btn" disabled={busy}
                onClick={() => void act(() => api.linkCasePartner(p.caseId, link.role, error.other!))}>{t("Link that one")}</button></> : null}
            </p>
          ) : null}
        </div>
      ))}
    </section>
  );
}

