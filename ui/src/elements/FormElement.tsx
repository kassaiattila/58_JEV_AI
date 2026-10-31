// 261 (plan B, B1g; the owner's decision of 2026-10-29: the three shared elements now, each with a first user): the
// shared element `form`, a step's action's form as its capability describes it (`jav/app/capabilities.py`
// `form_fields`, `Action.prefill`): the fields a person gives with their first values, why it cannot be sent now, and
// the page's state, which goes back as the service gave it so a stale page is refused (409). Its first user: the facts'
// freeze in the field review.
import { useState, type ReactNode } from "react";
import type { CaseFormSpec } from "../api";
import { FormActions } from "../components/FormActions";
import { t, useLocale } from "../i18n";
import type { ElementProps } from "./registry";
import { useStepAction } from "./stepAction";

const INPUT: Record<string, string> = { date: "date", int: "number", number: "number", text: "text" };
const empty = (v: unknown) => v === undefined || v === null || v === "";

/** One action's form: its fields, its button (the solid one once it can be sent), why not yet, and `note` below. */
export function StepForm({ p, action, note, className }: { p: ElementProps; action: string; note?: ReactNode; className?: string }) {
  useLocale();
  const step = p.element.step;
  const found = ((step && p.page.steps[step]?.actions) || []).find((a) => a.name === action);
  const spec: CaseFormSpec | null = found && typeof found.form === "object" ? found.form : null;
  const [values, setValues] = useState<Record<string, unknown>>(() => ({ ...(spec?.values ?? {}) }));
  const { busy, error, run } = useStepAction(p);
  if (!found || !spec) return null;
  const missing = spec.fields.filter((f) => f.required && empty(values[f.name]));
  const ready = !spec.blocked && !missing.length;
  // the fields a person gives, over the page's state as the service gives it now
  const send = () => run(found.name, { ...spec.values, ...Object.fromEntries(spec.fields.map((f) => [f.name, values[f.name] ?? null])) });
  return (
    <div className={className ?? "step-form"}>
      {spec.fields.map((f) => {
        const id = `form-${step}-${found.name}-${f.name}`;
        return (
          <div className="field" key={f.name}>
            <label htmlFor={id}>{t(f.label)}</label>
            <input id={id} type={INPUT[f.kind] ?? "text"} value={empty(values[f.name]) ? "" : String(values[f.name])}
              onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))} />
          </div>
        );
      })}
      <FormActions busy={busy} note={spec.blocked ? <span className="todo-text">{t(spec.blocked)}</span>
        : missing.length ? t("Give: {{fields}}", { fields: missing.map((f) => t(f.label)).join(", ") }) : null}>
        <button type="button" className={ready ? "primary" : "secondary"} disabled={!ready || busy} onClick={() => void send()}>{t(found.label)}</button>
      </FormActions>
      {note}
      {error ? <p className="notice error small" role="alert">{error}</p> : null}
    </div>
  );
}

/** The element: each of the step's actions whose form is described, or the one the pack's element names (`action`). */
export function FormView(p: ElementProps) {
  useLocale();
  const step = p.element.step ? p.page.steps[p.element.step] : undefined;
  const named = typeof p.element.action === "string" ? p.element.action : null;
  const forms = (step?.actions ?? []).filter((a) => typeof a.form === "object" && (!named || a.name === named));
  if (!step || !forms.length) return null;
  return (
    <section className="card" aria-label={step.title ? t(step.title) : t("Form")}>
      <div className="card-head"><h2>{step.title ? t(step.title) : t("Form")}</h2></div>
      {forms.map((a) => <StepForm key={a.name} p={p} action={a.name} />)}
    </section>
  );
}
