// 071 S-verzió (070 terv 2.1, audit A08 / §1): a Rendszer oldalon látszik, melyik kód fut — a verzió és a commit,
// amellyel a szolgáltatás elindult. Ha a munkafában commitolatlan változás volt, vagy a commit nem ismert, azt is kiírja.
import { api, type Health } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";

/** A verzió egy sorban (a megjelenítés és a teszt közös logikája). */
export function versionLine(h: Health): string {
  return h.commit ? t("v{{version}} · commit {{commit}}", { version: h.version, commit: h.commit }) : `v${h.version}`;
}

/** Figyelmeztetés, ha a futó kód nem egy commit pontos állapota, vagy a commit nem ismert; különben null. */
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
