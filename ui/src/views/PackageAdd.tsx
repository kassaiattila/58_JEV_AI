// 160-C S2 (plan F-flexible work package): adding to an existing package. Documents are added by content and the
// service says what happened — added, already in the package, restored, and the ones a live run of another package
// has processed (counted by the service, never the size of the selection; the legacy V4 add-to-group pattern). A
// package whose rule adds its own way (a statement package: its own survey, with its own party and period) has its
// domain's form (231 C3e: the package parts' `Add`, `ui/src/logic/packageParts.tsx`), built from the steps here.
// 168 (plan F-item-list-and-adding; DECISIONS 168): adding takes three steps — choose (given files, or a folder with
// or without its subfolders), check what would happen file by file, add what is ticked (the legacy V4 upload page's
// selection preview). A removed document is not ticked by default, so adding a folder again does not quietly bring
// back what was taken out on purpose.
import { useMemo, useRef, useState, type FormEvent } from "react";
import { api, ApiError, type AddSummary, type ItemPreview, type ItemSources, type PreviewFile, type Workpackage } from "../api";
import { BrowseButton } from "../components/BrowseButton";
import { FormActions } from "../components/FormActions";
import { t, useLocale } from "../i18n";
import { tmap } from "../labels";

export type AddSource = "files" | "folder";

export const pathsOf = (text: string) => text.split(/\r?\n/).map((s) => s.trim().replace(/^"|"$/g, "")).filter(Boolean);

export function addFailure(e: unknown): string {
  if (e instanceof ApiError && e.status === 409) return t("The package changed meanwhile. We refreshed the list: check it and try again.");
  return e instanceof ApiError ? e.message : String(e);
}

/** What an addition did, in the service's own counts; a document processed live in another package is a warning. */
export function AddSummaryLine({ summary }: { summary: AddSummary }) {
  useLocale();
  return (
    <div role="status" className="small add-result">
      <p className="add-summary">{t("Added: {{added}} · already in the package: {{already}} · restored: {{restored}}",
        { added: summary.added, already: summary.already, restored: summary.restored })}
        {summary.left_out ? ` · ${t("left out as unticked: {{n}}", { n: summary.left_out })}` : null}</p>
      {summary.processed_elsewhere.length ? (
        <p className="warning">{t("Already processed in a live run of another package: {{names}}. Check that it is not counted twice.",
          { names: summary.processed_elsewhere.join(", ") })}</p>
      ) : null}
    </div>
  );
}

/** The three steps' names, the current one filled; purely a guide (the form's own controls carry the meaning). */
export function AddSteps({ step }: { step: 1 | 2 | 3 }) {
  useLocale();
  const names = [t("Choose"), t("Check"), t("Add")];
  return (
    <ol className="add-steps" aria-label={t("Steps of adding")}>
      {names.map((name, i) => (
        <li key={name} aria-current={step === i + 1 ? "step" : undefined} className={step > i + 1 ? "done" : undefined}>
          <span className="add-step-no" aria-hidden="true">{i + 1}</span>{name}
        </li>
      ))}
    </ol>
  );
}

const STATE_TEXT = tmap({
  new: "New", already: "Already in the package", removed: "Removed earlier: tick to restore", repeated: "Same content as a file above",
}) as Record<PreviewFile["state"], string>;
// the state mark of each preview row: a new file is the thing to add, the others say why nothing happens to them
const STATE_MARK: Record<PreviewFile["state"], string> = { new: "s-new", already: "s-held", removed: "s-removed", repeated: "s-held" };
const tickable = (f: PreviewFile) => f.state === "new" || f.state === "removed";

/** 168: documents added to the package in three steps; `source` is the button the person pressed (files or a folder).
 *  169: `note` says what happens to them next (a reconciliation adds to another package, processed there). */
