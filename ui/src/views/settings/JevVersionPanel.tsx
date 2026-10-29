// 200 (the owner's decision of 2026-10-22): the JEV version on the System page — the system asks a pinned JEV version;
// the daily backup looks once a day where the provider's moving name points, and the card says when a newer version is
// out. A newer version is a notice: the pinned one keeps answering, and switching is a decision with a measurement. The
// service only reads the last look.
import { api, type JevVersionInfo } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";

const CONCRETE = /^jev-\d+\.\d+\.\d+$/;

/** The version state in one sentence and its warning level (shared by the card and the test). */
export function jevVersionState(info: JevVersionInfo): { level: "ok" | "warn"; text: string } {
  if (!CONCRETE.test(info.pinned)) {
    return { level: "warn", text: t("The model is not pinned: {{pinned}} follows the provider's latest version.", { pinned: info.pinned }) };
  }
  if (!info.latest || !info.checked_at) {
    return { level: "warn", text: t("Which JEV version is the latest has not been looked up yet; the daily backup does it.") };
  }
  const v = { pinned: info.pinned, latest: info.latest, when: when(info.checked_at), days: Math.floor(info.age_days ?? 0) };
  if (info.newer) {
    return { level: "warn", text: t("A newer JEV version is out: {{latest}} ({{when}}). The system keeps asking {{pinned}}; switching is a decision with a measurement.", v) };
  }
  if (info.stale) return { level: "warn", text: t("The latest JEV version was last looked up {{days}} days ago ({{when}}).", v) };
  return { level: "ok", text: t("The system asks {{pinned}}; it is the latest version too ({{when}}).", v) };
}

export function JevVersionPanel() {
  useLocale();
  const d = useLoad("jev-version", api.jevVersion, 300000);
  const state = d.data ? jevVersionState(d.data) : null;
  return (
    <section className="card wide" aria-label={t("JEV version")}>
      <div className="card-head">
        <h3>{t("JEV version")}</h3>
      </div>
      {d.error ? <p className="notice error">{d.error.message}</p> : null}
      {state ? (
        <p role="status" className={state.level === "ok" ? "" : "notice"}>
          <span className={`status ${state.level === "ok" ? "s-done" : "s-needs_review"}`}>
            {state.level === "ok" ? t("OK") : t("Attention")}
          </span>{" "}{state.text}
        </p>
      ) : null}
      <p className="muted small">
        {t("The daily backup looks once a day which version the provider's latest name points to; the system asks the pinned version only.")}
      </p>
    </section>
  );
}
