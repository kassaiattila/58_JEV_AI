// 064 (decision of 2026-09-29): the status of the store backup on the Settings › System page — the time and result of
// the latest backup, the copy made to the second location (NAS), a warning if the latest successful backup is too old,
// and „Mentés most” (Back up now). The daily backup is started by Windows Task Scheduler (scripts\backup-task.ps1);
// a failure does not stay silent here.
import { useState } from "react";
import { api, ApiError, type BackupInfo } from "../../api";
import { Icon } from "../../components/Icon";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";

/** The backup status in one sentence and the warning level (logic shared by the display and the test). */
export function backupState(info: BackupInfo, now: Date = new Date()): { level: "ok" | "warn" | "error"; text: string } {
  const s = info.status;
  if (!s) return { level: "warn", text: t("No backup has been made yet.") };
  if (!s.ok) return { level: "error", text: t("The last backup failed ({{when}}): {{error}}", { when: when(s.created_at), error: s.error ?? "" }) };
  const ageH = (now.getTime() - new Date(s.created_at).getTime()) / 3_600_000;
  const maxAge = info.config.max_age_hours ?? 36;
  if (ageH > maxAge) return { level: "warn", text: t("The last successful backup was made {{hours}} hours ago; the daily backup is probably not running.", { hours: Math.floor(ageH) }) };
  if (s.copy && !s.copy.ok) return { level: "warn", text: t("The local backup is fine ({{when}}), but the copy to the second location failed: {{error}}", { when: when(s.created_at), error: s.copy.error ?? "" }) };
  return { level: "ok", text: t("Last backup: {{when}}", { when: when(s.created_at) }) };
}

/** 070: the internal working documents (handoffs, plans, reports…) in the backup — they are not in git, so the backup
 *  is the only second copy. */
export function docsLine(info: BackupInfo): string {
  const docs = info.status?.files?.find((f) => f.file === "internal-docs.zip");
  if (docs) return t("{{n}} files ({{mb}} MB)", { n: docs.entries ?? 0, mb: (docs.bytes / 1e6).toFixed(1) });
  return info.config.with_docs ? t("not in the latest backup") : t("off");
}

export function BackupPanel() {
  useLocale();
  const b = useLoad("backup", api.backupStatus, 60000);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);

  async function now() {
    setBusy(true);
    setMsg(null);
    try {
      const m = await api.backupNow();
      setMsg({ error: !m.ok || (m.copy != null && !m.copy.ok), text: t("Backup done: {{dir}}", { dir: m.dir }) });
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
    } finally {
      setBusy(false);
      b.reload();
    }
  }

  const state = b.data ? backupState(b.data) : null;
  const s = b.data?.status;
  const size = s?.files?.reduce((sum, f) => sum + f.bytes, 0) ?? 0;
  const conf = b.data?.config;
  return (
    <section className="card wide" aria-label={t("Database backup")}>
      <div className="card-head">
        <h3>{t("Database backup")}</h3>
        <button type="button" className="secondary small-btn" disabled={busy} onClick={() => void now()}>
          <Icon name="download" />{busy ? t("Backing up…") : t("Back up now")}
        </button>
      </div>
      {b.error ? <p className="notice error">{b.error.message}</p> : null}
      {state ? (
        <p role="status" className={state.level === "ok" ? "" : state.level === "error" ? "notice error" : "notice"}>
          <span className={`status ${state.level === "ok" ? "s-done" : state.level === "error" ? "s-failed" : "s-warn"}`}>
            {state.level === "ok" ? t("OK") : state.level === "error" ? t("Error") : t("Attention")}
          </span>{" "}{state.text}
        </p>
      ) : null}
      {s?.ok ? (
        <dl className="kv">
          <dt>{t("Local backup")}</dt><dd className="mono small">{s.dir} ({(size / 1e6).toFixed(1)} MB)</dd>
          <dt>{t("Copy")}</dt>
          <dd className="mono small">{s.copy ? `${s.copy.dir} — ${s.copy.ok ? t("verified") : t("did not succeed")}` : t("not configured")}</dd>
          <dt>{t("Internal documents")}</dt><dd className="small">{b.data ? docsLine(b.data) : ""}</dd>
        </dl>
      ) : null}
      {conf ? (
        <p className="muted small">
          {t("Daily backup at {{time}} (Windows Task Scheduler); the latest {{keep}} backups are kept locally and at the second location.", { time: conf.schedule ?? "", keep: conf.keep ?? "" })}
        </p>
      ) : null}
      {msg ? <p role="status" className={msg.error ? "notice error" : "notice"}>{msg.text}</p> : null}
    </section>
  );
}
