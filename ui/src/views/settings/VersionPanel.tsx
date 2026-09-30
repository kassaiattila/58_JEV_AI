// 071 (security audit A08): the System page shows which code is running — the version and the commit
// the local service was started from. If the working tree had uncommitted changes, or the commit is unknown, it says so
// too.
import { api, type Health } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";

/** The version on one line (logic shared by the display and the test). */
export function versionLine(h: Health): string {
  return h.commit ? t("v{{version}} · commit {{commit}}", { version: h.version, commit: h.commit }) : `v${h.version}`;
}

/** A warning if the running code is not the exact state of a commit, or the commit is unknown; otherwise null. */
export function versionWarning(h: Health): string | null {
  if (!h.commit) return t("A commit nem ismert (a szolgáltatás git nélkül indult).");
  if (h.dirty) return t("A futó kód commitolatlan változást tartalmaz.");
  return null;
}

export function VersionPanel() {
  useLocale();
  const h = useLoad("health", api.health, 60000);
  const warning = h.data ? versionWarning(h.data) : null;
  return (
    <section className="card wide" aria-label={t("Verzió")}>
      <div className="card-head">
        <h3>{t("Verzió")}</h3>
      </div>
      {h.error ? <p className="notice error">{h.error.message}</p> : null}
      {h.data ? (
        <>
          <p><span className="mono">{versionLine(h.data)}</span></p>
          <p className="muted small">{t("A szolgáltatás {{when}} óta fut; új kód az újraindítása után él.", { when: when(h.data.started_at) })}</p>
          {warning ? <p role="status" className="notice">{warning}</p> : null}
        </>
      ) : null}
    </section>
  );
}
