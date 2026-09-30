// Beállítások (057, döntés 2026-09-28): a ritkán változó dolgok egy helyen — postafiókok, munkamappák, felhasználók,
// megjelenés, nyelv és a rendszer (feldolgozó, minden futás); 063: a receptek leírása. Balra az alpontok, jobbra a tartalom.
import { useState } from "react";
import { api, ApiError } from "../api";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import type { SettingsSection } from "../route";
import { Mailbox } from "./Mailbox";
import { RecipesPanel } from "./RecipeInfo";
import { RunList } from "./Runs";
import { AppearancePanel } from "./settings/AppearancePanel";
import { BackupPanel } from "./settings/BackupPanel";
import { FoldersPanel } from "./settings/FoldersPanel";
import { LanguagePanel } from "./settings/LanguagePanel";
import { UsersPanel } from "./settings/UsersPanel";
import { VersionPanel } from "./settings/VersionPanel";
import { ConfirmButton } from "../components/ConfirmButton";

// a feliratok magyar forrásként állnak itt; a fordítás a kirajzoláskor történik (`t()`)
const SECTIONS: { key: SettingsSection; label: string; hint: string }[] = [
  { key: "mailboxes", label: "Postafiókok", hint: "Outlook-fiókok, ütemezett letöltés, letöltési napló" },
  { key: "folders", label: "Munkamappák", hint: "Figyelt mappák: az új iratokból magától lesz munkacsomag" },
  { key: "recipes", label: "Receptek", hint: "Mit csinálnak a receptek, mit jelentenek a beállításaik, mennyibe kerülnek" },
  { key: "users", label: "Felhasználók", hint: "A „Ki dolgozik?” választéka" },
  { key: "appearance", label: "Megjelenés", hint: "Téma és sűrűség" },
  { key: "language", label: "Nyelv", hint: "A felület nyelve: magyar vagy angol" },
  { key: "system", label: "Rendszer", hint: "A futó verzió, a feldolgozó állapota, az adattár mentése, minden futás" },
];

export function Settings({ section }: { section: SettingsSection }) {
  useLocale();
  const current = SECTIONS.find((s) => s.key === section) ?? SECTIONS[0];
  return (
    <>
      <PageHeader title={t("Beállítások")} summary={t(current.hint)} />
      <div className="settings-layout">
        <nav className="settings-nav" aria-label={t("Beállítások")}>
          {SECTIONS.map((s) => (
            <a key={s.key} href={`#/settings/${s.key}`} aria-current={s.key === current.key ? "page" : undefined}>{t(s.label)}</a>
          ))}
        </nav>
        <div className="settings-body">
          <h2>{t(current.label)}</h2>
          {current.key === "mailboxes" ? <Mailbox variant="settings" /> : null}
          {current.key === "folders" ? <FoldersPanel /> : null}
          {current.key === "recipes" ? <RecipesPanel /> : null}
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
      <section aria-label={t("Minden futás")}>
        <h3>{t("Minden futás")}</h3>
        <RunList />
      </section>
    </div>
  );
}
