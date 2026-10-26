// 181 (plan 170 L5; DECISIONS 181): a work package's scope - the own party, the period and the role (what it collects:
// incoming invoices, outgoing invoices, bank statements) it belongs to. The email routing proposes the package whose
// scope fits an emailed document. A workflow step's package takes its workflow's party and period and the step's role;
// a statement package has its own; any other package that processes documents can be given one here, by hand.
import { useState } from "react";
import { api, type PackageScope, type WorkpackageView } from "../api";
import { useLoad } from "../hooks";
import { partOf } from "../logic/packageParts";
import { t, useLocale } from "../i18n";

const FROM: Record<string, string> = { workflow: "from its workflow", logic_pack: "its own" };

/** The scope in words: the party, the period and the role that are given, and where it comes from. */
export function scopeText(scope: PackageScope): string {
  const parts = [scope.party, scope.period_start ? `${scope.period_start} – ${scope.period_end ?? scope.period_start}` : null,
    scope.role_title ? t(scope.role_title) : null].filter(Boolean);
  const from = FROM[scope.from];
  return from ? `${parts.join(" · ")} (${t(from)})` : parts.join(" · ");
}

/** Whether a person can give this package a scope (not a package whose logic pack, or (231 C3e) whose rule, has one
 *  of its own). */
export function scopeEditable(view: WorkpackageView): boolean {
  return view.scope?.from !== "logic_pack" && !partOf(view)?.ownScope;
}

export function ScopeForm({ view, busy, onSave, onClear, onCancel }: {
  view: WorkpackageView; busy: boolean;
  onSave: (scope: { party_id: string | null; period_start: string | null; period_end: string | null; role: string | null }) => void;
  onClear: () => void; onCancel: () => void;
}) {
  useLocale();
  const wp = view.workpackage;
  const scope = view.scope;
  const parties = useLoad("parties", api.parties);
  const roles = useLoad("package-roles", api.packageRoles);
  const [party, setParty] = useState(scope?.party_id ?? "");
  const [start, setStart] = useState(scope?.period_start ?? "");
  const [end, setEnd] = useState(scope?.period_end ?? "");
  const [role, setRole] = useState(scope?.role ?? "");
  const fitting = (roles.data?.roles ?? []).filter((r) => r.package_kinds.includes(wp.source_kind));
  const periodOk = (!start && !end) || (Boolean(start) && Boolean(end) && start <= end);
  const given = Boolean(party || start || role);
  return (
    <form className="create" aria-label={t("Party, period and role")} onSubmit={(e) => {
      e.preventDefault();
      onSave({ party_id: party || null, period_start: start || null, period_end: end || null, role: role || null });
    }}>
      <p className="small muted">{t("The email routing proposes this package for the documents of its party, period and role.")}</p>
      {scope && scope.from !== "own" ? <p className="small">{t("Now: {{scope}}", { scope: scopeText(scope) })}</p> : null}
      {parties.error ? <p className="notice error" role="alert">{parties.error.message}</p> : null}
      <label className="block">{t("Own party")}
        <select value={party} onChange={(e) => setParty(e.target.value)}>
          <option value="">{t("No party")}</option>
          {(parties.data?.parties ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      <div className="rc-period">
        <label className="block">{t("Period from")}<input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
        <label className="block">{t("to")}<input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
      </div>
      {!periodOk ? <p className="small warn-text">{t("Give both days of the period, the first not after the second.")}</p> : null}
      <label className="block">{t("Role")}
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="">{t("No role")}</option>
          {fitting.map((r) => <option key={r.name} value={r.name}>{t(r.title)}</option>)}
        </select>
      </label>
      <div className="button-row">
        <button type="submit" className={given && periodOk ? "primary" : "secondary"} disabled={busy || !given || !periodOk}>{t("Save")}</button>
        {scope?.from === "own" ? (
          <button type="button" className="secondary" disabled={busy} onClick={onClear}>{t("Remove the package's own scope")}</button>
        ) : null}
        <button type="button" className="secondary" onClick={onCancel}>{t("Cancel")}</button>
      </div>
    </form>
  );
}
