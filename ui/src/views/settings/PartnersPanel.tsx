// 231 (plan stage B, B1; DECISIONS 231): the partner register in Settings: the outside parties every process deals with
// (customers, suppliers, insured persons, brokers), each with the roles it plays. A person finds a partner by name, tax
// number or email, records a new one or saves a change as a new version (a page that shows an older version is
// refused), retires one rather than deleting it and restores it; the versions show who changed what and when. The
// domains propose partners from what they have read (an invoice's supplier), on request; a person records them. A
// partner with the same tax number or name as another one is refused, and the page leads to that one.
import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type Partner, type PartnerRoles, type PartnerSuggestion, type PartnerValues } from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { VersionState } from "../../components/VersionState";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";

const EMPTY: PartnerValues = { name: "", tax_number: null, email: null, phone: null, address: null, note: null, roles: [] };
const TEXT_FIELDS: { key: "tax_number" | "email" | "phone"; label: string; max: number }[] = [
  { key: "tax_number", label: "Tax number", max: 40 }, { key: "email", label: "Email", max: 200 },
  { key: "phone", label: "Phone", max: 60 },
];

const roleText = (roles: string[], known: PartnerRoles) => roles.map((r) => t(known[r]?.label ?? r)).join(" · ");
const same = (a: PartnerValues, b: PartnerValues) =>
  JSON.stringify({ ...a, roles: [...a.roles].sort() }) === JSON.stringify({ ...b, roles: [...b.roles].sort() });
const valuesOf = (p: PartnerValues): PartnerValues =>
  ({ name: p.name, tax_number: p.tax_number, email: p.email, phone: p.phone, address: p.address, note: p.note, roles: p.roles });

type Open = { kind: "new"; from?: PartnerValues } | { kind: "partner"; id: string } | null;

