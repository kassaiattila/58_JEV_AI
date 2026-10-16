// 140 (backlog F-package-kinds K3): a statement package's page shows its party and period, each item's statement
// (valid, replaced by a better one, booking the same days as another one a person has to choose between, or no statement
// from it yet) and the party's months in the period, so what the package changes shows before and after its run.
import type { StatementPackageView } from "../api";
import { t, useLocale } from "../i18n";
import { tmap } from "../labels";
import { PartyMonths, RANK } from "./StatementPackageCreate";

const STATE: Record<string, string> = tmap({
  valid: "valid", replaced: "replaced by a better statement",
  conflict: "books the same days as another statement: choose the valid one on the review page",
  pending: "no statement from it yet",
});
const TONE: Record<string, string> = { valid: "ok", replaced: "muted", conflict: "warn-text", pending: "muted" };

export function StatementPackagePanel({ view }: { view: StatementPackageView }) {
  useLocale();
  const { scope, statements } = view;
  const count = (state: string) => statements.filter((s) => s.state === state).length;
  return (
    <section className="card rc-stack" aria-label={t("Statements of the package")}>
      <h3>{t("{{party}}'s statements, {{from}} – {{to}}", { party: scope.party.name, from: scope.period_start, to: scope.period_end })}</h3>
      <p className="small">
        {t("{{valid}} valid, {{replaced}} replaced, {{conflict}} to choose, {{pending}} without a statement yet", {
          valid: count("valid"), replaced: count("replaced"), conflict: count("conflict"), pending: count("pending") })}
      </p>
      <table className="table compact" aria-label={t("Statements of the package")}>
        <thead>
          <tr><th>{t("File")}</th><th>{t("Account")}</th><th>{t("Period")}</th><th>{t("Checks")}</th><th>{t("State")}</th></tr>
        </thead>
        <tbody>
          {statements.map((s) => (
            <tr key={s.item_id}>
              <td><span className="mono">{s.file}</span></td>
              <td>{s.account ? <><span className="mono">{s.account}</span> {s.currency}</> : "–"}</td>
              <td className="tnum">{s.period_start ? `${s.period_start} – ${s.period_end ?? "?"}` : "–"}</td>
              <td>{s.rank ? RANK[s.rank] ?? s.rank : "–"}</td>
              <td className={TONE[s.state]}>{STATE[s.state] ?? s.state}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <details open>
        <summary className="small">{t("{{party}}'s months", { party: scope.party.name })}</summary>
        <PartyMonths partyId={scope.party.id} start={scope.period_start} end={scope.period_end} />
      </details>
    </section>
  );
}
