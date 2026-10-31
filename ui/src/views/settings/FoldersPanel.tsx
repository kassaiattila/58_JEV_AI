// Work folders (057, following how the legacy V4 „Figyelt mappák” (Watched folders) work): per folder a name, path,
// active flag, subfolders, packaging (one shared package / daily packages) and check interval (080: the package gets the default processing settings). Draft → save or
// discard; with unsaved changes, leaving the page or following an internal link asks for confirmation (the V4 pattern).
// The path can be any existing folder (061 decision; the restriction can be switched back on in the local service's
// settings); the worker checks the folder at intervals, and no paid run starts on its own. 078: below the list, the output
// folder of the content-named copies. 081: every path can be picked with the system's folder picker (Browse…).
// 264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): the folders are the one list
// (`settings_folders`), "Add work folder" the title row's main action with a page of its own, a folder its own page
// (Remove at the left, Cancel, Save; "Check now" in the title row); the service still saves the whole list, so a page
// sends the list as it was read with its one folder changed.
import { useEffect, useState } from "react";
import { api, ApiError, getActor, NO_ACTOR, type WatchedFolder } from "../../api";
import { BrowseButton } from "../../components/BrowseButton";
import { ConfirmButton } from "../../components/ConfirmButton";
import { DataTable } from "../../components/DataTable";
import { DocumentFormats } from "../../components/DocumentFormats";
import { FormActions } from "../../components/FormActions";
import { ItemSteps } from "../../components/ItemSteps";
import { PageActions } from "../../components/PageActions";
import { Picker } from "../../components/Picker";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { intervals, when } from "../../labels";
import { go, settingsHash } from "../../route";
import { settingsChanged, useSettingsTitle } from "./settingsTree";

const EMPTY: WatchedFolder = { name: "", path: "", enabled: true, recursive: false, batch_mode: "folder", recipe_id: null, params: {}, interval_min: 15 };
const LIST = "settings_folders";
const NEW = "new";

export function FoldersPanel({ item }: { item?: string }) {
  useLocale();
  if (item) return <FolderPage key={item} id={item} />;
  return (
    <section className="stage-stack" aria-label={t("Work folders")}>
      <PageActions><a className="button primary" href={settingsHash("folders", NEW)}>{t("Add work folder")}</a></PageActions>
      <p className="muted small">{t("The worker checks this folder at the chosen interval and adds new supported documents to a work package. Source files are read only. Check the package recipe before starting processing; paid runs never start automatically.")}</p>
      <DocumentFormats />
      <DataTable dataset={LIST} label={t("Work folders")} storageId={LIST} persist={LIST} pollMs={15000}
        emptyText={t("No work folder yet: “Add work folder” sets one.")} />
      <OutputFolderCard />
    </section>
  );
}

