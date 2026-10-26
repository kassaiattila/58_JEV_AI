// 140 (backlog F-package-kinds K3): a statement package's page shows its party and period, each item's statement
// (valid, replaced by a better one, booking the same days as another one a person has to choose between, or no statement
// from it yet) and the party's months in the period, so what the package changes shows before and after its run.
// 231 (C3b5a): the survey's parts are here too (until then in the new statement package form, which went: a statement
// package is a bank statements case's, started from the new work wizard's general form); adding statements to a
// package uses them (`AddStatements.tsx`).
import { api, type StatementRef } from "../../api";
import type { StatementPackageSurvey, StatementPackageView, StatementSurveyRow } from "./api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { tmap } from "../../labels";
import { MonthGrid } from "./MonthStatus";

export const RANK: Record<string, string> = tmap({
  code_checked: "read by code, balances check out", extracted_checked: "extracted by AI, balances check out",
  unchecked: "balances not checked",
});

function period(r: { period_start: string | null; period_end: string | null }): string {
  return `${r.period_start ?? "?"} – ${r.period_end ?? "?"}`;
}

function refText(r: StatementRef): string {
  return t("{{file}} ({{period}}, {{rank}})", { file: r.file ?? r.id.slice(0, 12), period: period(r), rank: RANK[r.rank] ?? r.rank });
}

/** What the statement does to the store: already there, replaces, replaced by, or in a conflict a person decides. */
function StoreCell({ row }: { row: StatementSurveyRow }) {
  useLocale();
  if (row.in_store) return <span className="muted">{t("already in the store")}</span>;
  if (row.replaced_by) return <span className="warn-text" title={refText(row.replaced_by)}>{t("a better statement replaces it")}</span>;
  return (
    <>
      {row.replaces.length ? <span className="ok" title={row.replaces.map(refText).join("\n")}>{t("replaces {{n}} statement(s)", { n: row.replaces.length })}</span> : null}
      {row.conflicts.length ? (
        <span className="warn-text" title={row.conflicts.map(refText).join("\n")}>
          {t("books the same days as {{n}} statement(s): a person chooses on the review page", { n: row.conflicts.length })}
        </span>
      ) : null}
      {!row.replaces.length && !row.conflicts.length ? <span>{t("new")}</span> : null}
    </>
  );
}

function OwnerCell({ row, party }: { row: StatementSurveyRow; party: string }) {
  useLocale();
  if (row.owner === "package") return <span>{party}</span>;
  if (row.owner === "none") return <span className="muted">{t("goes to {{party}}", { party })}</span>;
  return <span className="warn-text">{t("{{party}}'s: a to-do in the run", { party: row.owner_party?.name ?? "?" })}</span>;
}

