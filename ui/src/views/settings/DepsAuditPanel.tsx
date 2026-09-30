// 075: the result of the regular dependency audit on the System page — when it last ran, how
// many known vulnerabilities it found in the pinned Python and UI packages, and a warning when it is missing, stale or
// incomplete. The audit runs from the command line or with the daily backup (weekly); the service only reads it.
import { api, type DepsAuditInfo } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";

/** The audit state in one sentence and its warning level (shared by the card and the test). */
export function depsAuditState(info: DepsAuditInfo): { level: "ok" | "warn" | "error"; text: string } {
  const s = info.status;
  if (!s) return { level: "warn", text: t("A csomag-ellenőrzés még nem futott.") };
  const counts = { when: when(s.checked_at), n: s.finding_count, py: s.python?.packages ?? 0, ui: s.npm?.packages ?? 0 };
  if (s.finding_count > 0) return { level: "error", text: t("{{n}} ismert sebezhetőség a csomagokban ({{when}}).", counts) };
  if (s.errors.length) return { level: "warn", text: t("A legutóbbi csomag-ellenőrzés nem teljes ({{when}}): {{error}}", { when: counts.when, error: s.errors.join("; ") }) };
  if (s.stale) return { level: "warn", text: t("A legutóbbi csomag-ellenőrzés {{days}} napnál régebbi ({{when}}).", { days: info.max_age_days, when: counts.when }) };
  return { level: "ok", text: t("Nincs ismert sebezhetőség: {{py}} Python- és {{ui}} felület-csomag ({{when}}).", counts) };
}

export function DepsAuditPanel() {
  useLocale();
  const d = useLoad("deps-audit", api.depsAudit, 300000);
  const state = d.data ? depsAuditState(d.data) : null;
  return (
    <section className="card wide" aria-label={t("Csomag-ellenőrzés")}>
      <div className="card-head">
        <h3>{t("Csomag-ellenőrzés")}</h3>
      </div>
      {d.error ? <p className="notice error">{d.error.message}</p> : null}
      {state ? (
        <p role="status" className={state.level === "ok" ? "" : state.level === "error" ? "notice error" : "notice"}>
          <span className={`status ${state.level === "ok" ? "s-done" : state.level === "error" ? "s-failed" : "s-needs_review"}`}>
            {state.level === "ok" ? t("Rendben") : state.level === "error" ? t("Hiba") : t("Figyelem")}
          </span>{" "}{state.text}
        </p>
      ) : null}
      <p className="muted small">
        {t("A külső programcsomagok ismert sebezhetőségeit a napi mentés hetente ellenőrzi; kézzel:")}{" "}
        <span className="mono">python -m jav.cli deps-audit</span>
      </p>
    </section>
  );
}
