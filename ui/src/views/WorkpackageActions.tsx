// Managing the work package (058): renaming, hiding from the list / restoring, permanent deletion. A hidden work
// package's runs and results are kept; permanent deletion is only possible on a work package without runs, with a
// separate confirmation (the local service guards this too).
import { useRef, useState } from "react";
import { api, ApiError, type WorkpackageView } from "../api";
import { Popover } from "../components/Popover";
import { t, useLocale } from "../i18n";
import { logicOf } from "../logic/registry";
import { go } from "../route";
import { Icon } from "../components/Icon";
import { ScopeForm, scopeEditable } from "./PackageScope";

type Mode = "menu" | "rename" | "delete" | "scope";

export function WorkpackageActions({ view, onChanged }: { view: WorkpackageView; onChanged: () => void }) {
  useLocale();
  const wp = view.workpackage;
  // 231 (A6): a case's container takes no documents (its case reads its record)
  const adds = wp.source_kind === "case" ? "nothing" : logicOf(wp.source_kind)?.adds;
  const archived = wp.status === "archived";
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("menu");
  const [name, setName] = useState(wp.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setOpen(false);
    setMode("menu");
    setError(null);
  };
  const act = async (fn: () => Promise<unknown>, after: () => void = onChanged) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      close();
      after();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button ref={anchor} type="button" className="secondary" aria-expanded={open} aria-haspopup="dialog"
        onClick={() => { setName(wp.name); setMode("menu"); setError(null); setOpen((o) => !o); }}>
        <Icon name="manage" />{t("Csomag kezelése")}
      </button>
      <Popover open={open} onClose={close} anchor={anchor} label={t("Csomag kezelése")} align="right" className="wp-actions">
        {mode === "menu" ? (
          <div className="menu-list">
            {/* 167: adding leads to its form at the top of Processing (176: unless the package's logic pack adds
                nothing, as a reconciliation package has no documents) */}
            {adds === "nothing" ? null : (
              <button type="button" className="menu-item" onClick={() => { close(); go({ view: "workpackages", wpId: wp.id, stage: "process", add: true }); }}>
                <Icon name="plus" />{adds === "statements" ? t("Add statements") : t("Add documents")}
              </button>
            )}
            <button type="button" className="menu-item" onClick={() => setMode("rename")}><Icon name="edit" />{t("Átnevezés")}</button>
            {/* 181: the party, period and role the email routing proposes the package for */}
            {scopeEditable(view) ? (
              <button type="button" className="menu-item" onClick={() => setMode("scope")}><Icon name="edit" />{t("Party, period and role…")}</button>
            ) : null}
            {archived ? (
              <button type="button" className="menu-item" disabled={busy} onClick={() => void act(() => api.restoreWorkpackage(wp.id))}>
                <Icon name="restore" />{t("Visszahozás a listába")}
              </button>
            ) : (
              <button type="button" className="menu-item" disabled={busy} onClick={() => void act(() => api.archiveWorkpackage(wp.id))}>
                <Icon name="hide" />{t("Elrejtés a listából")}
              </button>
            )}
            <p className="small muted">{t("Az elrejtett csomag futásai és eredményei megmaradnak; a lista „Elrejtett csomagok is” jelölőjével újra látszik.")}</p>
            {view.runs === 0 ? (
              <button type="button" className="menu-item danger-text" onClick={() => setMode("delete")}><Icon name="trash" />{t("Végleges törlés…")}</button>
            ) : (
              <p className="small muted">{t("Végleges törlés csak futás nélküli csomagon lehetséges; ez a csomag elrejthető.")}</p>
            )}
          </div>
        ) : mode === "scope" ? (
          <ScopeForm view={view} busy={busy} onCancel={() => setMode("menu")}
            onSave={(scope) => void act(() => api.setPackageScope(wp.id, scope))}
            onClear={() => void act(() => api.clearPackageScope(wp.id))} />
        ) : mode === "rename" ? (
          <form className="create" onSubmit={(e) => { e.preventDefault(); void act(() => api.renameWorkpackage(wp.id, name.trim())); }}>
            <label className="block">{t("Új név")}
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required autoFocus />
            </label>
            <div className="button-row">
              <button type="submit" className={name.trim() && name.trim() !== wp.name ? "primary" : "secondary"} disabled={busy || !name.trim() || name.trim() === wp.name}>{t("Mentés")}</button>
              <button type="button" className="secondary" onClick={() => setMode("menu")}>{t("Mégse")}</button>
            </div>
          </form>
        ) : (
          <div className="create">
            <p><strong>{t("Biztosan törlöd a csomagot?")}</strong></p>
            <p className="small">{t("A csomag és a tétel-listája törlődik, a fájlok a helyükön maradnak. A törlés nem vonható vissza; a ténye naplóban marad.")}</p>
            <div className="button-row">
              <button type="button" className="danger" disabled={busy}
                onClick={() => void act(() => api.deleteWorkpackage(wp.id), () => go({ view: "workpackages" }))}>
                {t("Végleges törlés")}
              </button>
              <button type="button" className="secondary" onClick={() => setMode("menu")}>{t("Mégse")}</button>
            </div>
          </div>
        )}
        {error ? <p className="notice error" role="alert">{error}</p> : null}
      </Popover>
    </>
  );
}
