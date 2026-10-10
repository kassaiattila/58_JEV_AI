// 133 (backlog F-own-parties; DECISIONS 133): the own parties — the companies, associations and people whose money is
// reconciled. The data proposes them (the buyer's tax number and name on the invoices, the holder's name at the top of
// a statement); a person accepts them and rearranges them at any time (the owner's decision of 2026-10-10): renames a
// party, moves a name variant, a tax number or an account to another party, merges two parties, dismisses what names
// no own party. A reconciliation package is one party's and follows every change at once.
// 138 (DECISIONS 137): an account or card is registered with its party in advance (kind, bank, currencies, the days it
// was open), so a month without its statement shows; the party's data status month by month folds open below.
import { useEffect, useState } from "react";
import {
  api, ApiError, type AccountDetailsInput, type AccountKind, type OwnParty, type PartiesOverview, type PartyAccount,
  type PartyIdentity, type PartySuggestion,
} from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { tmap } from "../../labels";
import { MonthStatus } from "./MonthStatus";
import "./parties.css";

const KIND: Record<string, string> = tmap({ tax: "Tax number", name: "Name variant", account: "Account or card" });
const ACCOUNT_KIND: Record<string, string> = tmap({ account: "Bank account", card: "Card" });
const NAMES_SHOWN = 4; // more name variants than this fold into a list

/** Runs a change and shows the overview it answers with; true when it went through. */
type Act = (fn: () => Promise<PartiesOverview>, done: string) => Promise<boolean>;

/** How often an identity is printed: a tax number or a name on so many invoices (some of them may go to another party by
 *  their tax number), an account in so many statements. */
function count(i: PartyIdentity): string {
  return i.kind === "account" ? t("{{n}} statements", { n: i.invoices }) : t("on {{n}} invoices", { n: i.invoices });
}

/** A party's or a suggestion's identities in brief: tax numbers and accounts one by one, name variants folded. */
function Identities({ list }: { list: PartyIdentity[] }) {
  useLocale();
  const names = list.filter((i) => i.kind === "name");
  const chips = (items: PartyIdentity[]) => items.map((i) => (
    <span key={`${i.kind}|${i.key}`} className="pt-id" title={KIND[i.kind]}>
      <span className={i.kind === "name" ? "" : "mono"}>{i.label}</span> <span className="muted">({count(i)})</span>
    </span>
  ));
  return (
    <div className="pt-ids">
      {chips(list.filter((i) => i.kind !== "name"))}
      {names.length <= NAMES_SHOWN ? chips(names) : (
        <details className="pt-names">
          <summary>{t("{{n}} name variants", { n: names.length })}</summary>
          <div className="pt-ids">{chips(names)}</div>
        </details>
      )}
    </div>
  );
}

