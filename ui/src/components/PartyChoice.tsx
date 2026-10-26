// 133: the own parties to choose from, each with its invoices and its statements' span. 176 (plan 170 L3): moved out of
// the reconciliation's creation form, as the statement package and the workflow wizard choose a party with it too.
import type { OwnParty, PartiesOverview } from "../api";
import { t, useLocale } from "../i18n";

/** 140: `anyParty` offers a party without an account too (a statement package brings its first statements). */
export function PartyChoice({ overview, value, onPick, anyParty = false }: {
  overview: PartiesOverview; value: string | null; onPick: (p: OwnParty) => void; anyParty?: boolean;
}) {
  useLocale();
  const list = overview.parties;
  return (
    <fieldset className="rc-accounts rc-parties">
      <legend className="small muted">{t("Own party")}</legend>
      {list.map((p) => {
        const noAccount = !p.accounts.length && !anyParty;
        return (
          <label key={p.id} className={noAccount ? "muted" : undefined}>
            <input type="radio" name="rc-party" checked={value === p.id} disabled={noAccount} onChange={() => onPick(p)} />
            <span>
              <strong>{p.name}</strong>{" "}
              <span className="muted small">
                {t("{{n}} invoices", { n: p.invoices })}{p.first ? `, ${p.first} – ${p.last}` : ""}{" · "}
                {!p.accounts.length ? t("no account or statement yet")
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
