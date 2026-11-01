import { useEffect, useState } from "react";
import { api, type PdfProtection } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { tmap } from "../../labels";

// 265 (code review UI-03): the panel's texts are in the shared dictionaries (until then a dictionary of its own)
const states: Record<PdfProtection["state"], string> = tmap({
  protected: "Protected", unprotected: "Memory limit unavailable", unknown: "Unknown", stale: "Stale",
});
const reasons: Record<string, string> = tmap({
  not_started: "The reader has not started yet.", helper_stopped: "The helper has stopped.",
  windows_job_unavailable: "Windows could not apply the memory limit.", isolation_disabled: "Isolation is disabled.",
  memory_limit_disabled: "The memory limit is disabled.", memory_limit_applied: "The operating system applied the memory limit.",
  worker_not_running: "The worker is not running.", worker_instance_ended: "The worker instance has ended.",
  report_expired: "The report has expired.", report_missing: "No current report is available.",
  report_invalid: "The report cannot be verified.", settings_changed: "Settings changed after the helper started.",
  starting: "The helper is starting.", memory_limit_unavailable: "The memory limit could not be established.",
});

export function PdfProtectionPanel() {
  useLocale();
  const result = useLoad("pdf-protection", api.health, 2000);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <section className="card wide" aria-label={t("PDF memory protection")}>
      <div className="card-head"><h3>{t("PDF memory protection")}</h3></div>
      {(["service", "worker"] as const).map((role) => {
        const report = result.data?.pdf_protection?.[role];
        const stamp = report?.observed_at;
        const expired = stamp != null && (now / 1000 - stamp > (report?.max_age_s ?? 10) || stamp > now / 1000 + 10);
        const state = result.error || expired ? "stale" : report?.state ?? "unknown";
        const safeState = state in states ? state : "unknown";
        const reason = result.error ? t("The status request failed.") : expired ? t("The report has expired.")
          : reasons[report?.reason ?? "report_missing"] ?? t("The report cannot be verified.");
        const label = role === "service" ? t("Service") : t("Worker");
        const effective = safeState === "protected" ? report?.effective_memory_mb : null;
        return (
          <div key={role} role="group" aria-label={label}>
            <h4>{label}</h4>
            <p><span className={`status ${safeState === "protected" ? "s-done" : "s-review"}`}>
              {states[safeState]}</span>{" "}{reason}</p>
            <p className="muted small">
              {t("Configured limit")}: {report?.configured ? `${report.configured.memory_mb} MB` : t("Unknown")}
              {" · "}{t("Effective limit")}: {effective != null ? `${effective} MB` : t("Not established")}
              {" · "}{t("Strict mode")}: {report?.configured ? t(report.configured.require_memory_limit ? "On" : "Off") : t("Unknown")}
            </p>
          </div>
        );
      })}
      <p className="muted small">{t("Strict mode refuses PDF reading without a memory limit. It is off by default.")}</p>
    </section>
  );
}
