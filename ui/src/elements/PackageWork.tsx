// 231 (plan stage C, C3b3; the owner's decision of 2026-10-25: the cases are the main list): the document processing
// step's special element (`jav/app/document_processing.py` process_documents@1). The case made its processing package
// from its source; the element shows the package (its documents and runs), starts its live run with the run's cost
// cap on the button (DESIGN §9), and leads to the package's own processing, review and result, which open from here
// (the work package list leaves such a package out).
import type { PackageWorkView } from "../api";
import { api } from "../api";
import { useAction } from "../hooks";
import { t, useLocale } from "../i18n";
import { usdBudget } from "../labels";
import { PackageIntake } from "./ProcessStart";
import type { ElementProps } from "./registry";

const capOf = (usd: Record<string, string> | undefined) => Object.values(usd ?? {}).reduce((s, v) => s + (Number(v) || 0), 0);

export function PackageWork({ caseId, element, page, onChanged }: ElementProps) {
  useLocale();
  const { busy, error, run } = useAction();
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
  const cap = capOf(data.estimate);
  const live = (data.runs ?? []).filter((r) => r.mode === "apply");
  const start = () => run(() => api.caseStepAction(caseId, stepId, "start_run"), { then: onChanged });
  const base = `#/workpackages/${encodeURIComponent(pkg.id)}`;
  return (
    <section className="card wide rc-stack" aria-label={t("The case's documents")}>
      <div className="card-head">
        <h3 title={pkg.name}>{t("The case's documents")}</h3>
        {data.can_start ? (
          <button type="button" className="primary" disabled={busy} onClick={() => void start()}
            title={t("Starts the package's live run, which can spend up to {{usd}}", { usd: usdBudget(cap) })}>
            {t("Start the live run")}<span className="spend" aria-hidden="true">≤ {usdBudget(cap)}</span>
          </button>
        ) : null}
      </div>
      <p className="small">{t("{{n}} documents", { n: pkg.items })}</p>
      {!data.can_start && !live.length && data.blockers?.length ? (
        <p className="notice small" role="status">{data.blockers.map((b) => t(b)).join(" ")}</p>
      ) : null}
      {live.length ? (
        <ul className="plain small">
          {live.map((r) => (
            <li key={r.run_id}>
              <a href={`#/runs/${encodeURIComponent(r.run_id)}`}>{r.run_id}</a>{" "}
              <span className="muted">{r.approval ? t("approved") : t(r.status)}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <nav className="button-row" aria-label={t("The package's pages")}>
        <a className="button secondary" href={`${base}/process`}>{t("Processing")}</a>
        <a className="button secondary" href={`${base}/review`}>{t("Review")}</a>
        <a className="button secondary" href={`${base}/result`}>{t("Result")}</a>
      </nav>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {/* 231 (C3d; the owner's decision of 2026-10-26): the processes that read the package (an email package: the
          email routing), as on the package's own page */}
      {data.offers?.length ? <PackageIntake offers={data.offers} /> : null}
    </section>
  );
}