function SurveyTable({ survey, chosen, onToggle }: { survey: StatementPackageSurvey; chosen: Set<string>; onToggle: (id: string, on: boolean) => void }) {
  useLocale();
  return (
    <table className="table compact sp-survey" aria-label={t("Statements in the files")}>
      <thead>
        <tr>
          <th><span className="sr-only">{t("Choose")}</span></th>
          <th>{t("Account")}</th><th>{t("Period")}</th><th>{t("Source")}</th><th>{t("Checks")}</th>
          <th>{t("In the store")}</th><th>{t("Party")}</th>
        </tr>
      </thead>
      <tbody>
        {survey.statements.map((r) => (
          <tr key={r.id} className={r.in_period ? undefined : "muted"}>
            <td>
              <input type="checkbox" checked={chosen.has(r.id)} disabled={r.in_package} onChange={(e) => onToggle(r.id, e.target.checked)}
                aria-label={t("Choose {{title}} ({{currency}}), {{period}}", { title: r.title, currency: r.currency ?? "?", period: period(r) })} />
            </td>
            <td><strong>{r.institution}</strong> <span className="mono">{r.account ?? r.title}</span> {r.currency}</td>
            <td className="tnum">{period(r)}{r.in_period ? null : <div className="small">{t("outside the period")}</div>}</td>
            <td>
              <span title={r.file}>{r.file}</span>
              {r.companion ? <div className="small muted">{t("with its PDF statement")}</div> : null}
              <div className="small muted">{t("{{n}} lines", { n: r.lines })}</div>
              {r.in_package ? <div className="small muted">{t("already in this package")}</div> : null}
            </td>
            <td>
              <span className={r.rank === "unchecked" ? "warn-text" : "ok"}>{RANK[r.rank] ?? r.rank}</span>
              {!r.balance_checked ? <div className="small muted">{t("no PDF statement: a to-do in the run")}</div>
                : !r.checks_ok ? <div className="small warn-text">{t("a check failed: it becomes a to-do in the run")}</div> : null}
            </td>
            <td><StoreCell row={r} /></td>
            <td><OwnerCell row={r} party={survey.party.name} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** 140, 160-C S2: the survey's choices — the statements (select all / clear), the PDFs no export uses and the files that
 *  could not be read; shared by a new statement package and by adding to one (what the package holds stays unticked). */
export function SurveyChoices({ survey, chosen, setChosen }: {
  survey: StatementPackageSurvey; chosen: Set<string>; setChosen: (next: Set<string>) => void;
}) {
  useLocale();
  const toggle = (id: string, on: boolean) => {
    const next = new Set(chosen);
    if (on) next.add(id); else next.delete(id);
    setChosen(next);
  };
  const open = survey.statements.filter((r) => !r.in_package).map((r) => r.id);
  return (
    <>
      {survey.statements.length ? (
        <>
          <p className="small">
            <button type="button" className="secondary small-btn" onClick={() => setChosen(new Set([...chosen, ...open]))}>{t("Select all")}</button>{" "}
            <button type="button" className="secondary small-btn" onClick={() => setChosen(new Set([...chosen].filter((id) => !survey.statements.some((r) => r.id === id))))}>{t("Clear the selection")}</button>
          </p>
          <SurveyTable survey={survey} chosen={chosen} onToggle={toggle} />
        </>
      ) : <p className="muted small">{t("The files hold no bank export a profile can read.")}</p>}
      {survey.pdfs.length ? (
        <fieldset className="plain">
          <legend>{t("PDF statements ({{n}})", { n: survey.pdfs.length })}</legend>
          <p className="small muted">{t("A PDF is recognised in the run: a bank statement's data is extracted by AI within the run's budget; any other document stops with a to-do, without extraction.")}</p>
          {survey.pdfs.map((p) => (
            <label key={p.path} className="check">
              <input type="checkbox" checked={chosen.has(p.path)} disabled={p.in_package} onChange={(e) => toggle(p.path, e.target.checked)}
                aria-label={t("Choose {{file}}", { file: p.file })} />{" "}
              <span className="mono">{p.file}</span>
              {p.in_package ? <span className="muted"> · {t("already in this package")}</span>
                : p.statement ? <span className="muted"> · {t("already in the store: {{statement}}", { statement: refText(p.statement) })}</span>
                : p.in_store ? <span className="muted"> · {t("already processed, not as a statement")}</span> : null}
            </label>
          ))}
        </fieldset>
      ) : null}
      {survey.skipped.length ? (
        <details>
          <summary className="small warn-text">{t("{{n}} file(s) could not be read as a statement", { n: survey.skipped.length })}</summary>
          <ul className="small">{survey.skipped.map((s) => <li key={`${s.file}:${s.reason}`}><span className="mono">{s.file}</span>: {s.reason}</li>)}</ul>
        </details>
      ) : null}
    </>
  );
}

/** The party's months in the period as the store has them now (the survey says what the package would change). */
export function PartyMonths({ partyId, start, end }: { partyId: string; start: string; end: string }) {
  useLocale();
  const [from, to] = [start.slice(0, 7), end.slice(0, 7)];
  const loaded = useLoad(`party-months:${partyId}:${from}:${to}`, () => api.partyMonths(partyId, from, to));
  if (loaded.error) return <p className="notice error" role="alert">{loaded.error.message}</p>;
  if (!loaded.data) return <p className="muted small">{t("Loading…")}</p>;
  return loaded.data.columns.length ? <MonthGrid data={loaded.data} />
    : <p className="muted small">{t("The party has no account or card yet: its first statements will bring them.")}</p>;
}


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
