// 168 (plan F-item-list-and-adding; DECISIONS 168): the package's items, one component for Processing (below the Run
// card) and Review (the owner's choice: the same list in both places). It shows what the package holds — each item's
// state and the run whose result counts now —, adds files or a folder in three steps, removes one or several items
// with a reason and restores them; removed items show behind a switch with their count.
// Before 168 this was the document list of Review (057; 160-C S1: a removal names the chosen person and needs a reason;
// removed items show behind a switch, with who removed them, when and why, and can be restored).
import { useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, getActor, type AddSummary, type DsRow, type Workpackage, type WorkpackageView } from "../api";
import { DataTable } from "../components/DataTable";
import { FormActions } from "../components/FormActions";
import { Icon } from "../components/Icon";
import { nameCell, NameModeSwitch } from "../components/NameCell";
import { chooserOf } from "../elements/sourceChoosers";
import { t, useLocale } from "../i18n";
import { addsOwnWay, partOf, type PackagePart } from "../logic/packageParts";
import { useNameMode } from "../names";
import { wpHash } from "../route";
import { AddDocuments, AddSummaryLine, type AddSource } from "./PackageAdd";

/** 153 (review E): where the package was created from, by its kind; later additions may come from elsewhere. 183: a
 *  mailbox package is named from the request of the download that made it, in the interface's language; 261: a source
 *  kind a domain adds names its packages' origin itself (its chooser's `createdFrom`, e.g. the email domain's mailbox). */
export function createdFrom(wp: Workpackage, view?: WorkpackageView | null, part?: PackagePart): string {
  const own = part?.createdFrom; // 176: a package's rule names its own origin (231 C3b5a: a statement package's)
  if (own) return own(wp);
  const kinds = chooserOf(wp.source_kind)?.createdFrom;
  if (kinds) return kinds(wp, view);
  const ref = wp.source_ref ?? "";
  const file = ref.split(/[\\/]/).pop() ?? ref;
  switch (wp.source_kind) {
    case "folder": return ref;
    case "watch": return t("the watched folder {{path}}", { path: ref }); // 177: was "the file <folder>"
    default: return ref ? t("the file {{name}}", { name: file }) : t("files chosen by hand");
  }
}

// the tally's order: what counts first (released, then awaiting approval, then trial), then what still needs work
const TALLY = ["approved", "live", "trial", "running", "failed", "pending", "removed"] as const;
type TallyState = (typeof TALLY)[number];
const tallyText = (state: TallyState, n: number): string => ({
  approved: () => t("{{n}} approved", { n }),
  live: () => t("{{n}} processed live", { n }),
  trial: () => t("{{n}} processed in a trial", { n }),
  running: () => t("{{n}} being processed", { n }),
  failed: () => t("{{n}} failed", { n }),
  pending: () => t("{{n}} pending", { n }),
  removed: () => t("{{n}} removed", { n }),
})[state]();

/** The package's items in one line: the count, then each state with its own mark (a state without items is left out). */
function Tally({ view }: { view: WorkpackageView }) {
  useLocale();
  const counts = view.item_counts ?? {};
  return (
    <p className="items-tally">
      <strong>{t("{{n}} items", { n: view.workpackage.items.length })}</strong>
      {TALLY.filter((s) => counts[s]).map((s) => <span key={s} className={`status s-${s}`}>{tallyText(s, counts[s] ?? 0)}</span>)}
    </p>
  );
}

