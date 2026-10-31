// 231 (stage D, D-f6): a person's decision on another step's result (decision@1): what it decides on, the choices (one
// the result does not allow is shown but cannot be taken; one that closes the case needs a reason), whether another
// person than an earlier decision's maker must decide above a limit, the decision that holds, and its state when it is
// missing, out of date or returned. A decision carries the result versions the page showed, so one made on an older page
// is refused; a person may return it with a reason instead.
import { useState } from "react";
import { api, type DecisionData } from "../api";
import { ApprovalStateNotes, ReturnControl } from "../components/ApprovalPanel";
import { FormActions } from "../components/FormActions";
import { errorText, useActor } from "../hooks";
import { t, useLocale } from "../i18n";
import { numText, when } from "../labels";
import { decisionStatus, VERDICT } from "./caseStatus";
import type { ElementProps } from "./registry";

const loading = <p className="muted">{t("Loading…")}</p>;
const amount = (m: { amount: string; currency: string }) => `${numText(m.amount, 2)} ${m.currency}`;

/** What is decided on, in one line: a verdict, or a total (else nothing). */
function Subject({ result }: { result: Record<string, unknown> | null }) {
  if (!result) return null;
  const verdict = typeof result.verdict === "string" ? result.verdict : null;
  const total = result.total as { amount: string; currency: string } | null | undefined;
  if (verdict) return <strong>{VERDICT[verdict] ?? verdict}</strong>;
  if (total?.amount) return <strong className="tnum">{amount(total)}</strong>;
  return null;
}

export function DecisionView(p: ElementProps) {
  useLocale();
  const actor = useActor();
  const d = p.element.data as DecisionData | null;
  const [choice, setChoice] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!d) return loading;
  const step = p.element.step ?? "";
  const title = p.page.steps[step]?.title;
  const about = p.page.steps[d.about];
  const state = decisionStatus(d);
  const picked = d.choices.find((c) => c.code === choice);
  const second = d.second_person;
  const mine = !!second?.needed && !!second.earlier_by && second.earlier_by === actor;
  const ready = !!picked && picked.allowed && (!picked.closes || !!note.trim()) && !mine;
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      p.onChanged();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const decide = () => run(() => api.caseStepAction(p.caseId, step, "decide", undefined,
    { choice, note: note.trim() || null, expected_basis: d.basis }));
  return (
    <section className="card" aria-label={title ? t(title) : t("Decision")}>
      <div className="card-head">
        <h2>{title ? t(title) : t("Decision")}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      <dl className="kv">
        <dt>{t("Decides on")}</dt>
        <dd>{about?.title ? t(about.title) : d.about}{d.result ? <> · <Subject result={d.result} /></> : <span className="muted"> · {t("not ready yet")}</span>}</dd>
      </dl>
      {second ? (
        second.needed ? (
          <p className="notice todo small">{t("Above the limit ({{limit}}) another person decides, not {{who}} (who made the “{{step}}”).", {
            limit: amount(second.above), step: p.page.steps[second.other_than]?.title ? t(p.page.steps[second.other_than].title!) : second.other_than,
            who: second.earlier_by ?? "–" })}</p>
        ) : <p className="muted small">{t("Below the limit ({{limit}}): anyone may decide.", { limit: amount(second.above) })}</p>
      ) : null}
      {d.problem ? <p className="notice warn small">{d.problem}</p> : null}
      {d.decided ? (
        <p className="notice ok-box">{t("Decided: {{choice}}, by {{who}}, {{when}}.", { choice: t(d.decided.title), who: d.decided.by, when: when(d.decided.at) })}
          {d.decided.note ? <span className="muted small"> — {d.decided.note}</span> : null}</p>
      ) : null}
      <ApprovalStateNotes state={d.approval} />
      {d.waits ? (
        <div className="decision-form">
          <fieldset className="choices">
            <legend className="sr-only">{t("The choices")}</legend>
            {d.choices.map((c) => (
              <label key={c.code} className={c.allowed ? "choice" : "choice muted"}>
                <input type="radio" name={`decision-${step}`} value={c.code} checked={choice === c.code} disabled={!c.allowed}
                  onChange={() => setChoice(c.code)} />
                {t(c.title)}
                {!c.allowed ? <span className="small"> · {t("the result does not allow it")}</span> : null}
                {c.closes ? <span className="small muted"> · {t("it closes the case")}</span> : null}
              </label>
            ))}
          </fieldset>
          <label className="block">{picked?.closes ? t("Reason (required)") : t("Note")}
            <input type="text" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </label>
          <FormActions busy={busy} note={mine ? <span className="todo-text">{t("Another person decides above the limit.")}</span>
            : picked?.closes && !note.trim() ? t("Give the reason.") : null}>
            <button type="button" className={ready ? "primary" : "secondary"} disabled={!ready || busy} onClick={() => void decide()}>{t("Record the decision")}</button>
          </FormActions>
        </div>
      ) : null}
      {!d.decided && d.waits ? <ReturnControl busy={busy} onReturn={(reason) => run(() => api.returnCaseStep(p.caseId, step, reason))} /> : null}
      {d.approval.versions.some((v) => v.reopened_at) ? (
        <details className="earlier">
          <summary className="muted small">{t("Earlier decisions ({{n}})", { n: d.approval.versions.filter((v) => v.reopened_at).length })}</summary>
          <table className="table compact">
            <thead><tr><th className="num">{t("Version")}</th><th>{t("Who")}</th><th>{t("When")}</th><th>{t("Reopened")}</th></tr></thead>
            <tbody>
              {d.approval.versions.filter((v) => v.reopened_at).map((v) => (
                <tr key={v.version}><td className="num">{v.version}</td><td>{v.approved_by}</td><td className="tnum">{when(v.approved_at)}</td>
                  <td className="muted small">{v.reopen_note ?? ""}</td></tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}
      {error ? <p className="notice error small" role="alert">{error}</p> : null}
    </section>
  );
}
