// The frame of the workspace (057, decision of 2026-09-28): two main parts — Work packages (the daily work) and
// Settings (mailboxes, work folders, users, appearance, language, system). The header shows the worker's status and
// the user's name.
import { useEffect, useState } from "react";
import { api, setActor, USERS_EVENT } from "./api";
import { useActor, useEvent, useHash, useLoad } from "./hooks";
import { t, useLocale } from "./i18n";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { LanguageSwitch } from "./components/LanguageSwitch";
import { lazyPage } from "./components/LazyPage";
import { Picker } from "./components/Picker";
import { UpdateBanner } from "./components/UpdateBanner";
import { parseRoute } from "./route";
import { RunDetail } from "./views/Runs";
import { Workpackages } from "./views/Workpackages";

// 195 (plan G-tidy R5): the pages away from the daily work load when they are first opened
const Activity = lazyPage(() => import("./views/Activity").then((m) => m.Activity));
const Waiting = lazyPage(() => import("./views/Waiting").then((m) => m.Waiting));
const LegacyResult = lazyPage(() => import("./views/LegacyResult").then((m) => m.LegacyResult));
const Settings = lazyPage(() => import("./views/Settings").then((m) => m.Settings));
const Workflows = lazyPage(() => import("./views/workflows/Workflows").then((m) => m.Workflows));
const CasePage = lazyPage(() => import("./views/CasePage").then((m) => m.CasePage));  // 231 (A6)
const CaseList = lazyPage(() => import("./views/CaseList").then((m) => m.CaseList));  // 231 (A7e)
const NewCase = lazyPage(() => import("./views/NewCase").then((m) => m.NewCase));  // 231 (U0)

// the label is the Hungarian source, translated at render time (058: the rail is wide enough for the label to fit
// without hyphenation)
const NAV = [
  { view: "workpackages", href: "#/workpackages", label: "Munkacsomagok", icon: <path d="M4 7h16M4 12h16M4 17h10" /> },
  // 146: the workflows (the work packages of one job, chained); an English source label, translated at render time
  { view: "workflows", href: "#/workflows", label: "Workflows", icon: <path d="M5 6h4v4H5zM15 14h4v4h-4zM9 8h4a2 2 0 0 1 2 2v4" /> },
  // 231 (A7e): the process packs' cases (an English source label, translated at render time)
  { view: "case-list", href: "#/cases", label: "Cases", icon: <path d="M4 8h16v11H4zM9 8V5h6v3M4 13h16" /> },
  { view: "settings", href: "#/settings", label: "Beállítások", icon: <path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1" /> },
] as const;

export function App() {
  const language = useLocale(); // on a language change the whole tree re-renders (the working copy is kept)
  // 167 (review 153 E): the browser tab's title follows the language too
  useEffect(() => { document.title = t("JAV workspace"); }, [language]);
  const hash = useHash();
  const route = parseRoute(hash);
  // the run page and the old result addresses belong to Work packages
  const section = route.view === "settings" ? "settings" : route.view === "workflows" ? "workflows"
    : route.view === "case-list" || route.view === "cases" ? "case-list" : "workpackages";
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
        <UpdateBanner />
        <header className="top">
          <div className="top-status">
            <WorkerBadge />
            <LanguageSwitch />
          </div>
          <ActorField />
        </header>
        <main id="main" className="main" tabIndex={-1}>
          {/* 167 (review 160 U-12): a view's error leaves the menu working; another address clears it */}
          <ErrorBoundary view resetKey={hash}>
            {route.view === "workpackages" ? <Workpackages route={route} /> : null}
            {route.view === "run" ? <RunDetail runId={route.runId} /> : null}
            {route.view === "workflows" ? <Workflows route={route} /> : null}
            {route.view === "cases" ? <CasePage caseId={route.caseId} tab={route.tab} /> : null}
            {route.view === "case-list" && !route.create ? <CaseList /> : null}
            {route.view === "case-list" && route.create ? <NewCase pack={route.pack} /> : null}
            {route.view === "settings" ? <Settings section={route.section} /> : null}
            {route.view === "legacy-result" ? <LegacyResult runId={route.runId} table={route.table} /> : null}
            {route.view === "activity" ? <Activity day={route.day} /> : null}
            {route.view === "waiting" ? <Waiting all={Boolean(route.all)} /> : null}
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

function WorkerBadge() {
  const w = useLoad("worker", api.worker, 5000);
  if (w.error) return <span className="pill error-pill" role="status">{t("A helyi szolgáltatás nem érhető el")}</span>;
  if (!w.data) return <span className="pill pending-pill">…</span>;
  const waiting = (w.data.jobs.queued ?? 0) + (w.data.jobs.claimed ?? 0);
  return (
    <span className={`pill ${w.data.running ? "" : "warn-pill"}`} role="status">
      {w.data.running ? t("Feldolgozó fut") : t("Feldolgozó nem fut")}{waiting ? ` · ${t("{{n}} tétel vár", { n: waiting })}` : ""}
    </span>
  );
}

/** 216: "Waiting for me" with the number of the person's open live tasks and anyone's (the list's default view); an
 *  attention count above zero, refreshed every 30 s. */
function WaitingLink({ actor }: { actor: string }) {
  const count = useLoad(`waiting:${actor}`, () => api.datasetQuery("waiting", { actor }, { limit: 1 }), 30000);
  const n = count.data?.total ?? null;
  return (
    <a className="small waiting-link" href="#/waiting">
      {t("Waiting for me")}
      {n === null ? null : <span className={n > 0 ? "count-alert" : "count-zero"}>{n}</span>}
    </a>
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
        {known ? <><WaitingLink actor={known} /><a className="small" href="#/activity">{t("Mai munkám")}</a></>
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
      {actor ? <><WaitingLink actor={actor} /><a className="small" href="#/activity">{t("Mai munkám")}</a></> : null}
      <a className="small" href="#/settings/users">{t("Felhasználók felvétele")}</a>
    </form>
  );
}
