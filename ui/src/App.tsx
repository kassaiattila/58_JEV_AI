// The frame of the workspace (057, decision of 2026-09-28): two main parts — Work packages (the daily work) and
// Settings (mailboxes, work folders, users, appearance, language, system). The header shows the worker's status and
// the user's name.
import { useState } from "react";
import { api, setActor, USERS_EVENT } from "./api";
import { useActor, useEvent, useHash, useLoad } from "./hooks";
import { t, useLocale } from "./i18n";
import { LanguageSwitch } from "./components/LanguageSwitch";
import { Picker } from "./components/Picker";
import { parseRoute } from "./route";
import { Activity } from "./views/Activity";
import { LegacyResult } from "./views/LegacyResult";
import { RunDetail } from "./views/Runs";
import { Settings } from "./views/Settings";
import { Workpackages } from "./views/Workpackages";

// the label is the Hungarian source, translated at render time (058: the rail is wide enough for the label to fit
// without hyphenation)
const NAV = [
  { view: "workpackages", href: "#/workpackages", label: "Munkacsomagok", icon: <path d="M4 7h16M4 12h16M4 17h10" /> },
  { view: "settings", href: "#/settings", label: "Beállítások", icon: <path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1" /> },
] as const;

export function App() {
  useLocale(); // on a language change the whole tree re-renders (the working copy is kept)
  const route = parseRoute(useHash());
  // the run page and the old result addresses belong to Work packages
  const section = route.view === "settings" ? "settings" : "workpackages";
  return (
    <div className="shell">
      <a className="skip" href="#main">{t("Ugrás a tartalomra")}</a>
      <aside className="rail">
        <div className="brand" aria-hidden="true">JAV</div>
        <nav aria-label={t("Főmenü")}>
          {NAV.map((n) => (
            <a key={n.view} className="nav" href={n.href} aria-current={section === n.view ? "page" : undefined}>
              <svg viewBox="0 0 24 24" aria-hidden="true">{n.icon}</svg>
              {t(n.label)}
            </a>
          ))}
        </nav>
      </aside>
      <div className="main-col">
        <header className="top">
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <WorkerBadge />
            <LanguageSwitch />
          </div>
          <ActorField />
        </header>
        <main id="main" className="main" tabIndex={-1}>
          {route.view === "workpackages" ? <Workpackages route={route} /> : null}
          {route.view === "run" ? <RunDetail runId={route.runId} /> : null}
          {route.view === "settings" ? <Settings section={route.section} /> : null}
          {route.view === "legacy-result" ? <LegacyResult runId={route.runId} table={route.table} /> : null}
          {route.view === "activity" ? <Activity day={route.day} /> : null}
        </main>
      </div>
    </div>
  );
}

function WorkerBadge() {
  const w = useLoad("worker", api.worker, 5000);
  if (w.error) return <span className="pill error-pill" role="status">{t("A helyi szolgáltatás nem érhető el")}</span>;
  if (!w.data) return <span className="pill">…</span>;
  const waiting = (w.data.jobs.queued ?? 0) + (w.data.jobs.claimed ?? 0);
  return (
    <span className={`pill ${w.data.running ? "" : "warn-pill"}`} role="status">
      {w.data.running ? t("Feldolgozó fut") : t("Feldolgozó nem fut")}{waiting ? ` · ${t("{{n}} tétel vár", { n: waiting })}` : ""}
    </span>
  );
}

/** Who is working? (057, 061 decision: active user). If the Settings › Users list is not empty, the name can only be
 *  chosen from it, and it is required before making changes (the local service rejects a name not on the list). With an
 *  empty list it can be typed freely (first setup), with a link to setting up the list. With a selected name:
 *  „Mai munkám” (My work today). */
function ActorField() {
  const users = useLoad("users", api.users);
  useEvent(USERS_EVENT, users.reload);
  const actor = useActor();
  const [name, setName] = useState(actor);
  const list = users.data?.users ?? [];
  if (!users.data) return <div className="actor" />;
  if (list.length) {
    const known = list.find((u) => u.toLocaleLowerCase() === actor.toLocaleLowerCase()) ?? null;
    return (
      <div className="actor">
        <Picker label={t("Ki dolgozik?")} value={known} placeholder={t("Válaszd ki a neved")} compact className={known ? "" : "needs-actor"}
          options={list.map((u) => ({ value: u, label: u }))} onChange={(v) => setActor(v)} />
        {known ? <a className="small" href="#/activity">{t("Mai munkám")}</a>
          : <span className="small warn-text" role="status">{t("Módosítás előtt válaszd ki a neved.")}</span>}
      </div>
    );
  }
  const saved = Boolean(actor) && actor === name.trim();
  return (
    <form className="actor" onSubmit={(e) => { e.preventDefault(); setActor(name); }}>
      <label htmlFor="actor">{t("Ki dolgozik?")}</label>
      <input id="actor" value={name} maxLength={64} placeholder={t("Neved (jóváhagyáshoz, javításhoz)")}
        onChange={(e) => setName(e.target.value)} onBlur={() => { if (name.trim()) setActor(name); }} />
      <button type="submit" className="secondary" disabled={saved || !name.trim()}>{saved ? t("Megjegyezve") : t("Mentés")}</button>
      {actor ? <a className="small" href="#/activity">{t("Mai munkám")}</a> : null}
      <a className="small" href="#/settings/users">{t("Felhasználók felvétele")}</a>
    </form>
  );
}
