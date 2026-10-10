// 132 (backlog F-reconciliation E2): a new reconciliation package. Its input is not files but a scope: own accounts
// or cards (those the store has statements of) and a period; it pairs the statement lines with the invoices other
// packages processed (DECISIONS 131).
import { useState } from "react";
import { api, ApiError, type ReconcileAccount } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { STATEMENT_TYPE } from "./labels";
import "./reconcile.css";

/** The accounts and cards to choose from, with what the store has of them. */
export function AccountChecklist({ accounts, chosen, onChange }: {
  accounts: ReconcileAccount[]; chosen: string[]; onChange: (keys: string[]) => void;
}) {
  useLocale();
  if (!accounts.length) {
    return <p className="notice">{t("The store has no processed bank or card statement yet. Process the statements in a work package first.")}</p>;
  }
  const toggle = (key: string, on: boolean) => onChange(on ? [...chosen, key] : chosen.filter((k) => k !== key));
  return (
    <fieldset className="rc-accounts">
      <legend className="small muted">{t("Own accounts and cards")}</legend>
      {accounts.map((a) => (
        <label key={a.key}>
          <input type="checkbox" checked={chosen.includes(a.key)} onChange={(e) => toggle(a.key, e.target.checked)} />
          <span>
            <span className="mono">{a.account ?? a.key}</span>{" "}
            <span className="muted small">
              {[a.statement_types.map((s) => STATEMENT_TYPE[s] ?? s).join(", "), a.currencies.join(", ")].filter(Boolean).join(" · ")}
              {" · "}{t("{{n}} statements, {{first}} – {{last}}", { n: a.statements, first: a.first ?? "?", last: a.last ?? "?" })}
            </span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** The first and last day of the previous month, as the default period. */
function lastMonth(today = new Date()): [string, string] {
  const first = new Date(Date.UTC(today.getFullYear(), today.getMonth() - 1, 1));
  const last = new Date(Date.UTC(today.getFullYear(), today.getMonth(), 0));
  return [first.toISOString().slice(0, 10), last.toISOString().slice(0, 10)];
}

export function ReconcileCreate({ onDone }: { onDone: (id: string) => void }) {
  useLocale();
  const accounts = useLoad("reconcile-accounts", api.reconcileAccounts);
  const [chosen, setChosen] = useState<string[]>([]);
  const [[start, end], setPeriod] = useState<[string, string]>(lastMonth);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const valid = chosen.length > 0 && Boolean(start) && Boolean(end) && start <= end;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const view = await api.createReconcilePackage({
        name: name.trim() || t("Reconciliation {{from}} – {{to}}", { from: start, to: end }), accounts: chosen, period_start: start, period_end: end,
      });
      onDone(view.workpackage.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="create rc-stack" aria-label={t("New reconciliation package")} onSubmit={(e) => { e.preventDefault(); if (valid) void submit(); }}>
      <p className="muted small">
        {t("A reconciliation package pairs the lines of your bank and card statements with the invoices already processed in other work packages. It processes no file and calls no AI service.")}
      </p>
      {accounts.error ? <p className="notice error" role="alert">{accounts.error.message}</p> : null}
      {accounts.data ? <AccountChecklist accounts={accounts.data.accounts} chosen={chosen} onChange={setChosen} /> : <p className="muted">{t("Loading…")}</p>}
      <div className="rc-period">
        <label className="block">{t("Period from")}
          <input type="date" value={start} onChange={(e) => setPeriod([e.target.value, end])} required />
        </label>
        <label className="block">{t("to")}
          <input type="date" value={end} onChange={(e) => setPeriod([start, e.target.value])} required />
        </label>
      </div>
      <label className="block">{t("Name")} <span className="muted">{t("(optional: the period)")}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
      </label>
      {start && end && start > end ? <p className="small warn-text">{t("The period ends before it starts.")}</p> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      <button type="submit" className="primary" disabled={busy || !valid}>{busy ? t("Creating…") : t("Create")}</button>
    </form>
  );
}
