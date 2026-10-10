// 138 (DECISIONS 137, 138): a party's data month by month, before it is reconciled. Per own account and currency: is
// there a statement for the month, do its balances check out, is its run approved, does it continue the previous
// statement's closing balance; and how many invoices the month has. The settings page shows it for a party, the new
// reconciliation package for the chosen accounts and period, where a gap warns but does not stop anything.
import { useState } from "react";
import { api, type MonthCell, type MonthColumn, type PartyMonths } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { tmap } from "../../labels";
import "./parties.css";

const STATE: Record<string, string> = tmap({
  ok: "OK", unapproved: "Awaiting approval", unverified: "Balances do not check out", partial: "Part of the month",
  missing: "No statement", none: "–",
});
const STATE_HINT: Record<string, string> = tmap({
  ok: "The statements cover the month, their balances check out and their run is approved.",
  unapproved: "The statements cover the month and check out, but their run is not approved yet.",
  unverified: "A statement of the month does not check out by its balances.",
  partial: "The statements cover only part of the month.",
  missing: "The account was open, but the store has no statement for the month.",
  none: "Not expected: the account was not open, or the month has not ended yet.",
});
const FLAG: Record<string, string> = tmap({ overlap: "two statements", break: "balance break" });
const FLAG_HINT: Record<string, string> = tmap({
  overlap: "Two statements book the same days: their lines may be counted twice.",
  break: "The opening balance does not continue the previous statement's closing balance.",
});
const KIND: Record<string, string> = tmap({ account: "Bank account", card: "Card" });
const TONE: Record<string, string> = { ok: "ok", unapproved: "warn", unverified: "bad", partial: "warn", missing: "bad", none: "none" };

/** The account in a column head: its bank, the end of its number and the currency. */
export function columnLabel(col: Pick<MonthColumn, "bank" | "label" | "currency">): string {
  const digits = col.label.replace(/\s/g, "");
  return [col.bank, digits.length > 8 ? `…${digits.slice(-4)}` : col.label, col.currency].filter(Boolean).join(" ");
}

function Cell({ cell }: { cell: MonthCell }) {
  useLocale();
  const hint = [STATE_HINT[cell.state], ...cell.flags.map((f) => FLAG_HINT[f])].join(" ");
  return (
    <td className={`ms-cell ${TONE[cell.state]}`} title={hint}>
      <span>{STATE[cell.state]}</span>
      {cell.statements > 1 ? <span className="muted small"> ({cell.statements})</span> : null}
      {cell.flags.map((f) => <span key={f} className="ms-flag">{FLAG[f]}</span>)}
    </td>
  );
}

/** The months as rows, the accounts as columns, the invoices last; `accounts` limits the columns. */
export function MonthGrid({ data, accounts }: { data: PartyMonths; accounts?: string[] }) {
  useLocale();
  const columns = accounts ? data.columns.filter((c) => accounts.includes(c.key)) : data.columns;
  const invoices = Object.fromEntries(data.invoices.map((i) => [i.month, i]));
  return (
    <div className="ms-wrap">
      <table className="table compact ms-grid" aria-label={t("Data status by month")}>
        <thead>
          <tr>
            <th>{t("Month")}</th>
            {columns.map((c) => (
              <th key={`${c.key}|${c.currency}`} title={`${KIND[c.kind]} · ${c.label}`}>{columnLabel(c)}</th>
            ))}
            <th>{t("Invoices")}</th>
          </tr>
        </thead>
        <tbody>
          {data.months.map((m, row) => {
            const inv = invoices[m];
            const waiting = inv ? inv.not_approved + inv.no_run : 0;
            return (
              <tr key={m}>
                <th scope="row" className="mono">{m}</th>
                {columns.map((c) => <Cell key={`${c.key}|${c.currency}`} cell={c.months[row]} />)}
                <td className="num">
                  {inv?.total ?? 0}
                  {waiting ? <span className="muted small"> · {t("{{n}} not approved", { n: waiting })}</span> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** What the grid's columns lack, in sentences; empty when every expected month is in order. */
export function monthWarnings(data: PartyMonths, accounts?: string[]): string[] {
  const columns = accounts ? data.columns.filter((c) => accounts.includes(c.key)) : data.columns;
  const n = (pick: (c: MonthCell) => boolean) => columns.reduce((s, col) => s + col.months.filter(pick).length, 0);
  const out: string[] = [];
  const missing = n((c) => c.state === "missing");
  const partial = n((c) => c.state === "partial");
  const unverified = n((c) => c.state === "unverified");
  const unapproved = n((c) => c.state === "unapproved");
  const overlap = n((c) => c.flags.includes("overlap"));
  const broken = n((c) => c.flags.includes("break"));
  if (missing) out.push(t("{{n}} months of an account have no statement: their invoices will show “No statement for its period”, not “No payment found”.", { n: missing }));
  if (partial) out.push(t("{{n}} months of an account are covered only in part.", { n: partial }));
  if (unverified) out.push(t("{{n}} months of an account have a statement whose balances do not check out.", { n: unverified }));
  if (unapproved) out.push(t("{{n}} months of an account have a statement whose run is not approved yet.", { n: unapproved }));
  if (overlap) out.push(t("{{n}} months of an account have two statements for the same days: their lines may be counted twice.", { n: overlap }));
  if (broken) out.push(t("{{n}} months of an account do not continue the previous closing balance: a statement may be missing or wrong.", { n: broken }));
  return out;
}

/** The previous month and the January of its year, as the default period ("YYYY-MM"). */
function defaultPeriod(today = new Date()): [string, string] {
  const last = new Date(Date.UTC(today.getFullYear(), today.getMonth(), 0));
  return [`${last.getUTCFullYear()}-01`, last.toISOString().slice(0, 7)];
}

/** A party's monthly data status with its own period (the settings page). */
export function MonthStatus({ partyId }: { partyId: string }) {
  useLocale();
  const [[start, end], setPeriod] = useState<[string, string]>(defaultPeriod);
  const valid = /^\d{4}-\d{2}$/.test(start) && /^\d{4}-\d{2}$/.test(end) && start <= end;
  const loaded = useLoad(valid ? `party-months:${partyId}:${start}:${end}` : null, () => api.partyMonths(partyId, start, end));
  const warnings = loaded.data ? monthWarnings(loaded.data) : [];
  return (
    <div className="ms-stack">
      <div className="rc-period">
        <label className="block">{t("From month")}
          <input type="month" value={start} onChange={(e) => setPeriod([e.target.value, end])} />
        </label>
        <label className="block">{t("to")}
          <input type="month" value={end} onChange={(e) => setPeriod([start, e.target.value])} />
        </label>
      </div>
      {!valid ? <p className="small warn-text">{t("The period ends before it starts.")}</p> : null}
      {loaded.error ? <p className="notice error" role="alert">{loaded.error.message}</p> : null}
      {loaded.data ? (
        loaded.data.columns.length ? (
          <>
            {warnings.length ? <ul className="small ms-warnings">{warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              : <p className="small ok">{t("Every expected month has an approved statement that checks out.")}</p>}
            <MonthGrid data={loaded.data} />
          </>
        ) : <p className="muted small">{t("The party has no account or card yet: register one, or process its statements.")}</p>
      ) : valid && !loaded.error ? <p className="muted">{t("Loading…")}</p> : null}
    </div>
  );
}
