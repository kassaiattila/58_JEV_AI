// Settings (057, decision of 2026-09-28): the things that rarely change, in one place — mailboxes, work folders, users,
// appearance, language and the system (worker, all runs); 063: the description of the recipes; 218: the rules, read only.
// Sub-items on the left, content on the right. 231 (C3e): a domain's section, or what it adds to a shared one, comes
// from the sections' registry (`logic/settingsSections.ts`). 231 (U3e): the menu in three groups.
import { Fragment, useState } from "react";
import { api, ApiError } from "../api";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import type { SettingsSection } from "../route";
import { SETTINGS_GROUPS, settingsParts, settingsSections } from "../logic/settingsSections";
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
import { ProcessNav, ProcessSettingsPanel } from "./settings/ProcessSettingsPanel";
import { ProductsPanel } from "./settings/ProductsPanel";
import { RulesPanel } from "./settings/RulesPanel";
import { UsersPanel } from "./settings/UsersPanel";
import { VersionPanel } from "./settings/VersionPanel";
import { PdfProtectionPanel } from "./settings/PdfProtectionPanel";
import { ConfirmButton } from "../components/ConfirmButton";
import { UncertainCallsPanel } from "./settings/UncertainCallsPanel";

export function Settings({ section, item, tab }: { section: SettingsSection; item?: string; tab?: string }) {
  useLocale();
  // 231 (C3e): the shared sections and the domains' own (`logic/settingsSections.ts`), in their order
  const sections = settingsSections();
  const current = sections.find((s) => s.key === section) ?? sections[0];
  const Own = current.Panel;
  return (
    <>
      <PageHeader title={t("Beállítások")} summary={t(current.hint)} />
      <div className="settings-layout">
        <nav className="settings-nav" aria-label={t("Beállítások")}>
          {/* 231 (U3e; the owner's decisions of 2026-10-28): the processes, the shared library and the system */}
          {SETTINGS_GROUPS.map((g) => (
            <div key={g.key} role="group" aria-labelledby={`settings-group-${g.key}`} className="settings-group">
              <span id={`settings-group-${g.key}`} className="settings-group-name">{t(g.label)}</span>
              {sections.filter((s) => s.group === g.key).map((s) => (
                <Fragment key={s.key}>
                  <a href={`#/settings/${s.key}`} aria-current={s.key === current.key && !item ? "page" : undefined}>{t(s.navLabel ?? s.label)}</a>
                  {/* 231 (U3a; the owner's decision of 2026-10-28): each process its own menu item and address */}
                  {s.key === "processes" && current.key === "processes" ? <ProcessNav current={item} /> : null}
                </Fragment>
              ))}
            </div>
          ))}
        </nav>
        <div className="settings-body">
          <h2>{t(current.label)}</h2>
          {Own ? <Own /> : null}
          {current.key === "folders" ? <FoldersPanel /> : null}
          {current.key === "partners" ? <PartnersPanel /> : null}
          {current.key === "processes" ? <ProcessSettingsPanel pack={item} tab={tab} /> : null}
          {current.key === "products" ? <ProductsPanel key={item ?? ""} initial={item} /> : null}
          {current.key === "recipes" ? (
            <>
              <EnginePanel />
              <RecipesPanel />
            </>
          ) : null}
          {current.key === "rules" ? <RulesPanel /> : null}
          {current.key === "outputs" ? <OutputTemplatesPanel /> : null}
          {current.key === "letters" ? <LetterFramesPanel /> : null}
          {current.key === "users" ? <UsersPanel /> : null}
          {current.key === "appearance" ? <AppearancePanel /> : null}
          {current.key === "language" ? <LanguagePanel /> : null}
          {current.key === "system" ? <SystemPanel /> : null}
          {settingsParts(current.key).map(({ title, Panel }) => (  // 231 (C3e): what the domains add to a shared section
            <Fragment key={title}><h2>{t(title)}</h2><Panel /></Fragment>
          ))}
        </div>
      </div>
    </>
  );
}

function SystemPanel() {
  useLocale();
  const w = useLoad("worker", api.worker, 5000);
  const [msg, setMsg] = useState<string | null>(null);
  async function stop() {
    try {
      await api.workerStop();
      setMsg(t("Leállítás kérve: a feldolgozó a folyamatban lévő tétel után áll le."));
      w.reload();
    } catch (e) {
      setMsg((e as ApiError).message);
    }
  }
  const jobs = w.data?.jobs ?? {};
  const [cmdBefore, cmdAfter] = t("A feldolgozót a {{cmd}} indítja; a lap bezárása nem állítja le a futásokat.").split("{{cmd}}");
  return (
    <div className="stage-stack">
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
      <section className="card wide" aria-label={t("Feldolgozó")}>
        <div className="card-head">
          <h3>{t("Feldolgozó")}</h3>
          {w.data?.running ? <ConfirmButton className="secondary small-btn" onConfirm={() => void stop()}><Icon name="stop" />{t("Leállítás")}</ConfirmButton> : null}
        </div>
        {w.error ? <p className="notice error">{w.error.message}</p> : null}
        {w.data ? (
          <p>
            <span className={`status ${w.data.running ? "s-done" : "s-failed"}`}>{w.data.running ? t("Fut") : t("Nem fut")}</span>
            {/* 231 (E1): how many of the allowed workers run, when more than one may */}
            {(w.data.slots ?? 1) > 1 ? <> <span className="tnum">{t("{{n}} of {{slots}} workers", { n: w.data.workers ?? 0, slots: w.data.slots ?? 1 })}</span> ·</> : null}
            {" "}{t("Sorban: {{queued}} · folyamatban: {{claimed}} · kész: {{done}} · leállítva: {{cancelled}}", { queued: jobs.queued ?? 0, claimed: jobs.claimed ?? 0, done: jobs.done ?? 0, cancelled: jobs.cancelled ?? 0 })}
            {jobs.dead ? ` · ${t("feladva: {{n}}", { n: jobs.dead })}` : ""}
          </p>
        ) : null}
        <p className="muted small">{cmdBefore}<span className="mono">scripts\dev.ps1 start</span>{cmdAfter}</p>
        {msg ? <p role="status" className="notice">{msg}</p> : null}
      </section>
      <BackupPanel />
      <DepsAuditPanel />
      <JevVersionPanel />
      <UncertainCallsPanel />
      <section aria-label={t("Minden futás")}>
        <h3>{t("Minden futás")}</h3>
        <RunList />
      </section>
    </div>
  );
}
