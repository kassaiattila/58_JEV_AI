// 140 (backlog F-package-kinds K3; DECISIONS 137, 139, 140): a new statement package: one own party's bank statements
// for a period, from a folder or from files. Before anything is written, the local service surveys the files: every
// statement with its account (the last four characters only), month, checks and source, whether the store has it
// already, what it would replace and whose account it is; and the PDFs no export uses, which a run processes with type
// recognition and AI extraction. A person ticks what goes in; the party's months show beside it. It replaces the
// earlier "Bank statement from a table" (136, 137): an export of one file or a folder of exports is surveyed here too.
import { useState } from "react";
import { api, ApiError, type OwnParty, type StatementPackageSurvey, type StatementRef, type StatementSurveyRow } from "../api";
import { BrowseButton } from "../components/BrowseButton";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { tmap } from "../labels";
import { PartyChoice } from "./reconcile/ReconcileCreate";
import { MonthGrid } from "./settings/MonthStatus";

/** The first day of the year of the last closed month and that month's last day, as the default period. */
export function defaultStatementPeriod(today = new Date()): [string, string] {
  const last = new Date(Date.UTC(today.getFullYear(), today.getMonth(), 0));
  return [`${last.getUTCFullYear()}-01-01`, last.toISOString().slice(0, 10)];
}

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
              <input type="checkbox" checked={chosen.has(r.id)} onChange={(e) => onToggle(r.id, e.target.checked)}
                aria-label={t("Choose {{title}} ({{currency}}), {{period}}", { title: r.title, currency: r.currency ?? "?", period: period(r) })} />
            </td>
            <td><strong>{r.institution}</strong> <span className="mono">{r.account ?? r.title}</span> {r.currency}</td>
            <td className="mono">{period(r)}{r.in_period ? null : <div className="small">{t("outside the period")}</div>}</td>
            <td>
              <span title={r.file}>{r.file}</span>
              {r.companion ? <div className="small muted">{t("with its PDF statement")}</div> : null}
              <div className="small muted">{t("{{n}} lines", { n: r.lines })}</div>
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