export function AddDocuments({ wp, source: initial = "files", note, onDone, onCancel }: {
  wp: Workpackage; source?: AddSource; note?: string; onDone: (s: AddSummary) => void; onCancel: () => void;
}) {
  useLocale();
  const [source, setSource] = useState<AddSource>(initial);
  const [files, setFiles] = useState("");
  const [folder, setFolder] = useState("");
  const [recursive, setRecursive] = useState(true);
  const [preview, setPreview] = useState<ItemPreview | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const asked = useRef(0);
  const lines = pathsOf(files);
  const sources: ItemSources | null = source === "files" ? (lines.length ? { paths: lines } : null)
    : folder.trim() ? { folder: folder.trim(), recursive } : null;
  // any change to what is chosen drops the preview (and a preview still on its way): its ticks belong to the files as read
  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); asked.current += 1; setPreview(null); setError(null); };

  async function check() {
    if (!sources) return;
    setBusy(true);
    setError(null);
    try {
      const my = ++asked.current;
      const p = await api.previewItems(wp.id, sources);
      if (my !== asked.current) return;
      setPreview(p);
      // new files are ticked; a removed one is not (taken out on purpose); the same content counts once
      setTicked(new Set(p.files.filter((f) => f.state === "new").map((f) => f.path)));
    } catch (err) {
      setError(addFailure(err));
    } finally {
      setBusy(false);
    }
  }

  const chosen = useMemo(() => (preview?.files ?? []).filter((f) => tickable(f) && ticked.has(f.path)), [preview, ticked]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!preview || !sources || !chosen.length) return;
    setBusy(true);
    setError(null);
    try {
      const exclude = preview.files.filter((f) => f.state === "new" && !ticked.has(f.path)).map((f) => f.item_id);
      const restore = chosen.filter((f) => f.state === "removed").map((f) => f.item_id);
      onDone((await api.addItems(wp.id, sources, wp.revision, { exclude, restore })).added);
    } catch (err) {
      setError(addFailure(err));
    } finally {
      setBusy(false);
    }
  }

  const step = preview ? (chosen.length ? 3 : 2) : 1;
  return (
    <form className="add-flow inline-form" onSubmit={submit} aria-label={t("Add documents to the package")}>
      <AddSteps step={step} />
      <fieldset className="segmented">
        <legend className="sr-only">{t("Source")}</legend>
        <label><input type="radio" name="add-src" checked={source === "files"} onChange={() => reset(setSource)("files")} /> {t("Given files")}</label>
        <label><input type="radio" name="add-src" checked={source === "folder"} onChange={() => reset(setSource)("folder")} /> {t("A folder")}</label>
      </fieldset>
      {source === "files" ? (
        <div className="path-row">
          <label className="block grow">{t("Documents to add: their full paths, one per line")}
            <textarea value={files} rows={3} onChange={(e) => reset(setFiles)(e.target.value)} />
          </label>
          <BrowseButton kind="files" initial={lines[lines.length - 1]} onPick={(picked) => reset(setFiles)([...lines, ...picked].join("\n"))} />
        </div>
      ) : (
        <div className="path-row">
          <label className="block grow">{t("The folder to add from")}
            <input value={folder} onChange={(e) => reset(setFolder)(e.target.value)} />
          </label>
          <BrowseButton kind="folder" initial={folder} onPick={([p]) => reset(setFolder)(p)} />
          <label className="check"><input type="checkbox" checked={recursive} onChange={(e) => reset(setRecursive)(e.target.checked)} /> {t("Include subfolders")}</label>
        </div>
      )}
      {preview ? null : (
        <FormActions onCancel={onCancel} busy={busy}>
          <button type="button" className="primary" disabled={busy || !sources} onClick={() => void check()}>
            {busy ? t("Reading…") : t("Check what would be added")}</button>
        </FormActions>
      )}
      {preview ? <PreviewList preview={preview} ticked={ticked} setTicked={setTicked} /> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {preview ? (
        <FormActions onCancel={onCancel} busy={busy}
          note={note ?? t("The new documents wait for processing: the run over the pending items starts from the Run card.")}>
          <button type="submit" className="primary" disabled={busy || !chosen.length}>
            {chosen.length ? t("Add {{n}} document(s)", { n: chosen.length }) : t("Nothing to add")}</button>
        </FormActions>
      ) : null}
    </form>
  );
}

/** 168: the preview's files with what would happen to each; the new and the removed ones can be ticked. */
function PreviewList({ preview, ticked, setTicked }: {
  preview: ItemPreview; ticked: Set<string>; setTicked: (s: Set<string>) => void;
}) {
  useLocale();
  const { counts, others } = preview;
  const offered = preview.files.filter(tickable);
  const all = offered.length > 0 && offered.every((f) => ticked.has(f.path));
  const toggle = (path: string, on: boolean) => {
    const next = new Set(ticked);
    if (on) next.add(path); else next.delete(path);
    setTicked(next);
  };
  const parts = [
    counts.new ? t("{{n}} new", { n: counts.new }) : "",
    counts.already ? t("{{n}} already in the package", { n: counts.already }) : "",
    counts.removed ? t("{{n}} removed earlier", { n: counts.removed }) : "",
    counts.repeated ? t("{{n}} repeated", { n: counts.repeated }) : "",
  ].filter(Boolean);
  return (
    <div className="add-preview">
      <p className="add-tally">
        <strong>{t("{{n}} document(s) found", { n: preview.files.length })}</strong>{parts.length ? `: ${parts.join(" · ")}` : null}
      </p>
      {counts.elsewhere ? (
        <p className="small"><span className="status s-warn">{t("{{n}} of them were already processed in a live run of another package: check that they are not counted twice.", { n: counts.elsewhere })}</span></p>
      ) : null}
      {others.count ? (
        <p className="muted small">{t("{{n}} other file(s) left out, as they are not documents: {{names}}", {
          n: others.count, names: others.names.join(", ") + (others.count > others.names.length ? ", …" : "") })}</p>
      ) : null}
      {preview.files.length ? (
        <div className="add-preview-scroll">
          <table className="table compact add-preview-table" aria-label={t("Files to add")}>
            <thead>
              <tr>
                <th className="tick"><input type="checkbox" aria-label={t("Tick every file that can be added")} checked={all} disabled={!offered.length}
                  onChange={(e) => setTicked(e.target.checked ? new Set(offered.map((f) => f.path)) : new Set())} /></th>
                <th>{t("File")}</th>
                {preview.folder ? <th>{t("Subfolder")}</th> : null}
                <th>{t("What happens")}</th>
              </tr>
            </thead>
            <tbody>
              {preview.files.map((f) => (
                <tr key={f.path} className={tickable(f) ? undefined : "is-quiet"}>
                  <td className="tick">
                    <input type="checkbox" aria-label={t("Add {{name}}", { name: f.name })} disabled={!tickable(f)}
                      checked={tickable(f) && ticked.has(f.path)} onChange={(e) => toggle(f.path, e.target.checked)} />
                  </td>
                  <td className="add-name" title={f.path}>{f.name}</td>
                  {preview.folder ? <td className="muted">{f.folder || "–"}</td> : null}
                  <td>
                    <span className={`status ${STATE_MARK[f.state]}`}>{STATE_TEXT[f.state]}</span>
                    {f.elsewhere && tickable(f) ? <span className="status s-warn add-elsewhere">{t("processed live elsewhere")}</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="empty">{t("No document here: nothing to add.")}</p>}
    </div>
  );
}
