// 136 (backlog F-revolut-csv, E4): a new work package from a bank's statement exported as a table (a workbook or a CSV
// file, e.g. a Revolut statement). The service lists the export's accounts with their line counts and checks, without
// their lines or balances; only the accounts a person ticks become items, one statement each, and the rest of the file
// is never stored (DECISIONS 132, 136). The run reads them by code and calls no AI service.
// 137 (DECISIONS 137): a folder of exports is read as a whole, e.g. the Erste XML files, one statement per month,
// each completed from the month's PDF statement; a month without one is marked, as its balances cannot be checked.
import { useState } from "react";
import { api, ApiError, type StatementTableSurvey } from "../api";
import { BrowseButton } from "../components/BrowseButton";
import { t, useLocale } from "../i18n";

export function StatementTableCreate({ onDone }: { onDone: (wpId: string) => void }) {
  useLocale();
  const [path, setPath] = useState("");
  const [survey, setSurvey] = useState<StatementTableSurvey | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function choosePath(next: string) {
    setPath(next);
    setSurvey(null);
    setChosen([]);
  }

  async function list() {
    setBusy(true);
    setError(null);
    try {
      setSurvey(await api.statementTableSurvey(path.trim()));
      setChosen([]);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!survey) return;
    setBusy(true);
    setError(null);
    try {
      const first = survey.accounts.find((a) => chosen.includes(a.key));
      const fallback = t("{{institution}} statements {{from}} – {{to}}", {
        institution: survey.institution, from: first?.period_start ?? "?", to: first?.period_end ?? "?" });
      const view = await api.createFromStatementTable(path.trim(), chosen, name.trim() || fallback);
      onDone(view.workpackage.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const toggle = (key: string, on: boolean) => setChosen(on ? [...chosen, key] : chosen.filter((k) => k !== key));

  return (
    <form className="create" aria-label={t("Bank statement from a table")} onSubmit={(e) => { e.preventDefault(); if (survey && chosen.length) void submit(); }}>
      <p className="muted small">
        {t("A bank's statement exported as a table (an Excel or CSV file) is read by code, without any AI service. Only the accounts you tick are kept, one statement each; the rest of the file is not stored.")}
      </p>
      <p className="muted small">
        {t("A folder of exports is read as a whole, for example the Erste XML files: one statement per month, completed from the month's PDF statement next to them or in a pdf subfolder.")}
      </p>
      <div className="path-row">
        <label className="block grow">{t("The exported file's or folder's full path")}
          <input value={path} onChange={(e) => choosePath(e.target.value)} required />
        </label>
        <BrowseButton kind="files" initial={path} onPick={([p]) => choosePath(p)} />
        <BrowseButton kind="folder" initial={path} onPick={([p]) => choosePath(p)} />
      </div>
      <button type="button" className="secondary" disabled={busy || !path.trim()} onClick={() => void list()}>
        {busy && !survey ? t("Reading…") : t("List the accounts")}
      </button>
      {survey ? (
        <fieldset className="plain">
          <legend>{t("Accounts in the file ({{institution}})", { institution: survey.institution })}</legend>
          {survey.accounts.length > 1 ? (
            <p className="small">
              <button type="button" className="secondary small-btn" onClick={() => setChosen(survey.accounts.map((a) => a.key))}>{t("Select all")}</button>{" "}
              <button type="button" className="secondary small-btn" disabled={!chosen.length} onClick={() => setChosen([])}>{t("Clear the selection")}</button>
            </p>
          ) : null}
          {survey.skipped ? <p className="small warn-text">{t("{{n}} file(s) in the folder could not be read as an export", { n: survey.skipped })}</p> : null}
          {survey.accounts.map((a) => (
            <label key={a.key} className="check">
              <input type="checkbox" checked={chosen.includes(a.key)} onChange={(e) => toggle(a.key, e.target.checked)}
                aria-label={t("Choose {{title}} ({{currency}})", { title: a.title, currency: a.currency })} />{" "}
              <strong>{a.title} ({a.currency})</strong>{a.account ? <span className="mono"> {a.account}</span> : null}{" · "}
              {a.lines ? t("{{n}} lines, {{first}} – {{last}}", { n: a.lines, first: a.first ?? "?", last: a.last ?? "?" }) : t("no lines")}
              {" · "}
              {a.balance_checked === false ? <span className="warn-text">{t("balances not checked: no PDF statement (a to-do in the run)")}</span>
                : a.checks_ok ? <span className="ok">{t("balances check out")}</span>
                : <span className="warn-text">{t("a check failed: it becomes a to-do in the run")}</span>}
              {a.companion ? <span className="muted"> · {t("with its PDF statement")}</span> : null}
            </label>
          ))}
        </fieldset>
      ) : null}
      {survey ? (
        <label className="block">{t("Name")} <span className="muted">{t("(optional: the bank and the period)")}</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </label>
      ) : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {survey ? (
        <button type="submit" className="primary" disabled={busy || !chosen.length}>
          {busy ? t("Creating…") : t("Create with {{n}} account(s)", { n: chosen.length })}
        </button>
      ) : null}
    </form>
  );
}
