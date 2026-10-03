import { useEffect, useState } from "react";
import { api, type PdfProtection } from "../../api";
import { useLoad } from "../../hooks";
import { useLocale } from "../../i18n";
import hu from "../../i18n/hu-pdf-protection.json";

type Message = keyof typeof hu;
const states: Record<PdfProtection["state"], Message> = {
  protected: "Protected", unprotected: "Memory limit unavailable", unknown: "Unknown", stale: "Stale",
};
const reasons: Record<string, Message> = {
  not_started: "The reader has not started yet.", helper_stopped: "The helper has stopped.",
  windows_job_unavailable: "Windows could not apply the memory limit.", isolation_disabled: "Isolation is disabled.",
  memory_limit_disabled: "The memory limit is disabled.", memory_limit_applied: "The operating system applied the memory limit.",
  worker_not_running: "The worker is not running.", worker_instance_ended: "The worker instance has ended.",
  report_expired: "The report has expired.", report_missing: "No current report is available.",
  report_invalid: "The report cannot be verified.", settings_changed: "Settings changed after the helper started.",
  starting: "The helper is starting.", memory_limit_unavailable: "The memory limit could not be established.",
};

export function PdfProtectionPanel() {
  const locale = useLocale();
  const message = (source: Message) => locale === "hu" ? hu[source] : source;
  const result = useLoad("pdf-protection", api.health, 2000);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <section className="card wide" aria-label={message("PDF memory protection")}>
      <div className="card-head"><h3>{message("PDF memory protection")}</h3></div>
      {(["service", "worker"] as const).map((role) => {
        const report = result.data?.pdf_protection?.[role];
        const stamp = report?.observed_at;
        const expired = stamp != null && (now / 1000 - stamp > (report?.max_age_s ?? 10) || stamp > now / 1000 + 10);
        const state = result.error || expired ? "stale" : report?.state ?? "unknown";
        const safeState = state in states ? state : "unknown";
        const reason = result.error ? "The status request failed." : expired ? "The report has expired."
          : reasons[report?.reason ?? "report_missing"] ?? "The report cannot be verified.";
        const label = message(role === "service" ? "Service" : "Worker");
        const effective = safeState === "protected" ? report?.effective_memory_mb : null;
        return (
          <div key={role} role="group" aria-label={label}>
            <h4>{label}</h4>
            <p><span className={`status ${safeState === "protected" ? "s-done" : "s-review"}`}>
              {message(states[safeState])}</span>{" "}{message(reason)}</p>
            <p className="muted small">
              {message("Configured limit")}: {report?.configured ? `${report.configured.memory_mb} MB` : message("Unknown")}
              {" · "}{message("Effective limit")}: {effective != null ? `${effective} MB` : message("Not established")}
              {" · "}{message("Strict mode")}: {report?.configured ? message(report.configured.require_memory_limit ? "On" : "Off") : message("Unknown")}
            </p>
          </div>
        );
      })}
      <p className="muted small">{message("Strict mode refuses PDF reading without a memory limit. It is off by default.")}</p>
    </section>
  );
}
