// Work folders (057, following how the legacy V4 „Figyelt mappák” (Watched folders) work): per folder a name, path,
// active flag, subfolders, packaging (one shared package / daily packages) and check interval (080: the package gets the default processing settings). Draft → save or
// discard; with unsaved changes, leaving the page or following an internal link asks for confirmation (the V4 pattern).
// The path can be any existing folder (061 decision; the restriction can be switched back on in the local service's
// settings); the worker checks the folder at intervals, and no paid run starts on its own. 078: below the list, the output
// folder of the content-named copies. 081: every path can be picked with the system's folder picker (Browse…).
import { useEffect, useState } from "react";
import { api, ApiError, getActor, NO_ACTOR, type WatchedFolder } from "../../api";
import { BrowseButton } from "../../components/BrowseButton";
import { DocumentFormats } from "../../components/DocumentFormats";
import { Picker } from "../../components/Picker";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { intervals, when } from "../../labels";
import { Icon } from "../../components/Icon";

const EMPTY: WatchedFolder = { name: "", path: "", enabled: true, recursive: false, batch_mode: "folder", recipe_id: null, params: {}, interval_min: 15 };

export function FoldersPanel() {
  useLocale();
  const data = useLoad("folders", api.folders);
  const [draft, setDraft] = useState<WatchedFolder[]>([]);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data.data) setDraft(data.data.folders); }, [data.data]);
  const baseline = data.data?.folders ?? [];
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline);

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

  const set = (i: number, patch: Partial<WatchedFolder>) => setDraft((d) => d.map((f, j) => (j === i ? { ...f, ...patch } : f)));

  async function save() {
    if (!getActor()) { setMsg({ error: true, text: t("Cannot save: {{reason}}.", { reason: t(NO_ACTOR) }) }); return; }
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.saveFolders(draft);
      setDraft(res.folders);
      setMsg({ error: false, text: t("Saved. The worker checks the folders at the set frequency.") });
      data.reload();
    } catch (e) {
      const err = e as ApiError;
      setMsg({ error: true, text: err.code === "forbidden_path" ? t("A path is outside the allowed locations (listed below).")
        : err.code === "folder_overlap" ? t("A work folder cannot be inside the output folder, nor contain it (below).") : err.message });
    } finally {
      setBusy(false);
    }
  }

  async function scan(id: string) {
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
    <section className="stage-stack" aria-label={t("Work folders")}>
      <p className="muted small">{t("The worker checks this folder at the chosen interval and adds new supported documents to a work package. Source files are read only. Check the package recipe before starting processing; paid runs never start automatically.")}</p>
      <DocumentFormats />
      {data.error ? <p className="notice error">{data.error.message}</p> : null}
      {draft.map((f, i) => (
        <fieldset key={f.id ?? `new-${i}`} className="card wide folder-card">
          <legend>{f.name || t("New work folder")}</legend>
          <div className="form-row">
            <label className="block">{t("Name")}<input value={f.name} maxLength={160} placeholder={t("(empty: the folder name)")} onChange={(e) => set(i, { name: e.target.value })} /></label>
            <label className="block grow">{t("Full folder path")}<input value={f.path} maxLength={1024} required onChange={(e) => set(i, { path: e.target.value })} /></label>
            <BrowseButton kind="folder" initial={f.path} onPick={([p]) => set(i, { path: p })} />
          </div>
          <div className="form-row">
            <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => set(i, { enabled: e.target.checked })} /> {t("Active (state)")}</label>
            <label className="check"><input type="checkbox" checked={f.recursive} onChange={(e) => set(i, { recursive: e.target.checked })} /> {t("Include subfolders")}</label>
            <fieldset className="segmented">
              <legend className="sr-only">{t("Packaging")}</legend>
              <label><input type="radio" name={`mode-${i}`} checked={f.batch_mode === "folder"} onChange={() => set(i, { batch_mode: "folder" })} /> {t("One shared batch")}</label>
              <label><input type="radio" name={`mode-${i}`} checked={f.batch_mode === "daily"} onChange={() => set(i, { batch_mode: "daily" })} /> {t("Daily batches")}</label>
            </fieldset>
          </div>
          <div className="form-row">
            <Picker label={t("Look over")} value={String(f.interval_min)} options={intervals().map(([m, label]) => ({ value: String(m), label }))}
              onChange={(v) => set(i, { interval_min: Number(v) })} />
          </div>
          <div className="button-row">
            {f.id && baseline.some((b) => b.id === f.id) ? <button type="button" className="secondary small-btn" disabled={dirty} title={dirty ? t("Save your changes first") : undefined}
              onClick={() => void scan(f.id!)}>{t("Check now")}</button> : null}
            <button type="button" className="quiet small-btn" onClick={() => setDraft((d) => d.filter((_, j) => j !== i))}>{t("Remove")}</button>
            <span className="muted small">
              {f.last_at ? <>{t("Last: {{when}}", { when: when(f.last_at) })} · {f.last_status === "error" ? <span className="error-text">{f.last_result?.error}</span>
                : t("{{n}} new documents", { n: f.last_result?.new ?? 0 })}{f.last_result?.workpackage ? <> · <a href={`#/workpackages/${f.last_result.workpackage}`}>{t("batch")}</a></> : null}</> : t("Not checked yet.")}
            </span>
          </div>
        </fieldset>
      ))}
      <div className="button-row">
        <button type="button" className="secondary" onClick={() => setDraft((d) => [...d, { ...EMPTY }])}><Icon name="plus" />{t("Add work folder")}</button>
        <span className="dt-spacer" />
        <button type="button" className="secondary" disabled={!dirty || busy} onClick={() => setDraft(baseline)}>{t("Discard changes")}</button>
        {/* 157: solid only while there is something to save (a faded solid button was noise) */}
        <button type="button" className={dirty ? "primary" : "secondary"} disabled={!dirty || busy} onClick={() => void save()}>{busy ? t("Saving…") : t("Save")}</button>
      </div>
      <p className="muted small" role="status">{dirty ? t("There are unsaved changes.") : ""}</p>
      {msg ? <p className={msg.error ? "notice error" : "notice"} role={msg.error ? "alert" : "status"}>{msg.text}</p> : null}
      {/* 061: by default there is no folder restriction; the list of locations only shows when it is switched on */}
      {data.data?.roots.length ? <p className="muted small">{t("Allowed locations: {{roots}}", { roots: data.data.roots.join(" · ") })}</p> : null}
      <OutputFolderCard />
    </section>
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
      <div className="button-row">
        <span className="dt-spacer" />
        <button type="button" className={path.trim() === saved ? "secondary" : "primary"} disabled={busy || path.trim() === saved} onClick={() => void save()}>{busy ? t("Saving…") : t("Save")}</button>
      </div>
      {msg ? <p className={msg.error ? "notice error" : "notice"} role={msg.error ? "alert" : "status"}>{msg.text}</p> : null}
    </fieldset>
  );
}
