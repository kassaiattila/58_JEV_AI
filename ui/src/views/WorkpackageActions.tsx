// Managing the work package (058): renaming, hiding from the list / restoring, permanent deletion. A hidden work
// package's runs and results are kept; permanent deletion is only possible on a work package without runs, with a
// separate confirmation (the local service guards this too).
import { useRef, useState } from "react";
import { api, ApiError, type WorkpackageView } from "../api";
import { Popover } from "../components/Popover";
import { FormActions } from "../components/FormActions";
import { t, useLocale } from "../i18n";
import { addsOwnWay, partOf } from "../logic/packageParts";
import { go } from "../route";
import { Icon } from "../components/Icon";
import { ScopeForm, scopeEditable } from "./PackageScope";

type Mode = "menu" | "rename" | "delete" | "scope";

export function WorkpackageActions({ view, onChanged }: { view: WorkpackageView; onChanged: () => void }) {
  useLocale();
  const wp = view.workpackage;
  // 231 (A6): a case's container takes no documents (its case reads its record)
  const adds = wp.source_kind === "case" ? "nothing" : addsOwnWay(view) ? "own" : "documents";  // 231 (C3b5a): its rule's
  const addLabel = partOf(view)?.addLabel;
  const archived = wp.status === "archived";
  // 263 (E2): a case's container is the case's: its menu says so
  const label = wp.source_kind === "case" ? t("Manage case") : t("Manage batch");
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
        <Icon name="manage" />{label}
      </button>
      <Popover open={open} onClose={close} anchor={anchor} label={label} align="right" className="wp-actions">
        {mode === "menu" ? (
          <div className="menu-list">
            {/* 167: adding leads to its form at the top of Processing (176: unless the package's logic pack adds
                nothing, as a reconciliation package has no documents) */}
            {adds === "nothing" ? null : (
              <button type="button" className="menu-item" onClick={() => { close(); go({ view: "workpackages", wpId: wp.id, stage: "process", add: true }); }}>
                <Icon name="plus" />{adds === "own" && addLabel ? t(addLabel) : t("Add documents")}
              </button>
            )}
            <button type="button" className="menu-item" onClick={() => setMode("rename")}><Icon name="edit" />{t("Rename")}</button>
            {/* 181: the party, period and role the email routing proposes the package for */}
            {scopeEditable(view) ? (
              <button type="button" className="menu-item" onClick={() => setMode("scope")}><Icon name="edit" />{t("Party, period and role…")}</button>
            ) : null}
            {archived ? (
              <button type="button" className="menu-item" disabled={busy} onClick={() => void act(() => api.restoreWorkpackage(wp.id))}>
                <Icon name="restore" />{t("Show in the list again")}
              </button>
            ) : (
              <button type="button" className="menu-item" disabled={busy} onClick={() => void act(() => api.archiveWorkpackage(wp.id))}>
                <Icon name="hide" />{t("Hide from the list")}
              </button>
            )}
            <p className="small muted">{t("A hidden batch keeps its runs and results; tick “Hidden batches too” on the list to see it again.")}</p>
            {view.runs === 0 ? (
              <button type="button" className="menu-item danger-text" onClick={() => setMode("delete")}><Icon name="trash" />{t("Delete permanently…")}</button>
            ) : (
              <p className="small muted">{t("Only a batch without runs can be deleted permanently; this one can be hidden.")}</p>
            )}
          </div>
        ) : mode === "scope" ? (
          <ScopeForm view={view} busy={busy} onCancel={() => setMode("menu")}
            onSave={(scope) => void act(() => api.setPackageScope(wp.id, scope))}
            onClear={() => void act(() => api.clearPackageScope(wp.id))} />
        ) : mode === "rename" ? (
          <form className="create" onSubmit={(e) => { e.preventDefault(); void act(() => api.renameWorkpackage(wp.id, name.trim())); }}>
            <label className="block">{t("New name")}
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required autoFocus />
            </label>
            <FormActions onCancel={() => setMode("menu")} busy={busy}>
              <button type="submit" className={name.trim() && name.trim() !== wp.name ? "primary" : "secondary"} disabled={busy || !name.trim() || name.trim() === wp.name}>{t("Save")}</button>
            </FormActions>
          </form>
        ) : (
          <div className="create">
            <p><strong>{t("Delete this batch permanently?")}</strong></p>
            <p className="small">{t("The batch and its item list are deleted; the files stay where they are. Deletion cannot be undone; the fact of deletion is kept in the log.")}</p>
            <FormActions onCancel={() => setMode("menu")} busy={busy}>
              <button type="button" className="danger" disabled={busy}
                onClick={() => void act(() => api.deleteWorkpackage(wp.id), () => go({ view: "workpackages" }))}>
                {t("Delete permanently")}
              </button>
            </FormActions>
          </div>
        )}
        {error ? <p className="notice error" role="alert">{error}</p> : null}
      </Popover>
    </>
  );
}
