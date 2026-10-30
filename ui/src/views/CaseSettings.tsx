// 261 (plan B, B2b; the owner's decisions of 2026-10-29): what a case keeps from its start, read only, beside what a
// case started now would use: its resources at their versions and its rule values with where each came from (the
// process's own, the installation's default, the rule file). A change of the process's settings reaches only the cases
// started after it; the process's settings page, linked here, is where they change. Loaded once a person opens it.
import { useState } from "react";
import { api, type CaseSettings } from "../api";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";

const ORIGIN: Record<string, string> = { process: "The process's own value", installation: "The installation's default", file: "From the file" };

function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "–";
  if (Array.isArray(v)) return v.map(show).join(", ");
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${t(k)} ${show(x)}`).join(" · ");
  return String(v);
}

const named = (r: { name: string; version: number | null } | null) =>
  !r ? "–" : r.version != null ? t("{{name}}, version {{n}}", { name: t(r.name), n: r.version }) : t(r.name);

export function CaseSettingsCard({ caseId, pack }: { caseId: string; pack: string }) {
  useLocale();
  const [open, setOpen] = useState(false);
  const kept = useLoad<CaseSettings>(open ? `case-settings:${caseId}` : null, () => api.caseSettings(caseId));
  const d = kept.data;
  const rows = d ? d.resources.length + d.rules.length : 0;
  return (
    <section className="card wide" aria-label={t("The case's settings")}>
      <div className="card-head">
        <h2>{t("The case's settings")}</h2>
        <button type="button" className="secondary small-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? t("Hide") : t("Show the settings")}</button>
      </div>
      <p className="muted small">{t("The case keeps the settings of its start; a change reaches only the cases started after it.")}{" "}
        <a href={`#/settings/processes/${encodeURIComponent(pack)}/values`}>{t("The settings new cases use")} →</a></p>
      {open && kept.error ? <p className="notice error small" role="alert">{kept.error.message}</p> : null}
      {open && !d && !kept.error ? <p className="muted">{t("Loading…")}</p> : null}
      {open && d && !d.kept ? <p className="muted small">{t("The case started before its settings were kept: it reads the files and the active versions.")}</p> : null}
      {open && d && d.kept && !rows ? <p className="muted small">{t("The process keeps no setting of its own.")}</p> : null}
      {open && d && d.kept && rows ? (
        <table className="table compact" aria-label={t("The case's settings")}>
          <thead><tr><th>{t("Setting")}</th><th>{t("The case's value")}</th><th>{t("Where it came from")}</th><th>{t("For a case started now")}</th></tr></thead>
          <tbody>
            {d.resources.map((r) => (
              <tr key={r.key}>
                <td>{t(r.label)}</td><td>{named(r)}</td><td className="muted">{t("At its start")}</td>
                <td className={named(r.now) === named(r) ? "muted" : undefined}>{named(r.now)}</td>
              </tr>
            ))}
            {d.rules.map((r) => (
              <tr key={r.key}>
                <td>{t(r.what)}</td><td className="tnum">{show(r.value)}</td>
                <td className="muted">{t(ORIGIN[r.origin] ?? r.origin)}{r.version != null ? `, ${t("version {{n}}", { n: r.version })}` : ""}</td>
                <td className={`tnum${show(r.now) === show(r.value) ? " muted" : ""}`}>{show(r.now)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
