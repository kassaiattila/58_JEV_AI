// 075: the result of the regular dependency audit on the System page — when it last ran, how
// many known vulnerabilities it found in the pinned Python and UI packages, and a warning when it is missing, stale or
// incomplete, and (158) when the Python runtime is behind the latest patch of its line. The audit runs from the command
// line or with the daily backup (weekly); the service only reads it.
import { api, type DepsAuditInfo } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";

/** The audit state in one sentence and its warning level (shared by the card and the test). */
export function depsAuditState(info: DepsAuditInfo): { level: "ok" | "warn" | "error"; text: string } {
  const s = info.status;
  if (!s) return { level: "warn", text: t("The dependency audit has not run yet.") };
  const counts = { when: when(s.checked_at), n: s.finding_count, py: s.python?.packages ?? 0, ui: s.npm?.packages ?? 0 };
  if (s.finding_count > 0) return { level: "error", text: t("{{n}} known vulnerabilities in the packages ({{when}}).", counts) };
  if (s.errors.length) return { level: "warn", text: t("The last dependency audit is incomplete ({{when}}): {{error}}", { when: counts.when, error: s.errors.join("; ") }) };
  if (s.stale) return { level: "warn", text: t("The last dependency audit is more than {{days}} days old ({{when}}).", { days: info.max_age_days, when: counts.when }) };
  if (s.runtime_outdated && s.runtime) {  // 158: a newer patch of the running Python is out
    return { level: "warn", text: t("Python {{running}} is behind the latest patch of its line, {{latest}} ({{date}}).",
      { running: s.runtime.running, latest: s.runtime.latest ?? "", date: s.runtime.latest_date ?? "?" }) };
  }
  return { level: "ok", text: t("No known vulnerabilities: {{py}} Python and {{ui}} UI packages ({{when}}).", counts) };
}

export function DepsAuditPanel() {
  useLocale();
  const d = useLoad("deps-audit", api.depsAudit, 300000);
  const state = d.data ? depsAuditState(d.data) : null;
  return (
    <section className="card wide" aria-label={t("Dependency audit")}>
      <div className="card-head">
        <h3>{t("Dependency audit")}</h3>
      </div>
      {d.error ? <p className="notice error">{d.error.message}</p> : null}
      {state ? (
        <p role="status" className={state.level === "ok" ? "" : state.level === "error" ? "notice error" : "notice"}>
          <span className={`status ${state.level === "ok" ? "s-done" : state.level === "error" ? "s-failed" : "s-warn"}`}>
            {state.level === "ok" ? t("OK") : state.level === "error" ? t("Error") : t("Attention")}
          </span>{" "}{state.text}
        </p>
      ) : null}
      <p className="muted small">
        {t("The daily backup checks the third-party packages for known vulnerabilities once a week; to run it by hand:")}{" "}
        <span className="mono">python -m jav.cli deps-audit</span>
      </p>
    </section>
  );
}
