// Review of an email item (048 T2): the email on the left (header, attachments, body), the recognised intent, the
// proposed next step and the to-dos on the right. There are no extracted fields or page images here; the attachments
// can be processed separately as documents.
import { useEffect, useState } from "react";
import { api, ApiError, type ItemResult, type RejectedTask } from "../api";
import { IntakeOffers } from "../elements/IntakeOffers";
import { ITEM_PARTS } from "../logic/registry";
import { EngineMark } from "../components/EngineMark";
import { Icon } from "../components/Icon";
import { Picker } from "../components/Picker";
import { getLocale, t, useLocale } from "../i18n";
import { docTypeLabel, intentLabel, intentOptions, nextFlowText, reasonText, TASK_ACTION, tmap, when } from "../labels";
import { Split } from "./Split";
import { useResolve } from "./useResolve";

export function EmailReview({ data, onChanged, wpId }: { data: ItemResult; onChanged: () => void; wpId?: string }) {
  useLocale();
  const m = data.email!;
  const r = m.result;
  const { resolve, pending: resolving, error: resolveError } = useResolve(onChanged);
  return (
    <Split
      left={
        <article className="mail-view" aria-label={t("The email")}>
          {/* 086 (audit N04): the email as the item was added, never a later version's text */}
          {m.source_status === "changed" ? (
            <p className="notice error" role="alert">{t("The version of the email this item processed can no longer be found, so its text cannot be shown.")}</p>
          ) : m.source_status === "earlier" ? (
            <p className="notice">{t("This email has since arrived again with a changed content; the version that was processed is shown here.")}</p>
          ) : null}
          <h2>{m.subject || <span className="muted">{t("(without subject)")}</span>}</h2>
          <dl className="mail-meta">
            <dt>{t("Sender")}</dt><dd>{m.sender_name ? `${m.sender_name} <${m.sender ?? ""}>` : m.sender ?? "–"}</dd>
            <dt>{t("To")}</dt><dd>{m.to.join(", ") || "–"}</dd>
            <dt>{t("Received")}</dt><dd>{when(m.received_at)}</dd>
            <dt>{t("Attachment")}</dt><dd>{m.attachments.length ? m.attachments.join(", ") : t("none")}</dd>
          </dl>
          <BodyCoverage c={m.body_coverage} />
          <div className="mail-body">{m.body ? <MailText text={m.body} /> : <span className="muted">{t("(empty email)")}</span>}</div>
        </article>
      }
      right={
        <section className="panel" aria-label={t("Intent and to-dos")}>
          {resolveError ? <p className="notice error" role="alert">{resolveError}</p> : null}
          {data.open_reasons.length ? (
            <ul className="issues" aria-label={t("Open to-dos in this run")}>
              {data.open_reasons.map((x) => (
                <li key={x.id} className="issue"><span>{reasonText(x.reason)}</span>
                  <button type="button" className="secondary small-btn" disabled={resolving !== null} onClick={() => void resolve(x)}><Icon name="check" />{t("Resolved")}</button></li>
              ))}
            </ul>
          ) : <p className="ok pad-s">{t("There are no open to-dos for this email in this run.")}</p>}
          {r ? (
            <div className="intent-box">
              <div className="muted small">{t("Detected intent")}</div>
              <div className="intent">{r.sent ? t("Sent message: its intent is not asked")
                : r.intent ? intentLabel(r.intent) : r.intent_label ?? t("could not be detected")}</div>
              {r.corrected ? (
                <div className="small">{r.machine_intent && r.machine_intent !== r.intent
                  ? t("Corrected by hand (the machine said: {{intent}})", { intent: intentLabel(r.machine_intent) })
                  : t("Confirmed by hand")}</div>
              ) : r.confidence != null ? <div className="small">{t("Model confidence: {{p}}%", { p: Math.round(r.confidence * 100) })}</div> : null}
              {!r.corrected && data.engine ? <div className="mt-s"><EngineMark engine={data.engine} /></div> : null}
              <IntentEditor data={data} onChanged={onChanged} />
              <TasksPanel data={data} onChanged={onChanged} />
              <div className="small mt-s">{t("Suggested next step:")} <strong>{nextFlowText(r.next_flow, r.next_flow_reads_text)}</strong></div>
              {!r.from_this_run ? <p className="notice small mt-s">{t("This result comes from a later run on the same email.")}</p> : null}
            </div>
          ) : <p className="muted pad-s">{t("This run has not processed the email yet.")}</p>}
          {/* 231 (C1a): the processes whose case this email may start (until then the quote's own part) */}
          {data.intake?.length ? <IntakeOffers offers={data.intake} /> : null}
          {/* 192: what other domains add under the email, by the registry */}
          {Object.entries(data.parts ?? {}).map(([name, value]) => {
            const shown = ITEM_PARTS[name];
            return shown ? <div key={name}>{shown(value)}</div> : null;
          })}
          {r && r.attachments.length ? (
            <div className="pad-s">
              <div className="muted small">{t("Attachment detection")}</div>
              <ul className="plain small">
                {r.attachments.map((a, i) => <li key={i}>{a.filename}: {a.shown_type ?? a.doc_type ? docTypeLabel((a.shown_type ?? a.doc_type)!) : a.status ? ATTACHMENT_STATUS[a.status] ?? a.status : "–"}</li>)}
              </ul>
            </div>
          ) : null}
          {data.attachment_items?.length ? (
            // 058 K5.2: the attachment ran as a document in this run: the extraction result is in its own view
            <div className="pad-s">
              <div className="muted small">{t("Attachment data")}</div>
              <ul className="plain small">
                {data.attachment_items.map((a) => (
                  <li key={a.item_id}><a href={wpId ? `#/workpackages/${wpId}/review/${encodeURIComponent(a.item_id)}` : undefined}>{t("{{file}}: extraction result", { file: a.filename })} →</a></li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      }
    />
  );
}

/** 058 K5.1: manual correction of the intent. The correction is versioned (like a document's fields); saving closes the
 *  run's own intent to-dos, and the routing is computed from the corrected intent. It cannot be corrected on an
 *  approved run. */
function IntentEditor({ data, onChanged }: { data: ItemResult; onChanged: () => void }) {
  useLocale();
  const current = data.email?.result?.intent ?? null;
  const [value, setValue] = useState<string | null>(current);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setValue(current), [current, data.item_id]);
  const save = async () => {
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      await api.saveCorrection(data.run_id, data.item_id, { fields: { intent: value }, expected_revision: data.correction.revision });
      onChanged();
    } catch (e) {
      const err = e as ApiError;
      setError(err.status === 409 ? t("Someone else corrected this email in the meantime. We refreshed it; review and save again.") : err.message);
      onChanged();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="intent-edit mt-s">
      <Picker label={t("Correct the intent")} value={value} options={intentOptions()} onChange={setValue} />
      <button type="button" className="secondary small-btn" disabled={busy || !value || (value === current && !!data.email?.result?.corrected)}
        onClick={() => void save()}>{value === current ? t("Confirm") : t("Save correction")}</button>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </div>
  );
}

/** 058 K5.3: the task proposals (after the evidence gate in code). A proposal is only a proposal: only a person can
 *  accept or reject it; once they have decided on all of them, the email's „javaslat vár döntésre” (proposal awaiting
 *  a decision) to-do is closed. */
function TasksPanel({ data, onChanged }: { data: ItemResult; onChanged: () => void }) {
  useLocale();
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tv = data.email?.tasks;
  if (!tv) return null;
  if (tv.status === "skipped") return <p className="muted small mt-s">{t("Task proposal: not requested for an email to be archived.")}</p>;
  if (tv.status === "error") return <p className="notice error small mt-s">{t("The task proposal failed ({{why}}); it is listed among the to-dos.", { why: tv.error ?? "?" })}</p>;
  const decide = async (index: number, decision: "accepted" | "rejected" | "done" | "undone") => {
    setBusy(index);
    setError(null);
    try {
      const state = tv.tasks.find((x) => x.index === index)?.decision_state;
      if (decision === "done" || decision === "undone") await api.markTaskDone(data.run_id, data.item_id, index, decision === "done", state);
      else await api.decideTask(data.run_id, data.item_id, index, decision, state);
      onChanged();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="task-box mt-s">
      <div className="muted small">{t("Task proposals (only a person can accept them)")}</div>
      {tv.tasks.length === 0 ? <p className="small">{t("No task follows from this email.")}</p> : (
        <ul className="plain task-list">
          {tv.tasks.map((tk) => (
            <li key={tk.index} className="task-item">
              <div><strong>{tk.title}</strong> <span className="muted small">· {TASK_ACTION[tk.action] ?? tk.action}</span>
                {tk.merged ? <span className="muted small"> · {t("{{n}} identical proposals merged", { n: tk.merged + 1 })}</span> : null}</div>
              {tk.due_date ? <div className="small">{t("Deadline: {{date}}", { date: tk.due_date })}</div> : null}
              {tk.assignee_hint ? <div className="small">{t("Assignee: {{who}}", { who: tk.assignee_hint })}</div> : null}
              <div className="small muted">{t("Evidence:")} {tk.evidence.map((e) => `„${e.quote}”`).join(" · ")}</div>
              {tk.decision ? (
                <div className="small">{tk.decision.decision === "accepted"
                  ? t("Accepted by {{who}}", { who: tk.decision.actor }) : t("Rejected by {{who}}", { who: tk.decision.actor })}</div>
              ) : null}
              {tk.decision?.done_at ? (
                <div className="small"><strong>{t("Done by {{who}}, {{when}}", { who: tk.decision.done_by ?? "", when: when(tk.decision.done_at) })}</strong></div>
              ) : null}
              <div className="button-row">
                <button type="button" className="secondary small-btn" disabled={busy !== null || tk.decision?.decision === "accepted"}
                  onClick={() => void decide(tk.index, "accepted")}><Icon name="check" />{t("Accept")}</button>
                <button type="button" className="quiet small-btn" disabled={busy !== null || tk.decision?.decision === "rejected"}
                  onClick={() => void decide(tk.index, "rejected")}>{t("Discard")}</button>
                {tk.decision?.decision === "accepted" ? (tk.decision.done_at
                  ? <button type="button" className="quiet small-btn" disabled={busy !== null} onClick={() => void decide(tk.index, "undone")}>{t("Undo done")}</button>
                  : <button type="button" className="secondary small-btn" disabled={busy !== null} onClick={() => void decide(tk.index, "done")}><Icon name="check" />{t("Done (task)")}</button>) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      {tv.rejected.length ? <RejectedTasks rejected={tv.rejected} /> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </div>
  );
}

/** 062: the content of the dropped proposals and the parts that failed, so that one can judge whether dropping them
 *  was justified. */
function RejectedTasks({ rejected }: { rejected: RejectedTask[] }) {
  useLocale();
  const partLabel: Record<string, string> = {
    task: t("the task (unknown kind or empty title)"), evidence: t("the task's evidence"), due_date: t("the deadline"), assignee: t("the assignee"),
  };
  return (
    <details className="small mt-s">
      <summary className="muted">{t("{{n}} proposals failed the evidence check (not a verbatim quote, invented deadline or assignee).", { n: rejected.length })}</summary>
      <ul className="plain task-list">
        {rejected.map((r, n) => (
          <li key={r.index ?? `x${n}`} className="task-item">
            {r.title ? (
              <>
                <div><strong>{r.title}</strong>{r.action ? <span className="muted"> · {TASK_ACTION[r.action] ?? r.action}</span> : null}</div>
                {r.due_date ? <div>{t("Deadline: {{date}}", { date: r.due_date })}</div> : null}
                {r.assignee_hint ? <div>{t("Assignee: {{who}}", { who: r.assignee_hint })}</div> : null}
                {r.failed_parts?.length ? <div>{t("Not verifiable: {{parts}}", { parts: r.failed_parts.map((p) => partLabel[p] ?? p).join(", ") })}</div> : null}
                {(r.quotes ?? []).map((q, k) => (
                  <div key={k} className={q.ok ? "muted" : undefined}>
                    „{q.quote}” – {q.ok ? t("found verbatim") : t("not verbatim in the email")}
                  </div>
                ))}
              </>
            ) : <div className="muted">{t("The proposal text was not kept for this earlier run.")}</div>}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** 058 K5.1: how much of the email body the intent recognition saw (the end of the email may only be missing if this
 *  is flagged). */
function BodyCoverage({ c }: { c?: NonNullable<ItemResult["email"]>["body_coverage"] }) {
  useLocale();
  if (!c) return null;
  if (c.status === "capped") {
    return <p className="notice error small">{t("The email text may have been cut at download (at {{n}} characters): the end may be missing, and intent recognition did not see it either.", { n: c.chars.toLocaleString(getLocale()) })}</p>;
  }
  if (c.status === "shortened") {
    return <p className="notice small">{t("Intent recognition saw only the beginning of the email text: {{seen}} / {{all}} characters.", { seen: c.seen_chars.toLocaleString(getLocale()), all: c.own_chars.toLocaleString(getLocale()) })}</p>;
  }
  return c.quoted_removed ? <p className="muted small">{t("Intent recognition saw the email's own text in full, but not the quoted earlier message.")}</p> : null;
}

// 058: the processing status of the attachment in everyday words (instead of the local service's code)
const ATTACHMENT_STATUS: Record<string, string> = tmap({
  unsupported: "not readable (image or other format)",
  name_only: "only its name is known",
  needs_ocr: "needs text recognition",
  unreadable: "the PDF cannot be read (corrupt or too large)",
});

const URL_RE = /<?(https?:\/\/[^\s<>"]+)>?/g;

/** Splits the email body into pieces: plain text and links (the host name is shown in place of the link). */
export function splitLinks(text: string): ({ text: string } | { url: string; host: string })[] {
  const out: ({ text: string } | { url: string; host: string })[] = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    if (m.index! > last) out.push({ text: text.slice(last, m.index) });
    let host = m[1];
    try {
      host = new URL(m[1]).host;
    } catch {
      /* malformed link: the full text stays */
    }
    out.push({ url: m[1], host });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}

/** 058: a short marker instead of long tracking links (the host name, with the full address in the tooltip). The link
 *  is deliberately not clickable: the UI does not open links from an outside email. */
function MailText({ text }: { text: string }) {
  useLocale();
  return (
    <>
      {splitLinks(text).map((part, i) => ("url" in part
        ? <span key={i} className="mail-link" title={part.url}>{t("link: {{host}}", { host: part.host })}</span>
        : <span key={i}>{part.text}</span>))}
    </>
  );
}
