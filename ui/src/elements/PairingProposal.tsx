// 231 (plan stage C, C2c; the owner's decision of 2026-10-25): the AI pairing proposal's special element
// (`jav/domains/finance/capabilities.py` pairing_proposal@1). A person asks the AI which invoice each statement line
// still to decide pays and what kind of payment it is; the button shows the run's cost cap (DESIGN §9: a trial spends
// from the same budget as a live run). The answers appear on the pairing cards below; a person still decides each pair.
import { api } from "../api";
import { useAction } from "../hooks";
import { t, useLocale } from "../i18n";
import { usdBudget } from "../labels";
import type { ElementProps } from "./registry";

/** The element's data: the step's latest run and the cap a run reserves (provider -> USD). */
export interface ProposalData {
  run: {
    round: number; state: "queued" | "running" | "done" | "failed"; lines: number | null; error: string | null;
    counts: Record<string, { asked: number; inherited: number; pays: number; failed: number }> | null;
    usage: { spent_usd?: string; providers?: Record<string, { spent_usd?: string }> } | null;
  } | null;
  engines: string[];
  cap_usd: Record<string, string>;
}

const capOf = (usd: Record<string, string>) => Object.values(usd).reduce((s, v) => s + (Number(v) || 0), 0);

export function PairingProposal({ caseId, element, page, onChanged }: ElementProps) {
  useLocale();
  const { busy, error, run } = useAction();
  const data = element.data as ProposalData | null;
  const stepId = element.step ?? "";
  const step = page.steps[stepId];
  if (!data || !step) return null;
  const cap = capOf(data.cap_usd);
  const last = data.run;
  const asked = last?.counts ? Object.values(last.counts).reduce((s, c) => s + c.asked + c.inherited, 0) : 0;
  const retry = step.actions?.some((a) => a.name === "retry");
  const skipped = step.state === "done" && step.phase === "skipped";
  const ask = () => run(() => api.startCaseStep(caseId, stepId), { then: onChanged });
  const again = () => run(() => api.caseStepAction(caseId, stepId, "retry"), { then: onChanged });
  return (
    <section className="card wide rc-stack" aria-label={t("AI pairing proposal")}>
      <div className="card-head">
        <h3>{t("AI pairing proposal")}</h3>
        {step.awaiting_start || retry ? (
          <button type="button" className="secondary" disabled={busy} onClick={() => void (retry ? again() : ask())}
            title={t("Asks JEV about the statement lines still to decide and can spend up to {{usd}}", { usd: usdBudget(cap) })}>
            {retry ? t("Ask the AI again") : t("Ask the AI for proposals")}
            <span className="spend" aria-hidden="true">≤ {usdBudget(cap)}</span>
          </button>
        ) : null}
      </div>
      <p className="muted small">{t("The AI proposes which invoice each statement line still to decide pays and what kind of payment it is. You decide every pair; asking is optional.")}</p>
      {last && (last.state === "queued" || last.state === "running") ? <p className="small" role="status">{t("The AI is answering…")}</p> : null}
      {last?.state === "done" ? (
        <p className="small ok" role="status">{t("The AI answered {{n}} line(s); its proposals are on the pairing cards.", { n: asked })}</p>
      ) : null}
      {last?.state === "failed" ? <p className="notice error small" role="alert">{t("The AI proposal failed: {{why}}", { why: last.error ?? "" })}</p> : null}
      {skipped ? <p className="muted small">{t("Not asked: the reconciliation was approved without it.")}</p> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </section>
  );
}