export function PackageItems({ view, adding, onAddingChange, onChanged, pendingAction }: {
  view: WorkpackageView;
  /** the open add form's source, or null; the caller owns it (in Processing the address does, so the menu can open it) */
  adding: AddSource | null;
  onAddingChange: (source: AddSource | null) => void;
  onChanged: () => void;
  /** the run over the pending items (Processing passes its buttons); without it, a link to Processing */
  pendingAction?: ReactNode;
}) {
  useLocale();
  const wp = view.workpackage;
  const names = useNameMode();
  const [error, setError] = useState<string | null>(null);
  const [showRemoved, setShowRemoved] = useState(false);
  const [removing, setRemoving] = useState<{ ids: string[]; name: string } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<AddSummary | null>(null);
  const own = addsOwnWay(view); // 176: added through the package's own survey (231 C3b5a: its rule's way)
  const OwnAdd = partOf(view)?.Add; // 231 (C3e): the form of the domain whose rule it is
  const removedCount = view.item_counts?.removed ?? 0;
  const supplements = Object.values(view.readiness.supplement ?? {});
  const pending = supplements.length ? Math.max(...supplements.map((s) => s?.items ?? 0)) : 0;

  async function act(call: () => Promise<unknown>) {
    setError(null);
    setBusy(true);
    try {
      await call();
      setRemoving(null);
      setReason("");
    } catch (e) {
      const err = e as ApiError;
      setError(err.status === 409 ? t("The package changed meanwhile. We refreshed the list: check it and try again.")
        : err.status === 422 && !getActor() ? t("Choose your name at the top first: a removal is recorded with it.") : err.message);
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const why = reason.trim();
    if (!removing || !why) return;
    const [only] = removing.ids;
    void act(() => (removing.ids.length === 1 ? api.removeItem(wp.id, only, wp.revision, why)
      : api.removeItems(wp.id, removing.ids, wp.revision, why)));
  }

  const open = (source: AddSource) => { setAdded(null); setRemoving(null); onAddingChange(source); };
  const close = () => { if (adding) onAddingChange(null); };
  const cell = (col: Parameters<typeof nameCell>[0], row: DsRow) => (col.key === "name" && row._removed ? (
    <span className="removed-name">{nameCell(col, row) ?? String(row.name ?? "")}</span>
  ) : nameCell(col, row));

  return (
    <section className="card wide items-card" aria-label={t("The package's items")}>
      <div className="card-head">
        <div className="items-head">
          <h2>{t("The package's items")}</h2>
          <Tally view={view} />
        </div>
        {adding ? null : own ? (
          <button type="button" className="secondary" onClick={() => open("folder")}><Icon name="plus" />{t(partOf(view)?.addLabel ?? "")}</button>
        ) : (
          <div className="button-row">
            <button type="button" className="secondary" onClick={() => open("files")}><Icon name="file" />{t("Add files")}</button>
            <button type="button" className="secondary" onClick={() => open("folder")}><Icon name="folder" />{t("Add a folder")}</button>
          </div>
        )}
      </div>
      <p className="muted small">{t("Created from: {{source}} · revision {{rev}} of the package", { source: createdFrom(wp, view, partOf(view)), rev: wp.revision })}</p>
      {adding && own && OwnAdd ? <OwnAdd wp={wp} source={adding} onCancel={close} onDone={() => { close(); onChanged(); }} /> : null}
      {adding && !own ? <AddDocuments wp={wp} source={adding} onCancel={close} onDone={(s) => { close(); setAdded(s); onChanged(); }} /> : null}
      {added ? <AddSummaryLine summary={added} /> : null}
      {pending ? (
        <div className="items-pending" role="region" aria-label={t("Pending items")}>
          <span className="status s-pending">{t("{{n}} item(s) wait for processing", { n: pending })}</span>
          {pendingAction ?? <a href={wpHash(wp.id, "process")}>{t("Run them in Processing")}</a>}
        </div>
      ) : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {removing ? (
        <form className="form-row inline-form" onSubmit={submit} aria-label={t("Remove from the package")}>
          <label className="block grow">{removing.ids.length === 1 ? t("Why remove “{{name}}”?", { name: removing.name })
            : t("Why remove these items ({{n}})?", { n: removing.ids.length })}
            {/* the form opens for this one answer */}
            <input value={reason} maxLength={500} required autoFocus onChange={(e) => setReason(e.target.value)}
              placeholder={t("for example: a duplicate scan, another month")} />
          </label>
          <p className="muted small form-note">{t("The file stays where it is. The item leaves the next runs; a run already started keeps it, and the item can be restored.")}</p>
          {/* a removal can be undone (restore), so it is not drawn as destructive; 263 (F1): "Cancel" first, on the right */}
          <FormActions onCancel={() => { setRemoving(null); setReason(""); }} busy={busy}>
            <button type="submit" className="primary" disabled={busy || !reason.trim()}>{t("Remove from the package")}</button>
          </FormActions>
        </form>
      ) : null}
      {/* the work package's revision is in the key: after a change the list reloads and the selection clears */}
      <DataTable key={`${wp.id}:${wp.revision}`} dataset="workpackage_items" label={t("The package's items")} selectable
        scope={{ workpackage_id: wp.id, names, ...(showRemoved ? { removed: "1" } : {}) }}
        emptyText={t("The package is empty.")} storageId="workpackage_items" maxHeight="50vh" cell={cell}
        toolbar={<>
          <NameModeSwitch />
          <label className="check small"><input type="checkbox" checked={showRemoved} onChange={(e) => setShowRemoved(e.target.checked)} />
            {" "}{removedCount ? t("Removed items too ({{n}})", { n: removedCount }) : t("Removed items too")}</label>
        </>}
        selectionActions={(rows) => {
          const inUse = rows.filter((r) => !r._removed);
          const gone = rows.filter((r) => r._removed);
          return (
            <>
              {inUse.length ? (
                <button type="button" className="secondary small-btn" disabled={busy} onClick={() => {
                  setRemoving({ ids: inUse.map((r) => String(r.item_id)), name: String(inUse[0].original_name ?? inUse[0].name ?? "") });
                  setReason(""); close();
                }}>{t("Remove {{n}} from the package…", { n: inUse.length })}</button>
              ) : null}
              {gone.length ? (
                <button type="button" className="secondary small-btn" disabled={busy}
                  onClick={() => void act(() => api.restoreItems(wp.id, gone.map((r) => String(r.item_id)), wp.revision))}>
                  {t("Restore {{n}}", { n: gone.length })}</button>
              ) : null}
            </>
          );
        }}
        actions={(row) => (row._removed ? (
          // the service serves only the package's items in use, so a removed one is restored before it is opened
          <button type="button" className="quiet small-btn" disabled={busy}
            onClick={() => void act(() => api.restoreItem(wp.id, String(row.item_id), wp.revision))}>{t("Restore")}</button>
        ) : (
          <>
            <a className="small" href={api.sourceUrl(wp.id, String(row.item_id))} target="_blank" rel="noreferrer">{t("Open document")}</a>
            <a className="small" href={api.sourceUrl(wp.id, String(row.item_id))} download>{t("Download")}</a>
            <button type="button" className="quiet small-btn" disabled={busy}
              onClick={() => { setRemoving({ ids: [String(row.item_id)], name: String(row.original_name ?? row.name ?? "") }); setReason(""); close(); }}>
              {t("Remove")}</button>
          </>
        ))} />
    </section>
  );
}

/** The item list with its own add form state (Review: the address does not hold it there). */
export function PackageItemsPanel({ view, onChanged }: { view: WorkpackageView; onChanged: () => void }) {
  const [adding, setAdding] = useState<AddSource | null>(null);
  return <PackageItems view={view} adding={adding} onAddingChange={setAdding} onChanged={onChanged} />;
}
