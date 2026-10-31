// 261 (plan B, B1e; the owner's decision of 2026-10-29: the three shared elements now, each with a first user): the
// shared element `actions`, a step's actions as buttons. The service names the actions available now
// (`jav/app/case_views.py` `_actions`), each that may spend with its cost cap by provider, which its button shows
// (DESIGN §9); an action with a form is its step's own element's. Its first users: the case page's step buttons (a
// stopped step's retry, whether a message arrived, a reply) and the document step's live run start.
import { t, useLocale } from "../i18n";
import { usdBudget } from "../labels";
import type { ElementProps } from "./registry";
import { useStepAction } from "./stepAction";

const total = (cap: Record<string, string> | undefined) => Object.values(cap ?? {}).reduce((s, v) => s + (Number(v) || 0), 0);

/** The step's actions as buttons: `primary`, the one the page leads to; `only`, the names to offer (all otherwise). */
export function ActionButtons({ p, primary, only }: { p: ElementProps; primary?: string; only?: string[] }) {
  useLocale();
  const { busy, error, run } = useStepAction(p);
  const step = p.element.step;
  const actions = ((step && p.page.steps[step]?.actions) || []).filter((a) => !a.form && (!only || only.includes(a.name)));
  if (!step || !actions.length) return null;
  return (
    <>
      <div className="button-row end">
        {actions.map((a) => {
          const cap = a.cap ? usdBudget(total(a.cap)) : null;
          return (
            <button key={a.name} type="button" className={a.name === primary ? "primary" : "secondary"} disabled={busy}
              title={cap ? t("{{action}}: it can spend up to {{usd}}", { action: t(a.label), usd: cap }) : undefined}
              onClick={() => void run(a.name)}>
              {t(a.label)}{cap ? <span className="spend" aria-hidden="true">≤ {cap}</span> : null}
            </button>
          );
        })}
      </div>
      {error ? <p className="notice error small" role="alert">{error}</p> : null}
    </>
  );
}

/** The element: the step's actions, under the step's title. */
export function ActionsView(p: ElementProps) {
  useLocale();
  const step = p.element.step ? p.page.steps[p.element.step] : undefined;
  if (!step?.actions?.some((a) => !a.form)) return null;
  return (
    <section className="card" aria-label={step.title ? t(step.title) : t("Actions")}>
      <div className="card-head"><h2>{step.title ? t(step.title) : t("Actions")}</h2></div>
      <ActionButtons p={p} />
    </section>
  );
}
