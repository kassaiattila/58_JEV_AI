// Settings (057, decision of 2026-09-28): the things that rarely change, in one place — mailboxes, work folders, users,
// appearance, language and the system (worker, all runs); 063: the description of the recipes; 218: the rules, read only.
// Sub-items on the left, content on the right. 231 (C3e): a domain's section, or what it adds to a shared one, comes
// from the sections' registry (`logic/settingsSections.ts`). 231 (U3e): the menu in three groups. 263 (plan E, E1; the
// owner's decisions of 2026-10-30): a table of contents beside one page - the groups, their sections, a section's lists
// and the things in them as one tree with a search (`components/Navigator.tsx`, `settings/settingsTree.tsx`); the page
// is a section's or a list's table, or one thing's sheet, under a header that stays in view with the way to it, its
// title and its main action at the right end.
import { Fragment, useState } from "react";
import { api, ApiError } from "../api";
import { Icon } from "../components/Icon";
import { findNode, Navigator, pathTo, type NavNode } from "../components/Navigator";
import { SidePanel } from "../components/SidePanel";
import { PageActionsSlot } from "../components/PageActions";
import { PageHeader } from "../components/PageHeader";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import type { SettingsSection } from "../route";
import { SETTINGS_GROUPS, settingsParts, settingsSections } from "../logic/settingsSections";
import { groupKey, isThing, sectionKey, selectedKey, SettingsTitleSlot, useSettingsTree } from "./settings/settingsTree";
import { RecipesPanel } from "./RecipeInfo";
import { RunList } from "./Runs";
import { AppearancePanel } from "./settings/AppearancePanel";
import { BackupPanel } from "./settings/BackupPanel";
import { DepsAuditPanel } from "./settings/DepsAuditPanel";
import { JevVersionPanel } from "./settings/JevVersionPanel";
import { EnginePanel } from "./settings/EnginePanel";
import { FoldersPanel } from "./settings/FoldersPanel";
import { LanguagePanel } from "./settings/LanguagePanel";
import { LetterFramesPanel } from "./settings/LetterFramesPanel";
import { OutputTemplatesPanel } from "./settings/OutputTemplatesPanel";
import { PartnersPanel } from "./settings/PartnersPanel";
import { ProcessSettingsPanel } from "./settings/ProcessSettingsPanel";
import { ProductsPanel } from "./settings/ProductsPanel";
import { RulesPanel } from "./settings/RulesPanel";
import { UsersPanel } from "./settings/UsersPanel";
import { VersionPanel } from "./settings/VersionPanel";
import { PdfProtectionPanel } from "./settings/PdfProtectionPanel";
import { ConfirmButton } from "../components/ConfirmButton";
import { UncertainCallsPanel } from "./settings/UncertainCallsPanel";

/** The branches a person opened or closed, kept per browser (every group open at first). */
const OPEN_KEY = "jav.settings.open";
// 263 (F4): the sections whose page opens with its own fuller introduction - their title row adds no summary
const OWN_INTRO = new Set(["outputs", "letters", "prices", "rules", "recipes", "users", "folders"]);
function loadOpen(): Set<string> {
  try {
    const saved = JSON.parse(localStorage.getItem(OPEN_KEY) ?? "null") as string[] | null;
    if (Array.isArray(saved)) return new Set(saved);
  } catch { /* no storage or a broken value: the default */ }
  return new Set(SETTINGS_GROUPS.map((g) => groupKey(g.key)));
}
function saveOpen(open: Set<string>) {
  try { localStorage.setItem(OPEN_KEY, JSON.stringify([...open])); } catch { /* private window: for the session only */ }
}

