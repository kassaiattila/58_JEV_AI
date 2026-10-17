// 160-C S2 (plan F-flexible work package): adding to an existing package. Documents are added by content and the
// service says what happened — added, already in the package, restored, and the ones a live run of another package
// has processed (counted by the service, never the size of the selection; the legacy V4 add-to-group pattern). A
// statement package grows only through its own survey, with its own party and period.
import { useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, type AddSummary, type StatementPackageSurvey, type Workpackage } from "../api";
import { BrowseButton } from "../components/BrowseButton";
import { Icon } from "../components/Icon";
import { t, useLocale } from "../i18n";
import { SurveyChoices } from "./StatementPackageCreate";

const pathsOf = (text: string) => text.split(/\r?\n/).map((s) => s.trim().replace(/^"|"$/g, "")).filter(Boolean);

function failure(e: unknown): string {
  if (e instanceof ApiError && e.status === 409) return t("The package changed meanwhile. We refreshed the list: check it and try again.");
  return e instanceof ApiError ? e.message : String(e);
}

/** What an addition did, in the service's own counts; a document processed live in another package is a warning. */
export function AddSummaryLine({ summary }: { summary: AddSummary }) {
  useLocale();
  return (
    <div role="status" className="small">
      <p className="add-summary">{t("Added: {{added}} · already in the package: {{already}} · restored: {{restored}}",
        { added: summary.added, already: summary.already, restored: summary.restored })}</p>
      {summary.processed_elsewhere.length ? (
        <p className="warning">{t("Already processed in a live run of another package: {{names}}. Check that it is not counted twice.",
          { names: summary.processed_elsewhere.join(", ") })}</p>
      ) : null}
    </div>
  );
}

/** 167: the add action with its form and the service's counts, in one place for Processing (above the run buttons) and
 *  Review's document list. `lead` is the text on the button's left; the caller owns whether the form is open (in
 *  Processing the address does, so the actions menu can open it). A statement package grows through its survey. */
export function AddToPackage({ wp, lead, open, onOpenChange, onChanged }: {
  wp: Workpackage; lead: ReactNode; open: boolean; onOpenChange: (open: boolean) => void; onChanged: () => void;
}) {
  useLocale();
  const [added, setAdded] = useState<AddSummary | null>(null);
  const statements = wp.source_kind === "statements";
  const close = () => onOpenChange(false);
  return (
    <>
      <div className="docs-head">
        {lead}
        {open ? null : (
          <button type="button" className="secondary small-btn" onClick={() => { setAdded(null); onOpenChange(true); }}>
            <Icon name="plus" />{statements ? t("Add statements") : t("Add documents")}</button>
        )}
      </div>
      {open && statements ? <AddStatements wp={wp} onCancel={close} onDone={() => { close(); onChanged(); }} /> : null}
      {open && !statements ? <AddDocuments wp={wp} onCancel={close} onDone={(s) => { close(); setAdded(s); onChanged(); }} /> : null}
      {added ? <AddSummaryLine summary={added} /> : null}
    </>
  );
}

export function AddDocuments({ wp, onDone, onCancel }: { wp: Workpackage; onDone: (s: AddSummary) => void; onCancel: () => void }) {
  useLocale();
  const [files, setFiles] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const paths = pathsOf(files);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!paths.length) return;
    setBusy(true);
    setError(null);
    try {
      onDone((await api.addItems(wp.id, paths, wp.revision)).added);
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form-row inline-form" onSubmit={submit} aria-label={t("Add documents to the package")}>
      <label className="block grow">{t("Documents to add: their full paths, one per line")}
        <textarea value={files} rows={3} onChange={(e) => setFiles(e.target.value)} />
      </label>
      <BrowseButton kind="files" initial={paths[paths.length - 1]} onPick={(picked) => setFiles([...paths, ...picked].join("\n"))} />
      <button type="submit" className="secondary" disabled={busy || !paths.length}>{t("Add {{n}} document(s)", { n: paths.length })}</button>
      <button type="button" className="quiet" onClick={onCancel}>{t("Cancel")}</button>
      <p className="muted small form-note">{t("A document already in the package is not added again, and a removed one is restored. The new documents wait for processing.")}</p>
      {error ? <p className="notice error form-note" role="alert">{error}</p> : null}
    </form>
  );
}