/** One folder's page (a new one's too): its settings saved with the rest of the list as it was read. */
function FolderPage({ id }: { id: string }) {
  useLocale();
  const data = useLoad("folders", api.folders);
  const saved = id === NEW ? null : data.data?.folders.find((f) => f.id === id) ?? null;
  const [draft, setDraft] = useState<WatchedFolder | null>(null);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const base = saved ?? EMPTY;
  const f = draft ?? base;
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(base);
  useSettingsTitle(id === NEW ? t("New work folder") : saved ? saved.name : null);

  // unsaved changes: leaving the page or following an internal link asks for confirmation
  useEffect(() => {
    if (!dirty) return;
    const unload = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    const click = (e: MouseEvent) => {
      const a = (e.target as HTMLElement).closest?.('a[href^="#"]');
      if (a && !window.confirm(t("Your changes to the work folders are not saved. Discard them?"))) { e.preventDefault(); e.stopPropagation(); }
    };
    window.addEventListener("beforeunload", unload);
    document.addEventListener("click", click, true);
    return () => { window.removeEventListener("beforeunload", unload); document.removeEventListener("click", click, true); };
  }, [dirty]);

  if (data.error) return <p className="notice error" role="alert">{data.error.message}</p>;
  if (!data.data) return <p className="muted">{t("Loading…")}</p>;
  if (id !== NEW && !saved) return <p className="notice warn">{t("It is not among the work folders (any more).")}</p>;
  const set = (patch: Partial<WatchedFolder>) => setDraft({ ...f, ...patch });

  async function write(next: WatchedFolder[], then: (folders: WatchedFolder[]) => void, done?: string) {
    if (!getActor()) { setMsg({ error: true, text: t("Cannot save: {{reason}}.", { reason: t(NO_ACTOR) }) }); return; }
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.saveFolders(next);
      setDraft(null);
      if (done) setMsg({ error: false, text: done });
      data.reload();
      settingsChanged();
      then(res.folders);
    } catch (e) {
      const err = e as ApiError;
      setMsg({ error: true, text: err.code === "forbidden_path" ? t("A path is outside the allowed locations (listed below).")
        : err.code === "folder_overlap" ? t("A work folder cannot be inside the output folder, nor contain it (below).") : err.message });
    } finally {
      setBusy(false);
    }
  }
  const all = data.data.folders;
  const save = () => void write(saved ? all.map((x) => (x.id === saved.id ? f : x)) : [...all, f], (folders) => {
    if (saved) return;
    const made = folders.find((x) => !all.some((y) => y.id === x.id));
    if (made?.id) go({ view: "settings", section: "folders", item: made.id });
  }, saved ? t("Saved. The worker checks the folders at the set frequency.") : undefined);
  const remove = () => void write(all.filter((x) => x.id !== id), () => go({ view: "settings", section: "folders" }));

  async function scan() {
    setMsg(null);
    try {
      const r = await api.scanFolder(id);
      setMsg({ error: r.status !== "ok", text: r.status === "ok"
        ? (r.settling
          ? t("Checked: {{n}} new documents, {{settling}} still being written (left for the next check).", { n: r.new ?? 0, settling: r.settling })
          : t("Checked: {{n}} new documents.", { n: r.new ?? 0 }))
        : r.error ?? t("Error") });
      data.reload();
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
    }
  }

  return (
    <>
      {saved ? (
        <PageActions>
          <ItemSteps list={LIST} />
          <button type="button" className="secondary" disabled={dirty} title={dirty ? t("Save your changes first") : undefined}
            onClick={() => void scan()}>{t("Check now")}</button>
        </PageActions>
      ) : null}
      <section className="sheet" aria-label={saved ? saved.name : t("New work folder")}>
        <div className="form-row">
          <label className="block">{t("Name")}<input value={f.name} maxLength={160} placeholder={t("(empty: the folder name)")} onChange={(e) => set({ name: e.target.value })} /></label>
          <label className="block grow">{t("Full folder path")}<input value={f.path} maxLength={1024} required onChange={(e) => set({ path: e.target.value })} /></label>
          <BrowseButton kind="folder" initial={f.path} onPick={([p]) => set({ path: p })} />
        </div>
        <div className="form-row">
          <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> {t("Active (state)")}</label>
          <label className="check"><input type="checkbox" checked={f.recursive} onChange={(e) => set({ recursive: e.target.checked })} /> {t("Include subfolders")}</label>
          <fieldset className="segmented">
            <legend className="sr-only">{t("Packaging")}</legend>
            <label><input type="radio" name="folder-mode" checked={f.batch_mode === "folder"} onChange={() => set({ batch_mode: "folder" })} /> {t("One shared batch")}</label>
            <label><input type="radio" name="folder-mode" checked={f.batch_mode === "daily"} onChange={() => set({ batch_mode: "daily" })} /> {t("Daily batches")}</label>
          </fieldset>
        </div>
        <div className="form-row">
          <Picker label={t("Look over")} value={String(f.interval_min)} options={intervals().map(([m, label]) => ({ value: String(m), label }))}
            onChange={(v) => set({ interval_min: Number(v) })} />
        </div>
        {saved ? (
          <p className="muted small">
            {saved.last_at ? <>{t("Last: {{when}}", { when: when(saved.last_at) })} · {saved.last_status === "error" ? <span className="error-text">{saved.last_result?.error}</span>
              : t("{{n}} new documents", { n: saved.last_result?.new ?? 0 })}{saved.last_result?.workpackage ? <> · <a href={`#/workpackages/${saved.last_result.workpackage}`}>{t("batch")}</a></> : null}</> : t("Not checked yet.")}
          </p>
        ) : null}
        {msg ? <p className={msg.error ? "notice error" : "notice"} role={msg.error ? "alert" : "status"}>{msg.text}</p> : null}
        {/* 061: by default there is no folder restriction; the list of locations only shows when it is switched on */}
        {data.data.roots.length ? <p className="muted small">{t("Allowed locations: {{roots}}", { roots: data.data.roots.join(" · ") })}</p> : null}
        <FormActions busy={busy}
          start={saved ? <ConfirmButton className="quiet" danger disabled={busy} question={t("Remove this work folder? Its batches and documents stay; the worker no longer checks it.")}
            onConfirm={remove}>{t("Remove")}</ConfirmButton> : undefined}
          onCancel={saved ? (dirty ? () => setDraft(null) : undefined) : () => go({ view: "settings", section: "folders" })}
          note={dirty ? t("There are unsaved changes.") : undefined}>
          {/* 157: solid only while there is something to save (a faded solid button was noise) */}
          <button type="button" className={dirty ? "primary" : "secondary"} disabled={!dirty || busy || !f.path.trim()} onClick={save}>
            {busy ? t("Saving…") : t("Save")}</button>
        </FormActions>
      </section>
    </>
  );
}