export function Settings({ section, item, tab, open: part }: { section: SettingsSection; item?: string; tab?: string; open?: string }) {
  useLocale();
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  const [open, setOpen] = useState<Set<string>>(loadOpen);
  const [thingTitle, setThingTitle] = useState<string | null>(null);
  // 231 (C3e): the shared sections and the domains' own (`logic/settingsSections.ts`), in their order
  const sections = settingsSections();
  const current = sections.find((s) => s.key === section) ?? sections[0];
  const chosen = selectedKey(current.key, item);
  const thing = isThing(current.key, item, tab);
  const tree = useSettingsTree((key) => key === current.key || open.has(sectionKey(key)));
  const toggle = (key: string) => setOpen((was) => {
    const next = new Set(was);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    saveOpen(next);
    return next;
  });
  // the header: the way to the chosen node (its group, its section) and, on a thing's page, the node itself; the title
  // is the thing's (its page names it) or the node's; a section's own page says what the section is for
  const way = pathTo(tree, chosen).map((k) => findNode(tree, k)).filter((n): n is NavNode => n !== null);
  const node = findNode(tree, chosen);
  const crumbs = [{ label: t("Settings"), href: "#/settings" }, ...way.map((n) => ({ label: n.label, href: n.href })),
    ...(thing && node ? [{ label: node.label, href: node.href }] : [])];
  const Own = current.Panel;
  return (
    <div className="settings-layout">
      <SidePanel id="settings" label={t("Contents")}>
        <Navigator nodes={tree} selected={chosen} open={open} onToggle={toggle} label={t("Settings")} />
      </SidePanel>
      <div className="settings-page">
        <PageHeader crumbs={crumbs} title={(thing ? thingTitle : null) ?? node?.label ?? t(current.label)} compact
          summary={!thing && chosen === sectionKey(current.key) && !OWN_INTRO.has(current.key) ? t(current.hint) : undefined} actionsSlot={setSlot} />
        <SettingsTitleSlot value={setThingTitle}>
        <PageActionsSlot value={slot}>
          <div className="settings-body">
            {Own ? <Own item={item} tab={tab} open={part} /> : null}
            {current.key === "folders" ? <FoldersPanel /> : null}
            {current.key === "partners" ? <PartnersPanel item={item} /> : null}
            {current.key === "processes" ? <ProcessSettingsPanel pack={item} tab={tab} /> : null}
            {current.key === "products" ? <ProductsPanel list={item} ident={tab} open={part} /> : null}
            {current.key === "recipes" ? (
              <>
                <EnginePanel />
                <RecipesPanel />
              </>
            ) : null}
            {current.key === "rules" ? <RulesPanel item={item} /> : null}
            {current.key === "outputs" ? <OutputTemplatesPanel item={item} tab={tab} /> : null}
            {current.key === "letters" ? <LetterFramesPanel item={item} tab={tab} /> : null}
            {current.key === "users" ? <UsersPanel /> : null}
            {current.key === "appearance" ? <AppearancePanel /> : null}
            {current.key === "language" ? <LanguagePanel /> : null}
            {current.key === "system" ? <SystemPanel /> : null}
            {settingsParts(current.key).map(({ title, Panel }) => (  // 231 (C3e): what the domains add to a shared section
              <Fragment key={title}><h2>{t(title)}</h2><Panel /></Fragment>
            ))}
          </div>
        </PageActionsSlot>
        </SettingsTitleSlot>
      </div>
    </div>
  );
}

function SystemPanel() {
  useLocale();
  const w = useLoad("worker", api.worker, 5000);
  const [msg, setMsg] = useState<string | null>(null);
  async function stop() {
    try {
      await api.workerStop();
      setMsg(t("Stop requested: the worker stops after the item in progress."));
      w.reload();
    } catch (e) {
      setMsg((e as ApiError).message);
    }
  }
  const jobs = w.data?.jobs ?? {};
  const [cmdBefore, cmdAfter] = t("The worker is started by {{cmd}}; closing the page does not stop the runs.").split("{{cmd}}");
  return (
    <div className="stage-stack">
      {/* 263 (F4): a person's to-do first - the paid calls whose outcome waits to be settled */}
      <UncertainCallsPanel when="any" />
      {/* 231 (U2a; the owner's decision of 2026-10-28: one work list, the cases): the lists away from the daily work */}
      <section className="card wide" aria-label={t("Earlier work")}>
        <h3>{t("Earlier work")}</h3>
        <p className="small">{t("The daily work is under Cases; these lists are for finding earlier work.")}</p>
        <p className="button-row">
          <a className="button secondary" href="#/workpackages">{t("All document batches")}</a>
          <a className="button secondary" href="#/workflows">{t("Earlier workflows")}</a>
        </p>
      </section>
      <VersionPanel />
      <PdfProtectionPanel />
      <section className="card wide" aria-label={t("Worker")}>
        <div className="card-head">
          <h3>{t("Worker")}</h3>
          {w.data?.running ? <ConfirmButton className="secondary small-btn" onConfirm={() => void stop()}><Icon name="stop" />{t("Stop")}</ConfirmButton> : null}
        </div>
        {w.error ? <p className="notice error">{w.error.message}</p> : null}
        {w.data ? (
          <p>
            <span className={`status ${w.data.running ? "s-done" : "s-failed"}`}>{w.data.running ? t("Running") : t("Not running")}</span>
            {/* 231 (E1): how many of the allowed workers run, when more than one may */}
            {(w.data.slots ?? 1) > 1 ? <> <span className="tnum">{t("{{n}} of {{slots}} workers", { n: w.data.workers ?? 0, slots: w.data.slots ?? 1 })}</span> ·</> : null}
            {" "}{t("Queued: {{queued}} · in progress: {{claimed}} · done: {{done}} · stopped: {{cancelled}}", { queued: jobs.queued ?? 0, claimed: jobs.claimed ?? 0, done: jobs.done ?? 0, cancelled: jobs.cancelled ?? 0 })}
            {jobs.dead ? ` · ${t("given up: {{n}}", { n: jobs.dead })}` : ""}
          </p>
        ) : null}
        <p className="muted small">{cmdBefore}<span className="mono">scripts\dev.ps1 start</span>{cmdAfter}</p>
        {msg ? <p role="status" className="notice">{msg}</p> : null}
      </section>
      <BackupPanel />
      <DepsAuditPanel />
      <JevVersionPanel />
      <UncertainCallsPanel when="none" />
      <section aria-label={t("All runs")}>
        <h3>{t("All runs")}</h3>
        <RunList />
      </section>
    </div>
  );
}
