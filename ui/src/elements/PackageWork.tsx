// 231 (plan stage C, C3b3; the owner's decision of 2026-10-25: the cases are the main list): the document processing
// step's special element (`jav/app/document_processing.py` process_documents@1). The case made its processing package
// from its source; the element shows the package (its documents and runs), starts its live run with the run's cost
// cap on the button (DESIGN §9), and leads to the package's own processing, review and result, which open from here
// (the work package list leaves such a package out).
import type { PackageWorkView } from "../api";
import { t, useLocale } from "../i18n";
import { batchOfCase, wpHash } from "../route";
import { RUN_STATUS, usdBudget } from "../labels";
import { ActionButtons } from "./ActionsElement";
import { PackageIntake } from "./ProcessStart";
import type { ElementProps } from "./registry";

const capOf = (usd: Record<string, string> | undefined) => Object.values(usd ?? {}).reduce((s, v) => s + (Number(v) || 0), 0);

export function PackageWork(p: ElementProps) {
  const { caseId, element, page } = p;
  useLocale();
  const data = element.data as PackageWorkView | null;
  const stepId = element.step ?? "";
  const step = page.steps[stepId];
  if (!data || !step) return null;
  const pkg = data.package;
  if (!pkg) {
    return (
      <section className="card wide rc-stack" aria-label={t("The case's documents")}>
        <h3>{t("The case's documents")}</h3>
        <p className="muted small">{step.state === "done" ? t("The source held no document: the case is done without a package.") : t("The package is being made…")}</p>
      </section>
    );
  }
  const live = (data.runs ?? []).filter((r) => r.mode === "apply");
  batchOfCase(pkg.id, caseId);  // 261 (B1c): its pages open under the case's address
  return (
    <>
    <section className="card wide rc-stack" aria-label={t("The case's documents")}>
      <div className="card-head">
        <h3 title={pkg.name}>{t("The case's documents")}</h3>
        {/* 261 (B1e): the shared actions, the live run's start with its cost cap from the service */}
        {data.can_start ? <div><ActionButtons p={p} only={["start_run"]} primary="start_run" /></div> : null}
      </div>
      <p className="small">{t("{{n}} documents", { n: pkg.items })}</p>
      {/* 261: the cap a person approved for its live run, and what the gate decided */}
      {data.budget?.decision === "start" ? (
        <p className="small muted">{t("Started by itself within the cap {{name}} approved ({{cap}}).", { name: data.budget.approved_by, cap: usdBudget(capOf(data.budget.usd)) })}</p>
      ) : null}
      {data.budget?.decision === "needs_budget" ? (
        <p className="notice small" role="status">{t("Over the cap {{name}} approved: the estimate is {{estimate}}, the cap {{cap}}. Start the run yourself if it is right.",
          { name: data.budget.approved_by, estimate: usdBudget(capOf(data.estimate)), cap: usdBudget(capOf(data.budget.usd)) })}</p>
      ) : null}
      {!data.can_start && !live.length && data.blockers?.length ? (
        <p className="notice small" role="status">{data.blockers.map((b) => t(b)).join(" ")}</p>
      ) : null}
      {live.length ? (
        <ul className="plain small">
          {live.map((r) => (
            <li key={r.run_id}>
              <a href={`#/runs/${encodeURIComponent(r.run_id)}`}>{r.run_id}</a>{" "}
              <span className="muted">{r.approval ? t("approved") : RUN_STATUS[r.status] ?? t(r.status)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <nav className="button-row" aria-label={t("The package's pages")}>
        <a className="button secondary" href={wpHash(pkg.id, "process")}>{t("Processing")}</a>
        <a className="button secondary" href={wpHash(pkg.id, "review")}>{t("Review")}</a>
        <a className="button secondary" href={wpHash(pkg.id, "result")}>{t("Result")}</a>
      </nav>
    </section>
    {/* 231 (C3d; the owner's decision of 2026-10-26): the processes that read the package (an email package: the email
        routing), as on the package's own page, each a card of its own beside the package's */}
    {data.offers?.length ? <PackageIntake offers={data.offers} /> : null}
    </>
  );
}