export function StatementPackageCreate({ onDone }: { onDone: (wpId: string) => void }) {
  useLocale();
  const parties = useLoad("parties", api.parties);
  const [party, setParty] = useState<OwnParty | null>(null);
  const [[start, end], setPeriod] = useState<[string, string]>(defaultStatementPeriod);
  const [source, setSource] = useState<"folder" | "files">("folder");
  const [folder, setFolder] = useState("");
  const [files, setFiles] = useState("");
  const [survey, setSurvey] = useState<StatementPackageSurvey | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lines = files.split(/\r?\n/).map((s) => s.trim().replace(/^"|"$/g, "")).filter(Boolean);
  const paths = source === "folder" ? (folder.trim() ? [folder.trim()] : []) : lines;
  const periodOk = Boolean(start) && Boolean(end) && start <= end;
  const canSurvey = party !== null && periodOk && paths.length > 0;

  // any change to what is surveyed drops the survey: the ticks belong to the files as they were read
  function reset<T>(set: (v: T) => void) {
    return (v: T) => { set(v); setSurvey(null); setChosen(new Set()); };
  }

  async function run() {
    if (!party) return;
    setBusy(true);
    setError(null);
    try {
      const s = await api.statementPackageSurvey({ paths, party_id: party.id, period_start: start, period_end: end });
      setSurvey(s);
      setChosen(new Set([...s.statements.filter((r) => r.chosen).map((r) => r.id), ...s.pdfs.filter((p) => p.chosen).map((p) => p.path)]));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!survey || !party) return;
    setBusy(true);
    setError(null);
    try {
      const view = await api.createStatementPackage({
        paths, party_id: party.id, period_start: start, period_end: end,
        name: name.trim() || t("{{party}} statements {{from}} – {{to}}", { party: party.name, from: start, to: end }),
        statements: survey.statements.filter((r) => chosen.has(r.id)).map((r) => r.id),
        pdfs: survey.pdfs.filter((p) => chosen.has(p.path)).map((p) => p.path),
      });
      onDone(view.workpackage.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const toggle = (id: string, on: boolean) => setChosen((prev) => {
    const next = new Set(prev);
    if (on) next.add(id); else next.delete(id);
    return next;
  });
  const nStatements = survey ? survey.statements.filter((r) => chosen.has(r.id)).length : 0;
  const nPdfs = survey ? survey.pdfs.filter((p) => chosen.has(p.path)).length : 0;

  return (
    <form className="create rc-stack" aria-label={t("New statement package")}
      onSubmit={(e) => { e.preventDefault(); if (survey && nStatements + nPdfs) void submit(); }}>
      <p className="muted small">
        {t("A statement package holds one party's bank statements for a period. A bank's export (Excel, CSV or the Erste XML with its PDF statements) is read by code, one statement per account and month; a PDF statement is recognised and its data extracted by AI in the run. Nothing is stored before you create the package.")}
      </p>
      {parties.error ? <p className="notice error" role="alert">{parties.error.message}</p> : null}
      {parties.data ? <PartyChoice overview={parties.data} value={party?.id ?? null} onPick={reset(setParty)} anyParty /> : <p className="muted">{t("Loading…")}</p>}
      <div className="rc-period">
        <label className="block">{t("Period from")}
          <input type="date" value={start} onChange={(e) => reset(setPeriod)([e.target.value, end])} required />
        </label>
        <label className="block">{t("to")}
          <input type="date" value={end} onChange={(e) => reset(setPeriod)([start, e.target.value])} required />
        </label>
      </div>
      {!periodOk && start && end ? <p className="small warn-text">{t("The period ends before it starts.")}</p> : null}
      <fieldset className="segmented">
        <legend className="sr-only">{t("Source")}</legend>
        <label><input type="radio" name="sp-src" checked={source === "folder"} onChange={() => reset(setSource)("folder")} /> {t("A folder")}</label>
        <label><input type="radio" name="sp-src" checked={source === "files"} onChange={() => reset(setSource)("files")} /> {t("Given files")}</label>
      </fieldset>
      {source === "folder" ? (
        <div className="path-row">
          <label className="block grow">{t("The statements' folder")}
            <input value={folder} onChange={(e) => reset(setFolder)(e.target.value)} />
          </label>
          <BrowseButton kind="folder" initial={folder} onPick={([p]) => reset(setFolder)(p)} />
        </div>
      ) : (
        <div className="path-row">
          <label className="block grow">{t("The files' full paths, one per line")}
            <textarea value={files} onChange={(e) => reset(setFiles)(e.target.value)} rows={4} />
          </label>
          <BrowseButton kind="files" initial={lines[lines.length - 1]} onPick={(picked) => reset(setFiles)([...lines, ...picked].join("\n"))} />
        </div>
      )}
      <button type="button" className="secondary" disabled={busy || !canSurvey} onClick={() => void run()}>
        {busy && !survey ? t("Reading…") : t("Survey the files")}
      </button>
      {survey ? (
        <section className="rc-stack" aria-label={t("Survey")}>
          {survey.statements.length ? (
            <>
              <p className="small">
                <button type="button" className="secondary small-btn" onClick={() => setChosen(new Set([...chosen, ...survey.statements.map((r) => r.id)]))}>{t("Select all")}</button>{" "}
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
                  <input type="checkbox" checked={chosen.has(p.path)} onChange={(e) => toggle(p.path, e.target.checked)}
                    aria-label={t("Choose {{file}}", { file: p.file })} />{" "}
                  <span className="mono">{p.file}</span>
                  {p.statement ? <span className="muted"> · {t("already in the store: {{statement}}", { statement: refText(p.statement) })}</span>
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
          <details>
            <summary className="small">{t("{{party}}'s months now", { party: survey.party.name })}</summary>
            <PartyMonths partyId={survey.party.id} start={start} end={end} />
          </details>
          <label className="block">{t("Name")} <span className="muted">{t("(optional: the party and the period)")}</span>
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
          </label>
        </section>
      ) : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {survey ? (
        <button type="submit" className="primary" disabled={busy || !(nStatements + nPdfs)}>
          {busy ? t("Creating…") : t("Create with {{n}} statement(s) and {{m}} PDF(s)", { n: nStatements, m: nPdfs })}
        </button>
      ) : null}
    </form>
  );
}