export function PartiesPanel() {
  useLocale();
  const loaded = useLoad("parties", api.parties);
  const [data, setData] = useState<PartiesOverview | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  useEffect(() => { if (loaded.data) setData(loaded.data); }, [loaded.data]);

  const act: Act = async (fn, done) => {
    setBusy(true);
    setMsg(null);
    try {
      setData(await fn());
      setMsg({ error: false, text: done });
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setMsg({ error: true, text: t("The data changed meanwhile; the suggestions have been reloaded. Check them and try again.") });
        loaded.reload();
      } else setMsg({ error: true, text: e instanceof ApiError ? e.message : String(e) });
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (!data) return loaded.error ? <p className="notice error" role="alert">{loaded.error.message}</p> : <p className="muted">{t("Loading…")}</p>;
  const claimed = data.invoices - data.unclaimed_invoices;
  return (
    <div className="pt-stack">
      <section className="card wide" aria-label={t("Own parties")}>
        <p className="muted small">
          {t("An own party is a company, an association or a person whose money is reconciled. The system proposes them from the processed documents: the buyer's tax number and name on the invoices, and the holder's name at the top of a statement. Accept them, then rearrange them at any time; a reconciliation package is one party's and follows every change at once.")}
        </p>
        <p className="small">{t("{{n}} incoming invoices: {{claimed}} belong to an own party, {{unclaimed}} to none yet.", { n: data.invoices, claimed, unclaimed: data.unclaimed_invoices })}</p>
        {data.buyer_is_supplier ? <p className="muted small">{t("{{n}} invoices name their own supplier as the buyer (a misreading); that name is not taken as a buyer.", { n: data.buyer_is_supplier })}</p> : null}
        {msg ? <p className={msg.error ? "notice error" : "small ok"} role={msg.error ? "alert" : "status"}>{msg.text}</p> : null}
      </section>
      {data.suggestions.length ? <Suggestions data={data} busy={busy} act={act} /> : null}
      {data.parties.map((p) => <PartyCard key={p.id} party={p} others={data.parties.filter((o) => o.id !== p.id)} busy={busy} act={act} />)}
      {!data.parties.length && !data.suggestions.length ? <p className="muted">{t("No invoice or statement names a buyer or a holder yet.")}</p> : null}
      {data.unassigned.length ? <Unassigned data={data} busy={busy} act={act} /> : null}
      {data.dismissed.length ? <Dismissed list={data.dismissed} busy={busy} act={act} /> : null}
    </div>
  );
}

function Suggestions({ data, busy, act }: { data: PartiesOverview; busy: boolean; act: Act }) {
  useLocale();
  const [names, setNames] = useState<Record<string, string>>({});
  const nameOf = (s: PartySuggestion) => names[s.id] ?? s.name;
  const partyName = (id: string | null) => data.parties.find((p) => p.id === id)?.name ?? "";
  const given = (ids: string[]) => Object.fromEntries(ids.filter((id) => names[id]?.trim()).map((id) => [id, names[id].trim()]));
  const dismiss = (s: PartySuggestion) => act(async () => {
    let last: PartiesOverview | null = null;
    for (const i of s.identities) last = await api.setPartyIdentity(i, "dismiss");
    return last!;
  }, t("Dismissed: it names no own party."));
  return (
    <section className="card wide" aria-label={t("Suggestions from the data")}>
      <div className="card-head">
        <h3>{t("Suggestions from the data")}</h3>
        {data.suggestions.length > 1 ? (
          <ConfirmButton className="primary" disabled={busy}
            onConfirm={() => void act(() => api.acceptPartySuggestions(data.suggestions.map((s) => s.id), given(data.suggestions.map((s) => s.id))), t("The suggestions have been accepted."))}>
            {t("Accept all {{n}}", { n: data.suggestions.length })}
          </ConfirmButton>
        ) : null}
      </div>
      <p className="muted small">{t("Check the name of each new party, and dismiss what names no own party of yours (for example a buyer misread from a ticket).")}</p>
      <ul className="plain pt-list">
        {data.suggestions.map((s) => (
          <li key={s.id} className="pt-row">
            <div className="pt-main">
              {s.party_id ? <strong>{t("Add to {{party}}", { party: partyName(s.party_id) })}</strong> : (
                <input value={nameOf(s)} maxLength={200} aria-label={t("Name of the new party")} disabled={busy}
                  onChange={(e) => setNames((n) => ({ ...n, [s.id]: e.target.value }))} />
              )}
              <span className="muted small">{t("{{n}} invoices", { n: s.invoices })}</span>
            </div>
            <Identities list={s.identities} />
            <div className="button-row">
              <button type="button" className="secondary" disabled={busy || !nameOf(s).trim()}
                onClick={() => void act(() => api.acceptPartySuggestions([s.id], given([s.id])), t("The suggestion has been accepted."))}>
                {s.party_id ? t("Add") : t("Accept")}
              </button>
              <ConfirmButton className="quiet" disabled={busy} onConfirm={() => void dismiss(s)}>{t("Not own")}</ConfirmButton>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Where an identity can go: another party, nowhere (unassigned, proposed again) or dismissed. */
function MoveIdentity({ identity, targets, busy, act }: { identity: PartyIdentity; targets: OwnParty[]; busy: boolean; act: Act }) {
  useLocale();
  const [to, setTo] = useState("");
  function move() {
    if (to === "dismiss") void act(() => api.setPartyIdentity(identity, "dismiss"), t("Dismissed: it names no own party."));
    else if (to === "release") void act(() => api.setPartyIdentity(identity, "release"), t("Taken out of the party; it is proposed again."));
    else if (to) void act(() => api.setPartyIdentity(identity, "assign", to), t("Moved."));
    setTo("");
  }
  return (
    <span className="pt-move">
      <select value={to} disabled={busy} aria-label={t("Move {{label}}", { label: identity.label })} onChange={(e) => setTo(e.target.value)}>
        <option value="">{t("Move to…")}</option>
        {targets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        <option value="release">{t("No party (unassigned)")}</option>
        <option value="dismiss">{t("Not own (dismissed)")}</option>
      </select>
      <button type="button" className="quiet small-btn" disabled={busy || !to} onClick={move}>{t("Move")}</button>
    </span>
  );
}

function IdentityRows({ list, targets, busy, act }: { list: PartyIdentity[]; targets: OwnParty[]; busy: boolean; act: Act }) {
  useLocale();
  return (
    <table className="table compact pt-table">
      <tbody>
        {list.map((i) => (
          <tr key={`${i.kind}|${i.key}`}>
            <td className="muted small">{KIND[i.kind]}</td>
            <td className={i.kind === "name" ? "" : "mono"}>{i.label}</td>
            <td className="num small">{count(i)}</td>
            <td><MoveIdentity identity={i} targets={targets} busy={busy} act={act} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** 138: what a person registers of an account or card; with `withNumber` its number too (a new one). */
export function AccountForm({ initial, withNumber, busy, onSave, onCancel }: {
  initial?: PartyAccount; withNumber?: boolean; busy: boolean;
  onSave: (details: AccountDetailsInput, number: string) => void; onCancel: () => void;
}) {
  useLocale();
  const reg = initial?.registered;
  const [number, setNumber] = useState("");
  const [kind, setKind] = useState<AccountKind>(reg?.kind ?? (initial?.statement_types.includes("credit_card") ? "card" : "account"));
  const [bank, setBank] = useState(reg?.bank ?? "");
  const [currencies, setCurrencies] = useState((reg?.currencies ?? initial?.currencies ?? ["HUF"]).join(", "));
  const [from, setFrom] = useState(reg?.valid_from ?? "");
  const [to, setTo] = useState(reg?.valid_to ?? "");
  const codes = currencies.split(/[\s,;]+/).map((c) => c.trim().toUpperCase()).filter(Boolean);
  const valid = codes.length > 0 && codes.every((c) => /^[A-Z]{3}$/.test(c)) && (!withNumber || number.trim().length > 0)
    && (!from || !to || from <= to);
  return (
    <form className="pt-account-form" aria-label={withNumber ? t("New account or card") : t("Details of {{label}}", { label: initial?.label ?? "" })}
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) onSave({ kind, currencies: codes, bank: bank.trim() || null, valid_from: from || null, valid_to: to || null }, number.trim());
      }}>
      {withNumber ? (
        <label className="block">{t("Account number (IBAN or domestic)")}
          <input value={number} maxLength={80} onChange={(e) => setNumber(e.target.value)} className="mono" />
        </label>
      ) : null}
      <label className="block">{t("Kind")}
        <select value={kind} onChange={(e) => setKind(e.target.value as AccountKind)}>
          <option value="account">{ACCOUNT_KIND.account}</option>
          <option value="card">{ACCOUNT_KIND.card}</option>
        </select>
      </label>
      <label className="block">{t("Bank")} <span className="muted">{t("(optional)")}</span>
        <input value={bank} maxLength={100} onChange={(e) => setBank(e.target.value)} />
      </label>
      <label className="block">{t("Currencies")}
        <input value={currencies} maxLength={60} onChange={(e) => setCurrencies(e.target.value)} placeholder="HUF, EUR" />
      </label>
      <label className="block">{t("Opened")} <span className="muted">{t("(optional)")}</span>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
      </label>
      <label className="block">{t("Closed")} <span className="muted">{t("(optional)")}</span>
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
      </label>
      {from && to && from > to ? <p className="small warn-text">{t("The account is closed before it was opened.")}</p> : null}
      <div className="button-row">
        <button type="submit" className="secondary" disabled={busy || !valid}>{t("Save")}</button>
        <button type="button" className="quiet" onClick={onCancel}>{t("Cancel")}</button>
      </div>
    </form>
  );
}

/** 138: an account's registered details in brief, or what its statements show. */
function accountDetails(a: PartyAccount | undefined): string {
  if (!a) return "";
  const reg = a.registered;
  const parts = [reg ? ACCOUNT_KIND[reg.kind] : null, reg?.bank, a.currencies.join(", ")];
  if (reg?.valid_from || reg?.valid_to) parts.push(`${reg.valid_from ?? "…"} – ${reg.valid_to ?? "…"}`);
  return parts.filter(Boolean).join(" · ");
}

/** 138: the party's accounts and cards with their details, each movable like any identity and its details editable. */
function AccountRows({ party, targets, busy, act }: { party: OwnParty; targets: OwnParty[]; busy: boolean; act: Act }) {
  useLocale();
  const [editing, setEditing] = useState<string | null>(null);
  const list = party.identities.filter((i) => i.kind === "account");
  const info = Object.fromEntries(party.accounts.map((a) => [a.key, a]));
  if (!list.length) return null;
  return (
    <table className="table compact pt-table">
      <tbody>
        {list.map((i) => (
          editing === i.key ? (
            <tr key={i.key}>
              <td colSpan={4}>
                <span className="mono">{i.label}</span>
                <AccountForm initial={info[i.key]} busy={busy} onCancel={() => setEditing(null)}
                  onSave={(details) => void act(() => api.setPartyAccount(i.key, details), t("The account's details have been saved."))
                    .then((ok) => { if (ok) setEditing(null); })} />
              </td>
            </tr>
          ) : (
            <tr key={i.key}>
              <td className="muted small">{KIND[i.kind]}</td>
              <td>
                <span className="mono">{i.label}</span>
                <div className="pt-details">{accountDetails(info[i.key]) || t("no details registered")}</div>
              </td>
              <td className="num small">{i.invoices ? count(i) : t("no statement yet")}</td>
              <td>
                <button type="button" className="quiet small-btn" disabled={busy} onClick={() => setEditing(i.key)}>{t("Details")}</button>
                <MoveIdentity identity={i} targets={targets} busy={busy} act={act} />
              </td>
            </tr>
          )
        ))}
      </tbody>
    </table>
  );
}

function PartyCard({ party, others, busy, act }: { party: OwnParty; others: OwnParty[]; busy: boolean; act: Act }) {
  useLocale();
  const [editing, setEditing] = useState<string | null>(null);
  const [into, setInto] = useState("");
  const [adding, setAdding] = useState(false);
  const [monthsOpen, setMonthsOpen] = useState(false);
  const fixed = party.identities.filter((i) => i.kind === "tax");
  const names = party.identities.filter((i) => i.kind === "name");
  const span = party.first ? ` · ${party.first} – ${party.last}` : "";
  return (
    <section className="card wide" aria-label={party.name}>
      <div className="card-head">
        {editing === null ? (
          <h3>{party.name} <button type="button" className="quiet small-btn" disabled={busy} onClick={() => setEditing(party.name)}>{t("Rename")}</button></h3>
        ) : (
          <form className="pt-main" onSubmit={(e) => {
            e.preventDefault();
            if (editing.trim()) void act(() => api.renameParty(party.id, editing.trim()), t("The party has been renamed.")).then((ok) => { if (ok) setEditing(null); });
          }}>
            <input value={editing} maxLength={200} autoFocus aria-label={t("New name of {{party}}", { party: party.name })} onChange={(e) => setEditing(e.target.value)} />
            <button type="submit" className="secondary" disabled={busy || !editing.trim()}>{t("Save")}</button>
            <button type="button" className="quiet" onClick={() => setEditing(null)}>{t("Cancel")}</button>
          </form>
        )}
      </div>
      <p className="small">
        {t("{{n}} invoices", { n: party.invoices })}{span}
        {" · "}
        {party.statements_first
          ? t("statements {{first}} – {{last}}", { first: party.statements_first, last: party.statements_last ?? "?" })
          : t("no statement yet")}
      </p>
      {fixed.length ? <IdentityRows list={fixed} targets={others} busy={busy} act={act} /> : null}
      <AccountRows party={party} targets={others} busy={busy} act={act} />
      {adding ? (
        <AccountForm withNumber busy={busy} onCancel={() => setAdding(false)}
          onSave={(details, number) => void act(() => api.registerPartyAccount(party.id, number, details), t("The account has been registered."))
            .then((ok) => { if (ok) setAdding(false); })} />
      ) : (
        <div className="button-row">
          <button type="button" className="quiet small-btn" disabled={busy} onClick={() => setAdding(true)}>{t("Register a bank account or card")}</button>
        </div>
      )}
      {names.length ? (
        <details className="pt-names" open={names.length <= NAMES_SHOWN}>
          <summary>{t("{{n}} name variants", { n: names.length })}</summary>
          <IdentityRows list={names} targets={others} busy={busy} act={act} />
        </details>
      ) : null}
      <details className="pt-names" onToggle={(e) => setMonthsOpen((e.target as HTMLDetailsElement).open)}>
        <summary>{t("Data status by month")}</summary>
        {monthsOpen ? <MonthStatus partyId={party.id} /> : null}
      </details>
      <div className="button-row">
        {others.length ? (
          <span className="pt-move">
            <select value={into} disabled={busy} aria-label={t("Merge {{party}} into", { party: party.name })} onChange={(e) => setInto(e.target.value)}>
              <option value="">{t("Merge into…")}</option>
              {others.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <ConfirmButton className="quiet" disabled={busy || !into}
              onConfirm={() => void act(() => api.mergeParty(party.id, into), t("The parties have been merged."))}>{t("Merge")}</ConfirmButton>
          </span>
        ) : null}
        <span className="spacer" />
        <ConfirmButton className="quiet" disabled={busy} ariaLabel={t("Delete {{party}}", { party: party.name })}
          onConfirm={() => void act(() => api.deleteParty(party.id), t("The party has been deleted; its names and accounts are proposed again."))}>
          {t("Delete")}
        </ConfirmButton>
      </div>
    </section>
  );
}

/** The identities nothing claims: given to a party, made a new party, or dismissed. */
function Unassigned({ data, busy, act }: { data: PartiesOverview; busy: boolean; act: Act }) {
  useLocale();
  const [to, setTo] = useState<Record<string, string>>({});
  const key = (i: PartyIdentity) => `${i.kind}|${i.key}`;
  function give(i: PartyIdentity) {
    const target = to[key(i)];
    if (target === "new") void act(() => api.createParty(i.label, [i]), t("A new party has been made of it."));
    else if (target) void act(() => api.setPartyIdentity(i, "assign", target), t("Moved."));
  }
  return (
    <section className="card wide" aria-label={t("Unassigned")}>
      <div className="card-head"><h3>{t("Unassigned")}</h3></div>
      <p className="muted small">{t("Seen on too few invoices, or like more than one party: give them to a party, make a new party of them, or dismiss them.")}</p>
      <table className="table compact pt-table">
        <tbody>
          {data.unassigned.map((i) => (
            <tr key={key(i)}>
              <td className="muted small">{KIND[i.kind]}</td>
              <td className={i.kind === "name" ? "" : "mono"}>{i.label}</td>
              <td className="num small">{count(i)}</td>
              <td>
                <span className="pt-move">
                  <select value={to[key(i)] ?? ""} disabled={busy} aria-label={t("Give {{label}} to", { label: i.label })}
                    onChange={(e) => setTo((m) => ({ ...m, [key(i)]: e.target.value }))}>
                    <option value="">{t("Give to…")}</option>
                    {data.parties.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    <option value="new">{t("A new party")}</option>
                  </select>
                  <button type="button" className="quiet small-btn" disabled={busy || !to[key(i)]} onClick={() => give(i)}>{t("Give")}</button>
                  <ConfirmButton className="quiet small-btn" disabled={busy}
                    onConfirm={() => void act(() => api.setPartyIdentity(i, "dismiss"), t("Dismissed: it names no own party."))}>{t("Not own")}</ConfirmButton>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Dismissed({ list, busy, act }: { list: PartyIdentity[]; busy: boolean; act: Act }) {
  useLocale();
  return (
    <details className="card wide pt-dismissed">
      <summary>{t("Not own ({{n}})", { n: list.length })}</summary>
      <table className="table compact pt-table">
        <tbody>
          {list.map((i) => (
            <tr key={`${i.kind}|${i.key}`}>
              <td className="muted small">{KIND[i.kind]}</td>
              <td className={i.kind === "name" ? "" : "mono"}>{i.label}</td>
              <td className="num small">{count(i)}</td>
              <td>
                <button type="button" className="quiet small-btn" disabled={busy}
                  onClick={() => void act(() => api.setPartyIdentity(i, "release"), t("Taken back; it is proposed again."))}>{t("Undo")}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
