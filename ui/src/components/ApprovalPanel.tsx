// 192 (plan F-quote-package B5; DECISIONS 192, the owner's choice "a shared element now"): the approval of a logic
// pack's own version, written once for the reconciliation and the quote. Approved: who and when, what the lock means, a
// change since, and reopening with a reason. Not yet: what the approval records, what blocks it, and the approval
// itself, the view's one solid action only when nothing blocks it. The earlier (reopened) versions are listed below.
// Each pack gives its own texts, blockers and actions; the service checks everything (jav/app/package_release.py).
// D0-d: a case's approving step's state shows too: out of date (a step it builds on has a new result; approve it again)
// and returned by a person with a reason; while it is not approved, a person may return it with a reason.
import { useState, type ReactNode } from "react";
import type { ApprovalState, OwnApproval, OwnVersion } from "../api";
import { t, useLocale } from "../i18n";
import { when } from "../labels";
import { ConfirmButton } from "./ConfirmButton";

export function ApprovalPanel(p: {
  approval: OwnApproval; archived: boolean; busy: boolean;
  /** beside the heading: a template choice, a download */
  tools?: ReactNode;
  /** while a version is approved: what its lock means */
  lockedText: string;
  /** while a version is approved: the data changed since (null: it did not) */
  changedText?: string | null;
  /** while a version is approved: a change worth knowing that leaves its data as it is (null: none) */
  noteText?: string | null;
  /** before the approval: what it records */
  pendingText: string;
  /** what blocks the approval (null: nothing does) */
  blockers: ReactNode | null;
  /** under the blockers: a way to clear some of them */
  clearing?: ReactNode;
  approveLabel: string;
  onApprove: () => void;
  /** the reopening with its reason; true when it was done (the reason is then cleared) */
  onReopen: (note: string) => Promise<boolean>;
  /** after the approval's part: its warnings */
  children?: ReactNode;
  error: string | null;
  notice: string | null;
  /** D0-d: the approval's state of the case's step (out of date, returned) */
  state?: ApprovalState | null;
  /** D0-d: a person returns the result with a reason instead of approving it; true when it was done */
  onReturn?: (reason: string) => Promise<boolean>;
}) {
  useLocale();
  const [note, setNote] = useState("");
  const active = p.approval.active;
  const blocked = p.blockers !== null;
  return (
    <section className="card" aria-label={t("Approval")}>
      <div className="card-head">
        <h2>{t("Approval")}</h2>
        {p.tools ? <span className="button-row">{p.tools}</span> : null}
      </div>
      {active ? (
        <>
          <p className="notice ok-box">
            {t("Approved: version {{n}}, by {{who}}, {{when}}.", { n: active.version, who: active.approved_by, when: when(active.approved_at) })}
          </p>
          <p className="muted small">{p.lockedText}</p>
          {p.changedText ? <p className="notice warn small" role="status">{p.changedText}</p> : null}
          {p.noteText ? <p className="notice small" role="status">{p.noteText}</p> : null}
          {p.archived ? null : (
            <div className="approval-reopen">
              <label className="block">{t("Reason for reopening")}
                <input type="text" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
              </label>
              <ConfirmButton className="secondary" disabled={p.busy || !note.trim()}
                onConfirm={() => void p.onReopen(note.trim()).then((done) => { if (done) setNote(""); })}>
                {t("Reopen")}
              </ConfirmButton>
            </div>
          )}
        </>
      ) : (
        <>
          <p className="muted small">{p.pendingText}</p>
          <ApprovalStateNotes state={p.state} />
          {blocked ? (
            <>
              <h3>{t("What blocks the approval")}</h3>
              {p.blockers}
              {p.clearing}
            </>
          ) : <p className="small ok">{t("Nothing blocks the approval.")}</p>}
          {p.archived ? null : (
            <ConfirmButton className={blocked ? "secondary" : "primary"} disabled={p.busy || blocked} onConfirm={p.onApprove}>
              {p.approveLabel}
            </ConfirmButton>
          )}
        </>
      )}
      {!active && !p.archived && p.onReturn ? <ReturnControl busy={p.busy} onReturn={p.onReturn} /> : null}
      {p.children}
      {p.error ? <p className="notice error" role="alert">{p.error}</p> : null}
      {p.notice ? <p className="small ok" role="status">{p.notice}</p> : null}
    </section>
  );
}

/** D0-d: an approval out of date or returned, as the step's state says (nothing while it is missing or approved). */
export function ApprovalStateNotes({ state }: { state?: ApprovalState | null }) {
  useLocale();
  if (state?.state === "outdated" && state.outdated) {
    return <p className="notice warn small" role="status">{t("Out of date: {{why}}. Check it and approve it again.", { why: outdatedWhy(state.outdated) })}</p>;
  }
  if (state?.state === "returned" && state.returned) {
    const r = state.returned;
    return <p className="notice todo small" role="status">{t("Returned by {{who}}, {{when}}: {{reason}}", { who: r.rejected_by, when: when(r.rejected_at), reason: r.reason })}</p>;
  }
  return null;
}

/** D0-d: returning the result with a required reason (a secondary button that asks once more). */
export function ReturnControl({ busy, onReturn }: { busy: boolean; onReturn: (reason: string) => Promise<boolean> }) {
  useLocale();
  const [reason, setReason] = useState("");
  return (
    <div className="approval-reopen">
      <label className="block">{t("Reason for returning it")}
        <input type="text" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} />
      </label>
      <ConfirmButton className="secondary" disabled={busy || !reason.trim()}
        onConfirm={() => void onReturn(reason.trim()).then((done) => { if (done) setReason(""); })}>
        {t("Return it")}
      </ConfirmButton>
    </div>
  );
}

/** 218 (P3l): the reason the workflow's chain gives when it reopens a version (the service's `REAPPROVE_NOTE`) is the
 *  interface's own text; a person's reason is shown as they wrote it. */
const CHAIN_REOPEN_NOTE = "a step it builds on has a new result: check it and approve it again";
/** D0-d: how the service's own reopening of an approval out of date begins (`package_release.OUTDATED`) */
const OUTDATED = "out of date: ";
const OUTDATED_WHY = "an earlier step it builds on changed: ";

function outdatedWhy(why: string): string {
  return why.startsWith(OUTDATED_WHY) ? t("an earlier step it builds on changed: {{steps}}", { steps: why.slice(OUTDATED_WHY.length) }) : why;
}

function reopenNote(note: string | null | undefined): string {
  if (note === CHAIN_REOPEN_NOTE) return t(CHAIN_REOPEN_NOTE);
  if (note?.startsWith(OUTDATED)) return t("Out of date: {{why}}", { why: outdatedWhy(note.slice(OUTDATED.length)) });
  return note ?? "";
}

/** The reopened versions, each with what the pack lets a person do with it (a download). */
export function EarlierVersions({ versions, action }: { versions: OwnVersion[]; action?: (v: OwnVersion) => ReactNode }) {
  useLocale();
  const earlier = versions.filter((v) => v.reopened_at);
  if (!earlier.length) return null;
  return (
    <section className="card" aria-label={t("Earlier versions")}>
      <h2>{t("Earlier versions")}</h2>
      <ul className="plain">
        {earlier.map((v) => (
          <li key={v.version} className="small">
            {t("Version {{n}}: approved by {{who}}, {{when}}; reopened by {{by}}, {{at}}: {{note}}",
              { n: v.version, who: v.approved_by, when: when(v.approved_at), by: v.reopened_by ?? "", at: when(v.reopened_at), note: reopenNote(v.reopen_note) })}
            {action ? <>{" "}{action(v)}</> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
