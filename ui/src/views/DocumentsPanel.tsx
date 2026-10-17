// The work package's documents (057): not a separate tab but part of Review (decision of 2026-09-28). Opening and
// downloading per document, removal from the work package; before a run, this is the only content of Review.
// 160-C S1 (decisions 163 D2, D3): a removal names the chosen person and needs a reason; removed items show behind a
// switch, with who removed them, when and why, and can be restored.
import { useState, type FormEvent } from "react";
import { api, ApiError, getActor, type AddSummary, type DsRow, type Workpackage } from "../api";
import { DataTable } from "../components/DataTable";
import { nameCell, NameModeSwitch } from "../components/NameCell";
import { t, useLocale } from "../i18n";
import { useNameMode } from "../names";
import { AddDocuments, AddStatements, AddSummaryLine } from "./PackageAdd";

/** 153 (review E): where the package was created from, by its kind; later additions may come from elsewhere. */
export function createdFrom(wp: Workpackage): string {
  const ref = wp.source_ref ?? "";
  const file = ref.split(/[\\/]/).pop() ?? ref;
  switch (wp.source_kind) {
    case "folder": return ref;
    case "mailbox": return t("mailbox {{name}}", { name: file });
    case "statements": return t("a statement package");
    default: return ref ? t("the file {{name}}", { name: file }) : t("files chosen by hand");
  }
}

export function DocumentsPanel({ wp, onChanged }: { wp: Workpackage; onChanged: () => void }) {
  useLocale();
  const names = useNameMode();
  const [error, setError] = useState<string | null>(null);
  const [showRemoved, setShowRemoved] = useState(false);
  const [removing, setRemoving] = useState<{ id: string; name: string } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false); // 160-C S2
  const [added, setAdded] = useState<AddSummary | null>(null);
  const statements = wp.source_kind === "statements";

  async function act(call: () => Promise<unknown>) {
    setError(null);
    setBusy(true);
    try {
      await call();
      setRemoving(null);
      setReason("");
    } catch (e) {
      const err = e as ApiError;
      setError(err.status === 409 ? t("A csomag közben változott. Frissítettük a listát, nézd át és próbáld újra.")
        : err.status === 422 && !getActor() ? t("Choose your name at the top first: a removal is recorded with it.") : err.message);
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (removing && reason.trim()) void act(() => api.removeItem(wp.id, removing.id, wp.revision, reason.trim()));
  }

  const cell = (col: Parameters<typeof nameCell>[0], row: DsRow) => (col.key === "name" && row._removed ? (
    <span className="removed-name">{nameCell(col, row) ?? String(row.name ?? "")} <span className="status">{t("Removed")}</span></span>
  ) : nameCell(col, row));

  return (
    <section aria-label={t("A csomag iratai")} className="stage-stack">
      <div className="docs-head">
        <p className="muted small">{t("Created from: {{source}} · revision {{rev}} of the package", { source: createdFrom(wp), rev: wp.revision })}</p>
        {adding ? null : (
          <button type="button" className="secondary small-btn" onClick={() => { setAdding(true); setRemoving(null); setAdded(null); }}>
            {statements ? t("Add statements") : t("Add documents")}</button>
        )}
      </div>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {adding && statements ? <AddStatements wp={wp} onCancel={() => setAdding(false)} onDone={() => { setAdding(false); onChanged(); }} /> : null}
      {adding && !statements ? (
        <AddDocuments wp={wp} onCancel={() => setAdding(false)} onDone={(s) => { setAdding(false); setAdded(s); onChanged(); }} />
      ) : null}
      {added ? <AddSummaryLine summary={added} /> : null}
      {removing ? (
        <form className="form-row inline-form" onSubmit={submit} aria-label={t("Remove a document from the package")}>
          <label className="block grow">{t("Why remove “{{name}}”?", { name: removing.name })}
            {/* the form opens for this one answer */}
            <input value={reason} maxLength={500} required autoFocus onChange={(e) => setReason(e.target.value)}
              placeholder={t("for example: a duplicate scan, another month")} />
          </label>
          {/* a removal can be undone (restore), so it is not drawn as destructive */}
          <button type="submit" className="secondary" disabled={busy || !reason.trim()}>{t("Remove from the package")}</button>
          <button type="button" className="quiet" onClick={() => { setRemoving(null); setReason(""); }}>{t("Mégse")}</button>
          <p className="muted small form-note">{t("The file stays where it is. The item leaves the next runs; a run already started keeps it, and the item can be restored.")}</p>
        </form>
      ) : null}
      {/* the work package's revision is in the key: after a removal the list reloads */}
      <DataTable key={`${wp.id}:${wp.revision}`} dataset="workpackage_items" label={t("A csomag iratai")}
        scope={{ workpackage_id: wp.id, names, ...(showRemoved ? { removed: "1" } : {}) }}
        emptyText={t("A csomag üres.")} storageId="workpackage_items" maxHeight="60vh" cell={cell}
        toolbar={<>
          <NameModeSwitch />
          <label className="check small"><input type="checkbox" checked={showRemoved} onChange={(e) => setShowRemoved(e.target.checked)} /> {t("Removed items too")}</label>
        </>}
        actions={(row) => (row._removed ? (
          // the service serves only the package's items in use, so a removed one is restored before it is opened
          <button type="button" className="quiet small-btn" disabled={busy}
            onClick={() => void act(() => api.restoreItem(wp.id, String(row.item_id), wp.revision))}>{t("Restore")}</button>
        ) : (
          <>
            <a className="small" href={api.sourceUrl(wp.id, String(row.item_id))} target="_blank" rel="noreferrer">{t("Megnyitás")}</a>
            <a className="small" href={api.sourceUrl(wp.id, String(row.item_id))} download>{t("Letöltés")}</a>
            <button type="button" className="quiet small-btn" disabled={busy}
              onClick={() => { setRemoving({ id: String(row.item_id), name: String(row.original_name ?? row.name ?? "") }); setReason(""); setAdding(false); }}>
              {t("Eltávolítás")}</button>
          </>
        ))} />
    </section>
  );
}
