// 132 (backlog F-reconciliation E2): the own accounts and cards a reconciliation pairs, with what the store has of
// them; 133: the chosen party's first; 138: one registered without a statement too. 231 (C3e): the reconciliation's own
// create form went (a reconciliation is the reconciliation pack's case, started from the general form), so its scope's
// account list lives here.
import type { ReconcileAccount } from "../api";
import { t, useLocale } from "../../../i18n";
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
