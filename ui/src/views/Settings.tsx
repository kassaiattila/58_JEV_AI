// Settings (057, decision of 2026-09-28): the things that rarely change, in one place — mailboxes, work folders, users,
// appearance, language and the system (worker, all runs); 063: the description of the recipes. Sub-items on the left,
// content on the right.
import { useState } from "react";
import { api, ApiError } from "../api";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import type { SettingsSection } from "../route";
import { Mailbox } from "./Mailbox";
import { BankFilesPanel } from "./BankFiles";
import { RecipesPanel } from "./RecipeInfo";
import { RunList } from "./Runs";
import { AppearancePanel } from "./settings/AppearancePanel";
import { BackupPanel } from "./settings/BackupPanel";
import { DepsAuditPanel } from "./settings/DepsAuditPanel";
import { EnginePanel } from "./settings/EnginePanel";
import { FoldersPanel } from "./settings/FoldersPanel";
import { LanguagePanel } from "./settings/LanguagePanel";
import { OutputTemplatesPanel } from "./settings/OutputTemplatesPanel";
import { PartiesPanel } from "./settings/PartiesPanel";
import { PriceListsPanel } from "./settings/PriceListsPanel";
import { UsersPanel } from "./settings/UsersPanel";
import { VersionPanel } from "./settings/VersionPanel";
import { PdfProtectionPanel } from "./settings/PdfProtectionPanel";
import { ConfirmButton } from "../components/ConfirmButton";
import { UncertainCallsPanel } from "./settings/UncertainCallsPanel";

// the labels stand here as Hungarian source; translation happens at render time (`t()`)
// 073: exported so a test can check that every label and hint has an English translation (the i18n checker only
// sees literal t("...") arguments, and "Receptek" slipped through; 080: "Receptek" became "Feldolgozás")
export const SETTINGS_SECTIONS: { key: SettingsSection; label: string; hint: string }[] = [
  { key: "mailboxes", label: "Postafiókok", hint: "Outlook-fiókok, ütemezett letöltés, letöltési napló" },
  { key: "folders", label: "Munkamappák", hint: "Figyelt mappák: az új iratokból magától lesz munkacsomag" },
  // 133: new labels have an English source (the Hungarian translation is in hu-native.json)
  { key: "parties", label: "Own parties", hint: "Whose money is reconciled: companies, associations and people, with their names, tax numbers and accounts" },
  { key: "recipes", label: "Feldolgozás", hint: "Hogyan dolgozza fel a rendszer az iratokat és a leveleket, mit jelentenek a beállítások, mennyibe kerülnek" },
  // 179 (plan 170 L4, DECISIONS 178): own Excel templates of the downloads
  { key: "outputs", label: "Output templates", hint: "Your own Excel and Word templates for the downloads: upload, check, preview and make active; the markers to write in them" },
  // 191 (plan F-quote-package B2): the seller's price lists a quote is priced from
  { key: "prices", label: "Price lists", hint: "The price lists quotes are priced from: upload, check and make active; the volume discounts, the currency and the VAT rate" },
  { key: "users", label: "Felhasználók", hint: "A „Ki dolgozik?” választéka" },
  { key: "appearance", label: "Megjelenés", hint: "The theme: light, dark or as the system is set" },
  { key: "language", label: "Nyelv", hint: "A felület nyelve: magyar vagy angol" },
  { key: "system", label: "Rendszer", hint: "A futó verzió, a feldolgozó állapota, az adattár mentése, minden futás" },
];

export function Settings({ section }: { section: SettingsSection }) {
  useLocale();
  const current = SETTINGS_SECTIONS.find((s) => s.key === section) ?? SETTINGS_SECTIONS[0];
  return (
    <>
      <PageHeader title={t("Beállítások")} summary={t(current.hint)} />
      <div className="settings-layout">
        <nav className="settings-nav" aria-label={t("Beállítások")}>
          {SETTINGS_SECTIONS.map((s) => (
            <a key={s.key} href={`#/settings/${s.key}`} aria-current={s.key === current.key ? "page" : undefined}>{t(s.label)}</a>
          ))}
        </nav>
        <div className="settings-body">
          <h2>{t(current.label)}</h2>
          {current.key === "mailboxes" ? <Mailbox variant="settings" /> : null}
          {current.key === "folders" ? <FoldersPanel /> : null}
          {current.key === "parties" ? <PartiesPanel /> : null}
          {current.key === "recipes" ? (
            <>
              <EnginePanel />
              <RecipesPanel />
              <h2>{t("Bank files the system reads")}</h2>
              <BankFilesPanel />
            </>
          ) : null}
          {current.key === "outputs" ? <OutputTemplatesPanel /> : null}
          {current.key === "prices" ? <PriceListsPanel /> : null}
          {current.key === "users" ? <UsersPanel /> : null}
          {current.key === "appearance" ? <AppearancePanel /> : null}
          {current.key === "language" ? <LanguagePanel /> : null}
          {current.key === "system" ? <SystemPanel /> : null}
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
            {" "}{t("Sorban: {{queued}} · folyamatban: {{claimed}} · kész: {{done}} · leállítva: {{cancelled}}", { queued: jobs.queued ?? 0, claimed: jobs.claimed ?? 0, done: jobs.done ?? 0, cancelled: jobs.cancelled ?? 0 })}
            {jobs.dead ? ` · ${t("feladva: {{n}}", { n: jobs.dead })}` : ""}
          </p>
        ) : null}
        <p className="muted small">{cmdBefore}<span className="mono">scripts\dev.ps1 start</span>{cmdAfter}</p>
        {msg ? <p role="status" className="notice">{msg}</p> : null}
      </section>
      <BackupPanel />
      <DepsAuditPanel />
      <UncertainCallsPanel />
      <section aria-label={t("Minden futás")}>
        <h3>{t("Minden futás")}</h3>
        <RunList />
      </section>
    </div>
  );
}
