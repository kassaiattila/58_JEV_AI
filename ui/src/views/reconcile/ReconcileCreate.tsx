// 132 (backlog F-reconciliation E2): a new reconciliation package. Its input is not files but a scope: own accounts
// or cards (those the store has statements of) and a period; it pairs the statement lines with the invoices other
// packages processed (DECISIONS 131). 133: the package is one own party's (DECISIONS 133): the parties stand first with
// their invoices and statements; choosing one checks its accounts and sets the period to its statements' span.
// 138 (DECISIONS 137): an account registered with the party without a statement can be chosen too, and the chosen
// accounts' months show before creating: a month without a statement warns, it does not stop the package.
import { useState } from "react";
import { api, ApiError, type OwnParty, type PartiesOverview, type ReconcileAccount } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { MonthGrid, monthWarnings } from "../settings/MonthStatus";
import { STATEMENT_TYPE } from "./labels";
import "./reconcile.css";

/** The accounts and cards to choose from, with what the store has of them. */
export function AccountChecklist({ accounts, chosen, onChange, partyId }: {
  accounts: ReconcileAccount[]; chosen: string[]; onChange: (keys: string[]) => void; partyId?: string | null;
}) {
  useLocale();
  if (!accounts.length) {
    return <p className="notice">{t("The store has no processed bank or card statement yet. Process the statements in a work package first.")}</p>;
  }
  const toggle = (key: string, on: boolean) => onChange(on ? [...chosen, key] : chosen.filter((k) => k !== key));
  // the chosen party's accounts first, then the others with their party named
  const ordered = partyId ? [...accounts].sort((a, b) => Number(a.party?.id !== partyId) - Number(b.party?.id !== partyId)) : accounts;
  return (
    <fieldset className="rc-accounts">
      <legend className="small muted">{t("Own accounts and cards")}</legend>
      {ordered.map((a) => (
        <label key={a.key}>
          <input type="checkbox" checked={chosen.includes(a.key)} onChange={(e) => toggle(a.key, e.target.checked)} />
          <span>
            <span className="mono">{a.account ?? a.key}</span>{" "}
            <span className="muted small">
              {[a.statement_types.map((s) => STATEMENT_TYPE[s] ?? s).join(", "), a.currencies.join(", ")].filter(Boolean).join(" · ")}
              {" · "}{a.statements ? t("{{n}} statements, {{first}} – {{last}}", { n: a.statements, first: a.first ?? "?", last: a.last ?? "?" })
                : t("registered, no statement yet")}
            </span>
            {a.party && partyId && a.party.id !== partyId ? <>{" "}<span className="rc-sig warn">{a.party.name}</span></> : null}
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

/** 133: the own parties to choose from, each with its invoices and its statements' span. */
export function PartyChoice({ overview, value, onPick }: { overview: PartiesOverview; value: string | null; onPick: (p: OwnParty) => void }) {
  useLocale();
  const list = overview.parties;
  return (
    <fieldset className="rc-accounts rc-parties">
      <legend className="small muted">{t("Own party")}</legend>
      {list.map((p) => {
        const noAccount = !p.accounts.length;
        return (
          <label key={p.id} className={noAccount ? "muted" : undefined}>
            <input type="radio" name="rc-party" checked={value === p.id} disabled={noAccount} onChange={() => onPick(p)} />
            <span>
              <strong>{p.name}</strong>{" "}
              <span className="muted small">
                {t("{{n}} invoices", { n: p.invoices })}{p.first ? `, ${p.first} – ${p.last}` : ""}{" · "}
                {noAccount ? t("no account or statement yet")
                  : p.statements_first ? t("{{n}} accounts or cards, statements {{first}} – {{last}}", { n: p.accounts.length, first: p.statements_first, last: p.statements_last ?? "?" })
                    : t("{{n}} accounts or cards, no statement yet", { n: p.accounts.length })}
              </span>
            </span>
          </label>
        );
      })}
      {!list.length ? (
        <p className="notice">
          {t("No own party yet: accept the suggestions first, so that a package shows only its own party's invoices.")}{" "}
          <a href="#/settings/parties">{t("Settings › Own parties")}</a>
        </p>
      ) : null}
      {list.length && overview.suggestions.length ? (
        <p className="small muted">
          {t("{{n}} suggestions wait for a decision.", { n: overview.suggestions.length })}{" "}
          <a href="#/settings/parties">{t("Settings › Own parties")}</a>
        </p>
      ) : null}
    </fieldset>
  );
}

/** 138: the chosen accounts' months in the period, with what they lack; a gap warns, it does not stop the package. */
function MonthPreview({ partyId, accounts, start, end }: { partyId: string; accounts: string[]; start: string; end: string }) {
  useLocale();
  const [from, to] = [start.slice(0, 7), end.slice(0, 7)];
  const loaded = useLoad(`party-months:${partyId}:${from}:${to}`, () => api.partyMonths(partyId, from, to));
  if (loaded.error) return <p className="notice error" role="alert">{loaded.error.message}</p>;
  if (!loaded.data) return <p className="muted small">{t("Loading…")}</p>;
  const warnings = monthWarnings(loaded.data, accounts);
  return (
    <section className="rc-months" aria-label={t("Data status of the period")}>
      {warnings.length ? (
        <div className="notice" role="status">
          <ul className="small ms-warnings">{warnings.map((w) => <li key={w}>{w}</li>)}</ul>
          <p className="small muted">{t("The package can be created; the gaps show in its result.")}</p>
        </div>
      ) : <p className="small ok">{t("Every month of the chosen accounts has an approved statement that checks out.")}</p>}
      <details>
        <summary className="small">{t("Data status by month")}</summary>
        <MonthGrid data={loaded.data} accounts={accounts} />
      </details>
    </section>
  );
}

export function ReconcileCreate({ onDone }: { onDone: (id: string) => void }) {
  useLocale();
  const accounts = useLoad("reconcile-accounts", api.reconcileAccounts);
  const parties = useLoad("parties", api.parties);
  const [party, setParty] = useState<OwnParty | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [[start, end], setPeriod] = useState<[string, string]>(lastMonth);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const needsParty = Boolean(parties.data?.parties.length);
  const valid = chosen.length > 0 && Boolean(start) && Boolean(end) && start <= end && (!needsParty || party !== null);

  function pick(p: OwnParty) {
    setParty(p);
    setChosen(p.accounts.map((a) => a.key));
    if (p.statements_first && p.statements_last) setPeriod([p.statements_first, p.statements_last]);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const view = await api.createReconcilePackage({
        name: name.trim() || (party ? t("{{party}} · {{from}} – {{to}}", { party: party.name, from: start, to: end })
          : t("Reconciliation {{from}} – {{to}}", { from: start, to: end })),
        accounts: chosen, period_start: start, period_end: end, party_id: party?.id ?? null,
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
      {parties.error ? <p className="notice error" role="alert">{parties.error.message}</p> : null}
      {parties.data ? <PartyChoice overview={parties.data} value={party?.id ?? null} onPick={pick} /> : null}
      {accounts.data ? <AccountChecklist accounts={accounts.data.accounts} chosen={chosen} onChange={setChosen} partyId={party?.id} /> : <p className="muted">{t("Loading…")}</p>}
      <div className="rc-period">
        <label className="block">{t("Period from")}
          <input type="date" value={start} onChange={(e) => setPeriod([e.target.value, end])} required />
        </label>
        <label className="block">{t("to")}
          <input type="date" value={end} onChange={(e) => setPeriod([start, e.target.value])} required />
        </label>
      </div>
      <label className="block">{t("Name")} <span className="muted">{t(party ? "(optional: the party and the period)" : "(optional: the period)")}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
      </label>
      {start && end && start > end ? <p className="small warn-text">{t("The period ends before it starts.")}</p> : null}
      {party && chosen.length > 0 && start && end && start <= end
        ? <MonthPreview partyId={party.id} accounts={chosen} start={start} end={end} /> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      <button type="submit" className="primary" disabled={busy || !valid}>{busy ? t("Creating…") : t("Create")}</button>
    </form>
  );
}