export function PartnersPanel() {
  useLocale();
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [retired, setRetired] = useState(false);
  const list = useLoad(`partners:${q}:${role}:${retired}`, () => api.partners({ q: q.trim() || undefined, role: role || undefined, retired }));
  const [open, setOpen] = useState<Open>(null);
  const roles = list.data?.roles ?? {};
  const rows = list.data?.partners ?? [];
  return (
    <div className="partners">
      <div className="form-row partners-tools">
        <label className="block grow">{t("Search")}
          <input value={q} maxLength={200} autoComplete="off" placeholder={t("Name, tax number or email…")} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label className="block">{t("Role")}
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">{t("Every role")}</option>
            {Object.entries(roles).map(([key, r]) => <option key={key} value={key}>{t(r.label)}</option>)}
          </select>
        </label>
        <label className="check small partners-retired">
          <input type="checkbox" checked={retired} onChange={(e) => setRetired(e.target.checked)} /> {t("Retired ones too")}
        </label>
        <button type="button" className={open ? "secondary" : "primary"} onClick={() => setOpen({ kind: "new" })}>{t("New partner")}</button>
      </div>
      {list.error ? <p className="notice error" role="alert">{list.error.message}</p> : null}
      {!list.data ? <p className="muted">{t("Loading…")}</p> : rows.length ? (
        <table className="table compact partners-table" aria-label={t("Partners")}>
          <thead><tr><th>{t("Name")}</th><th>{t("Roles")}</th><th>{t("Tax number")}</th><th>{t("Email")}</th><th>{t("Changed")}</th></tr></thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.partner_id} aria-selected={open?.kind === "partner" && open.id === p.partner_id}>
                <td>
                  <button type="button" className="link-btn partner-open" onClick={() => setOpen({ kind: "partner", id: p.partner_id })}>{p.name}</button>
                  {p.retired ? <> <VersionState state="retired" /></> : null}
                </td>
                <td>{roleText(p.roles, roles)}</td>
                <td className="mono">{p.tax_number ?? "–"}</td>
                <td>{p.email ?? "–"}</td>
                <td className="tnum">{when(p.changed_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">{q || role ? t("No partner matches.") : t("No partner yet. Record one, or take one from the proposals below.")}</p>
      )}
      {open ? <PartnerCard key={open.kind === "partner" ? open.id : "new"} open={open} roles={roles}
        onOpen={(id) => setOpen({ kind: "partner", id })} onClose={() => setOpen(null)} onChanged={list.reload} /> : null}
      <Suggestions roles={roles} onTake={(s) => setOpen({ kind: "new", from: { ...EMPTY, name: s.name, tax_number: s.tax_number, roles: s.roles } })} />
    </div>
  );
}

/** One partner (or a new one): its values to change, its retirement, its versions. */
function PartnerCard({ open, roles, onOpen, onClose, onChanged }: {
  open: NonNullable<Open>; roles: PartnerRoles; onOpen: (id: string) => void; onClose: () => void; onChanged: () => void;
}) {
  useLocale();
  const id = open.kind === "partner" ? open.id : null;
  const loaded = useLoad(`partner:${id ?? "new"}`, () => (id ? api.partner(id) : Promise.resolve(null)));
  const partner: Partner | null = loaded.data ?? null;
  const start = useMemo(() => (partner ? valuesOf(partner) : open.kind === "new" ? open.from ?? EMPTY : EMPTY), [partner, open]);
  // what the person changed, on top of what was loaded (null: nothing yet); a saved or reloaded version starts afresh
  const [draft, setDraft] = useState<PartnerValues | null>(null);
  useEffect(() => setDraft(null), [partner?.version, partner?.retired]);
  const values = draft ?? start;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ text: string; other: string | null } | null>(null);
  const changed = !same(values, start);
  const ready = values.name.trim() !== "" && values.roles.length > 0;
  const set = (patch: Partial<PartnerValues>) => setDraft({ ...values, ...patch });
  const text = (v: string) => (v.trim() ? v : null);

  async function run(fn: () => Promise<Partner>) {
    setBusy(true);
    setError(null);
    try {
      const saved = await fn();
      onChanged();
      if (!id) onOpen(saved.partner_id);
      else loaded.reload();
    } catch (e) {
      setError(e instanceof ApiError ? { text: e.message, other: e.code === "partner_conflict" && e.detail.other !== id ? e.detail.other ?? null : null }
        : { text: String(e), other: null });
      if (e instanceof ApiError && e.code === "partner_conflict" && e.detail.other === id) loaded.reload();
    } finally {
      setBusy(false);
    }
  }
  if (id && !partner) return loaded.error ? <p className="notice error" role="alert">{loaded.error.message}</p> : <p className="muted">{t("Loading…")}</p>;
  const save = () => run(() => (partner ? api.updatePartner(partner.partner_id, values, partner.version) : api.createPartner(values)));

  return (
    <section className="card wide partner-card" aria-label={partner ? partner.name : t("New partner")}>
      <div className="card-head">
        <h3>{partner ? partner.name : t("New partner")}</h3>
        <span className="button-row">
          {partner?.retired ? <VersionState state="retired" /> : null}
          <button type="button" className="quiet small-btn" onClick={onClose}>{t("Close")}</button>
        </span>
      </div>
      <div className="form-row">
        <label className="block grow">{t("Name")}
          <input value={values.name} maxLength={200} autoComplete="off" disabled={partner?.retired} onChange={(e) => set({ name: e.target.value })} />
        </label>
        {TEXT_FIELDS.map((f) => (
          <label key={f.key} className="block">{t(f.label)}
            <input value={values[f.key] ?? ""} maxLength={f.max} autoComplete="off" disabled={partner?.retired}
              className={f.key === "tax_number" ? "mono" : undefined} onChange={(e) => set({ [f.key]: text(e.target.value) })} />
          </label>
        ))}
      </div>
      <label className="block">{t("Address")}
        <input value={values.address ?? ""} maxLength={400} autoComplete="off" disabled={partner?.retired} onChange={(e) => set({ address: text(e.target.value) })} />
      </label>
      <fieldset className="partner-roles" disabled={partner?.retired}>
        <legend>{t("Roles")}</legend>
        {Object.entries(roles).map(([key, r]) => (
          <label key={key} className="check" title={t(r.what)}>
            <input type="checkbox" checked={values.roles.includes(key)}
              onChange={(e) => set({ roles: e.target.checked ? [...values.roles, key] : values.roles.filter((x) => x !== key) })} />
            {t(r.label)}
          </label>
        ))}
      </fieldset>
      <label className="block">{t("Note")}
        <textarea value={values.note ?? ""} maxLength={2000} rows={2} disabled={partner?.retired} onChange={(e) => set({ note: e.target.value || null })} />
      </label>
      <div className="button-row">
        {partner?.retired ? (
          <button type="button" className="secondary" disabled={busy} onClick={() => void run(() => api.restorePartner(partner.partner_id))}>{t("Restore")}</button>
        ) : (
          <>
            <button type="button" className={changed && ready ? "primary" : "secondary"} disabled={busy || !changed || !ready} onClick={() => void save()}>
              {partner ? t("Save as a new version") : t("Record the partner")}
            </button>
            {partner ? (
              <ConfirmButton className="secondary" disabled={busy} onConfirm={() => void run(() => api.retirePartner(partner.partner_id))}>{t("Retire")}</ConfirmButton>
            ) : null}
            <span className="muted small">{partner ? t("A change is kept as a new version; the earlier ones stay.") : t("A name and at least one role are needed.")}</span>
          </>
        )}
      </div>
      {error ? (
        <p className="notice error small" role="alert">
          {error.text}
          {error.other ? <> {" "}<button type="button" className="link-btn" onClick={() => onOpen(error.other!)}>{t("Open it")}</button></> : null}
        </p>
      ) : null}
      {partner ? (
        <table className="table compact partner-versions" aria-label={t("Versions")}>
          <thead><tr><th>{t("Version")}</th><th>{t("State")}</th><th>{t("Roles")}</th><th>{t("Who")}</th><th>{t("When")}</th></tr></thead>
          <tbody>
            {partner.versions.map((v) => (
              <tr key={v.version}>
                <td className="num">{v.version}</td>
                <td><VersionState state={v.state} /></td>
                <td>{roleText(v.roles, roles)}</td>
                <td>{v.state === "retired" && v.retired_by ? v.retired_by : v.made_by}</td>
                <td className="tnum">{when(v.state === "retired" ? v.retired_at : v.made_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

/** The domains' proposals, on request (reading them goes through every invoice); a person records one. */
function Suggestions({ roles, onTake }: { roles: PartnerRoles; onTake: (s: PartnerSuggestion) => void }) {
  useLocale();
  const [shown, setShown] = useState(false);
  const found = useLoad(`partner-suggestions:${shown}`, () => (shown ? api.partnerSuggestions() : Promise.resolve(null)));
  return (
    <section className="partner-suggestions" aria-label={t("Proposals from the documents read")}>
      <div className="card-head">
        <h3>{t("Proposals from the documents read")}</h3>
        {!shown ? <button type="button" className="secondary small-btn" onClick={() => setShown(true)}>{t("Show the proposals")}</button> : null}
      </div>
      <p className="muted small">{t("The suppliers of the incoming invoices and the buyers of the outgoing ones that are not yet partners. Nothing is recorded by itself.")}</p>
      {shown && !found.data ? <p className="muted">{t("Loading…")}</p> : null}
      {found.data && !found.data.suggestions.length ? <p className="muted small">{t("No proposal: every party read is a partner already.")}</p> : null}
      {found.data?.suggestions.length ? (
        <table className="table compact" aria-label={t("Proposals")}>
          <thead><tr><th>{t("Name")}</th><th>{t("Tax number")}</th><th>{t("Seen as")}</th><th className="num">{t("Documents")}</th><th>{t("Last")}</th><th /></tr></thead>
          <tbody>
            {found.data.suggestions.map((s) => (
              <tr key={`${s.tax_number ?? ""}|${s.name}`}>
                <td>{s.name}</td>
                <td className="mono">{s.tax_number ?? "–"}</td>
                <td>{roleText(s.roles, roles)}</td>
                <td className="num">{s.seen}</td>
                <td className="tnum">{s.last ?? "–"}</td>
                <td><button type="button" className="secondary small-btn" onClick={() => onTake(s)}>{t("Record it")}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
