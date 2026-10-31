// The frame of the workspace (057, decision of 2026-09-28): two main parts — the daily work and Settings (mailboxes,
// work folders, users, appearance, language, system). 231 (U2a; the owner's decision of 2026-10-28: one work list) the
// daily work is the Cases: a document batch and a run open under their case; the list of every batch and the chains
// are reached from Settings › System. The header shows the worker's status and the user's name. 263 (plan E, E1; the
// owner's decision of 2026-10-30): the two main parts are in the header's left end beside the brand - the dark side rail
// that held only them is gone, so the work has the whole width.
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
  // 231 (A7e): the process packs' cases (an English source label, translated at render time); (U2a) the one work list
  { view: "case-list", href: "#/cases", label: "Cases" },
  { view: "settings", href: "#/settings", label: "Settings" },
] as const;

export function App() {
  const language = useLocale(); // on a language change the whole tree re-renders (the working copy is kept)
  // 167 (review 153 E): the browser tab's title follows the language too
  useEffect(() => { document.title = t("JAV workspace"); }, [language]);
  const hash = useHash();
  const route = parseRoute(hash);
  // 263 (E2; one case, one track): a case's page in one place whether its address names a part of its track or one of
  // its batches, so moving between them keeps the page
  const casePage = route.view === "cases" ? { caseId: route.caseId, tab: route.tab, sub: route.sub, of: route.of }
    : route.view === "workpackages" && route.wpId && route.inCase ? { caseId: route.inCase, batch: { wpId: route.wpId, route } } : null;
  // U2a: the list of every batch belongs to Settings › System; a batch, a run, a chain and an old result address to
  // the Cases (the work they are part of)
  const section = route.view === "settings" || (route.view === "workpackages" && !route.wpId) ? "settings" : "case-list";
  return (
    <div className="shell">
      <a className="skip" href="#main">{t("Skip to content")}</a>
      <div className="main-col">
        <UpdateBanner />
        <header className="top">
          <div className="top-nav">
            <div className="brand" aria-hidden="true">JAV</div>
            <nav aria-label={t("Main menu")} className="main-nav">
              {NAV.map((n) => (
                <a key={n.view} className="nav" href={n.href} aria-current={section === n.view ? "page" : undefined}>{t(n.label)}</a>
              ))}
            </nav>
          </div>
          <div className="top-right">
            <div className="top-status">
              <WorkerBadge />
              <LanguageSwitch />
            </div>
            <ActorField />
          </div>
        </header>
        <main id="main" className="main" tabIndex={-1}>
          {/* 167 (review 160 U-12): a view's error leaves the menu working; another address clears it */}
          <ErrorBoundary view resetKey={hash}>
            {route.view === "workpackages" && !casePage ? <Workpackages route={route} /> : null}
            {route.view === "run" ? <RunDetail runId={route.runId} /> : null}
            {route.view === "workflows" ? <Workflows route={route} /> : null}
            {casePage ? <CasePage {...casePage} /> : null}
            {route.view === "case-list" && !route.create ? <CaseList /> : null}
            {route.view === "case-list" && route.create ? <NewCase pack={route.pack} after={route.after} /> : null}
            {route.view === "settings" ? <Settings section={route.section} item={route.item} tab={route.tab} open={route.open} /> : null}
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
  if (w.error) return <span className="pill error-pill" role="status">{t("The local service is not reachable")}</span>;
  if (!w.data) return <span className="pill pending-pill">…</span>;
  const waiting = (w.data.jobs.queued ?? 0) + (w.data.jobs.claimed ?? 0);
  return (
    <span className={`pill ${w.data.running ? "" : "warn-pill"}`} role="status">
      {w.data.running ? t("Worker running") : t("Worker not running")}{waiting ? ` · ${t("{{n}} items waiting", { n: waiting })}` : ""}
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
        <Picker label={t("Who is working?")} value={known} placeholder={t("Choose your name")} compact className={known ? "" : "needs-actor"}
          options={list.map((u) => ({ value: u, label: u }))} onChange={(v) => setActor(v)} />
        {known ? <><WaitingLink actor={known} /><a className="small" href="#/activity">{t("My work today")}</a></>
          : <span className="small warn-text" role="status">{t("Select your name before making changes.")}</span>}
      </div>
    );
  }
  const saved = Boolean(actor) && actor === name.trim();
  return (
    <form className="actor" onSubmit={(e) => { e.preventDefault(); setActor(name); }}>
      <label htmlFor="actor">{t("Who is working?")}</label>
      <input id="actor" value={name} maxLength={64} placeholder={t("Your name (for approvals and corrections)")}
        onChange={(e) => setName(e.target.value)} onBlur={() => { if (name.trim()) setActor(name); }} />
      <button type="submit" className="secondary" disabled={saved || !name.trim()}>{saved ? t("Remembered") : t("Save")}</button>
      {actor ? <><WaitingLink actor={actor} /><a className="small" href="#/activity">{t("My work today")}</a></> : null}
      <a className="small" href="#/settings/users">{t("Add users")}</a>
    </form>
  );
}