export function AddStatements({ wp, onDone, onCancel }: { wp: Workpackage; onDone: () => void; onCancel: () => void }) {
  useLocale();
  const [source, setSource] = useState<"folder" | "files">("folder");
  const [folder, setFolder] = useState("");
  const [files, setFiles] = useState("");
  const [survey, setSurvey] = useState<StatementPackageSurvey | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lines = pathsOf(files);
  const paths = source === "folder" ? (folder.trim() ? [folder.trim()] : []) : lines;
  // any change to what is surveyed drops the survey: the ticks belong to the files as they were read
  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); setSurvey(null); setChosen(new Set()); };

  async function read() {
    setBusy(true);
    setError(null);
    try {
      const s = await api.packageStatementSurvey(wp.id, paths);
      setSurvey(s);
      setChosen(new Set([...s.statements.filter((r) => r.chosen).map((r) => r.id), ...s.pdfs.filter((p) => p.chosen).map((p) => p.path)]));
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!survey) return;
    setBusy(true);
    setError(null);
    try {
      await api.addPackageStatements(wp.id, { paths, expected_revision: wp.revision,
        statements: survey.statements.filter((r) => chosen.has(r.id)).map((r) => r.id),
        pdfs: survey.pdfs.filter((p) => chosen.has(p.path)).map((p) => p.path) });
      onDone();
    } catch (err) {
      setError(failure(err));
    } finally {
      setBusy(false);
    }
  }

  const nStatements = survey ? survey.statements.filter((r) => chosen.has(r.id)).length : 0;
  const nPdfs = survey ? survey.pdfs.filter((p) => chosen.has(p.path)).length : 0;
  return (
    <form className="rc-stack inline-form" onSubmit={submit} aria-label={t("Add statements to the package")}>
      <p className="muted small">{t("The files are surveyed for the package's own party and period; what the package already holds is not offered again.")}</p>
      <fieldset className="segmented">
        <legend className="sr-only">{t("Source")}</legend>
        <label><input type="radio" name="sp-add-src" checked={source === "folder"} onChange={() => reset(setSource)("folder")} /> {t("A folder")}</label>
        <label><input type="radio" name="sp-add-src" checked={source === "files"} onChange={() => reset(setSource)("files")} /> {t("Given files")}</label>
      </fieldset>
      {source === "folder" ? (
        <div className="path-row">
          <label className="block grow">{t("The statements' folder")}<input value={folder} onChange={(e) => reset(setFolder)(e.target.value)} /></label>
          <BrowseButton kind="folder" initial={folder} onPick={([p]) => reset(setFolder)(p)} />
        </div>
      ) : (
        <div className="path-row">
          <label className="block grow">{t("The files' full paths, one per line")}
            <textarea value={files} onChange={(e) => reset(setFiles)(e.target.value)} rows={3} />
          </label>
          <BrowseButton kind="files" initial={lines[lines.length - 1]} onPick={(picked) => reset(setFiles)([...lines, ...picked].join("\n"))} />
        </div>
      )}
      <div className="button-row">
        <button type="button" className="secondary" disabled={busy || !paths.length} onClick={() => void read()}>
          {busy && !survey ? t("Reading…") : t("Survey the files")}</button>
        <button type="button" className="quiet" onClick={onCancel}>{t("Cancel")}</button>
      </div>
      {survey ? <SurveyChoices survey={survey} chosen={chosen} setChosen={setChosen} /> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {survey ? (
        <button type="submit" className="secondary" disabled={busy || !(nStatements + nPdfs)}>
          {t("Add {{n}} statement(s) and {{m}} PDF(s)", { n: nStatements, m: nPdfs })}</button>
      ) : null}
    </form>
  );
}
