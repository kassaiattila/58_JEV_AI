// 231 (stage D, D-f8): a letter that goes with a printed document (letter@1). While it waits, the draft written by code
// from its frame: the address, the subject and the text, which a person may change, and the document it attaches; one
// solid button accepts it with the page's document version (an older page is refused). Accepted, the letter as it was
// accepted, who accepted it and when, and its email file with its fingerprint: the send step hands over that file.
import { useEffect, useRef, useState } from "react";
import { api, type LetterData } from "../api";
import { ApprovalStateNotes } from "../components/ApprovalPanel";
import { FormActions } from "../components/FormActions";
import { errorText } from "../hooks";
import { t, useLocale } from "../i18n";
import { when } from "../labels";
import { letterStatus } from "./caseStatus";
import type { ElementProps } from "./registry";

const loading = <p className="muted">{t("Loading…")}</p>;
const ADDRESS = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function Fingerprint({ sha }: { sha: string }) {
  return <span className="mono small" title={sha}>{sha.slice(0, 12)}</span>;
}

export function LetterView(p: ElementProps) {
  useLocale();
  const d = p.element.data as LetterData | null;
  const [to, setTo] = useState(() => d?.draft?.to ?? "");
  const [subject, setSubject] = useState(() => d?.draft?.subject ?? "");
  const [body, setBody] = useState(() => d?.draft?.body ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const draftKey = d?.draft ? `${d.document?.sha256}:${d.draft.subject}:${d.draft.body}` : null;
  const shownKey = useRef(draftKey);
  useEffect(() => {  // only a new draft (a new document) starts the form again, never what a person typed meanwhile
    if (!d?.draft || shownKey.current === draftKey) return;
    shownKey.current = draftKey;
    setTo(d.draft.to ?? "");
    setSubject(d.draft.subject);
    setBody(d.draft.body);
  }, [draftKey]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return loading;
  const step = p.element.step ?? "";
  const title = p.page.steps[step]?.title;
  const state = letterStatus(d);
  const addressOk = !to.trim() || ADDRESS.test(to.trim());
  const left = /\{\{.*?\}\}/s.exec(`${subject}\n${body}`);
  const ready = !!subject.trim() && !!body.trim() && addressOk && !left;
  const accept = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.caseStepAction(p.caseId, step, "accept", undefined,
        { to: to.trim() || null, subject: subject.trim(), body, expected_basis: d.basis });
      p.onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const a = d.accepted;
  return (
    <section className="card" aria-label={title ? t(title) : t("Letter")}>
      <div className="card-head">
        <h2>{title ? t(title) : t("Letter")}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      <ApprovalStateNotes state={d.approval} />
      {d.problem ? <p className="notice warn small">{d.problem}</p> : null}
      {a ? (
        <>
          <dl className="kv">
            <dt>{t("To")}</dt><dd className={a.to ? "" : "muted"}>{a.to ?? t("no address")}</dd>
            <dt>{t("Subject")}</dt><dd>{a.subject}</dd>
            <dt>{t("Attached")}</dt><dd>{a.document.name} · <Fingerprint sha={a.document.sha256} /></dd>
            {a.file ? (<><dt>{t("Email file")}</dt>
              <dd><a href={api.caseStepFileUrl(p.caseId, step)} download={a.file.name}>{a.file.name}</a> · <Fingerprint sha={a.file.sha256} /></dd></>) : null}
          </dl>
          <div className="mail-body">{a.body}</div>
          <p className="muted small">{t("Accepted by {{who}}, {{when}}.", { who: a.by, when: when(a.at) })}</p>
        </>
      ) : d.waits && d.draft ? (
        <div className="letter-form">
          <p className="muted small">{t("Written from the frame with the document's values. Read it, change it if needed, and accept it: the send hands over this letter with the document attached.")}</p>
          <label className="block">{t("To")}
            <input type="email" value={to} maxLength={320} onChange={(e) => setTo(e.target.value)} />
          </label>
          {!to.trim() ? <p className="todo-text small">{t("No address: the letter goes without one, into the output folder.")}</p> : null}
          {!addressOk ? <p className="todo-text small">{t("This is not an email address.")}</p> : null}
          <label className="block">{t("Subject")}
            <input type="text" value={subject} maxLength={d.limits.subject_chars} onChange={(e) => setSubject(e.target.value)} />
          </label>
          <label className="block">{t("The letter's text")}
            <textarea className="letter-text" rows={12} value={body} maxLength={d.limits.body_chars} onChange={(e) => setBody(e.target.value)} />
          </label>
          {left ? <p className="todo-text small">{t("A marker is left in the letter: {{marker}}", { marker: left[0] })}</p> : null}
          {d.document ? (
            <p className="small">{t("Attached")}: {d.document.name} · <Fingerprint sha={d.document.sha256} /></p>
          ) : null}
          <FormActions busy={busy}>
            <button type="button" className={ready ? "primary" : "secondary"} disabled={!ready || busy} onClick={() => void accept()}>
              {t("Accept the letter")}
            </button>
          </FormActions>
        </div>
      ) : (
        <p className="muted">{t("Written once the document is printed.")}</p>
      )}
      {error ? <p className="notice error small" role="alert">{error}</p> : null}
    </section>
  );
}