/** 078: where the content-named copies of a run go (Result › File names). Saved on its own, not with the folder list;
 *  every write makes a new subfolder there, nothing is overwritten or deleted. */
export function OutputFolderCard() {
  useLocale();
  const data = useLoad("output-folder", api.outputFolder);
  // null: not edited, the saved value shows; a value typed before the saved one arrives is kept
  const [draft, setDraft] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const saved = data.data?.path ?? "";
  const path = draft ?? saved;

  async function save() {
    if (!getActor()) { setMsg({ error: true, text: t("Cannot save: {{reason}}.", { reason: t(NO_ACTOR) }) }); return; }
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.saveOutputFolder(path.trim() || null);
      setDraft(res.path ?? "");
      setMsg({ error: false, text: res.path ? t("Saved.") : t("The output folder has been cleared.") });
      data.reload();
    } catch (e) {
      const err = e as ApiError;
      setMsg({ error: true, text: err.code === "folder_overlap" ? t("The output folder and a watched work folder cannot be inside one another (the watcher would take the copies in again), nor can it be in the application's own data folders.")
        : err.code === "forbidden_path" ? t("A path is outside the allowed locations (listed below).") : err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset className="card wide folder-card" aria-label={t("Output folder")}>
      <legend>{t("Output folder")}</legend>
      <p className="muted small">{t("The content-named copies of the documents go here (Result › File names). Every write gets a new subfolder; nothing here is ever overwritten or deleted. It cannot be inside a watched work folder.")}</p>
      <div className="form-row">
        <label className="block grow">{t("Full folder path")}<input value={path} maxLength={1024} placeholder={t("(empty: no output folder)")} onChange={(e) => setDraft(e.target.value)} /></label>
        <BrowseButton kind="folder" initial={path} onPick={([p]) => setDraft(p)} />
      </div>
      {msg ? <p className={msg.error ? "notice error" : "notice"} role={msg.error ? "alert" : "status"}>{msg.text}</p> : null}
      {/* 264 (F6): Cancel while something changed, then the save */}
      <FormActions busy={busy} onCancel={path.trim() !== saved ? () => setDraft(null) : undefined}>
        <button type="button" className={path.trim() === saved ? "secondary" : "primary"} disabled={busy || path.trim() === saved} onClick={() => void save()}>{busy ? t("Saving…") : t("Save")}</button>
      </FormActions>
    </fieldset>
  );
}
