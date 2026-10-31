// 176 (plan F-statement-package): adding to a statement package takes its own survey - the files read for the package's
// party and period, what it already holds not offered again - then what is ticked is added. 231 (C3e): the finance
// domain's form for the statements rule's own way of adding (registered as its package part's `Add`, `./index.tsx`);
// until C3e in the shared add module (`ui/src/views/PackageAdd.tsx`), whose steps it uses.
import { useRef, useState, type FormEvent } from "react";
import { api, type Workpackage } from "../../api";
import { BrowseButton } from "../../components/BrowseButton";
import { FormActions } from "../../components/FormActions";
import { lazyPage } from "../../components/LazyPage";
import { t, useLocale } from "../../i18n";
import { addFailure, AddSteps, pathsOf, type AddSource } from "../../views/PackageAdd";
import type { StatementPackageSurvey } from "./api";

// 195 (plan G-tidy R5): a statement package's survey loads with the statement pages
const SurveyChoices = lazyPage(() => import("./StatementPackagePanel").then((m) => m.SurveyChoices));

export function AddStatements({ wp, source: initial = "folder", onDone, onCancel }: {
  wp: Workpackage; source?: AddSource; onDone: () => void; onCancel: () => void;
}) {
  useLocale();
  const [source, setSource] = useState<AddSource>(initial);
  const [folder, setFolder] = useState("");
  const [recursive, setRecursive] = useState(false);
  const [files, setFiles] = useState("");
  const [survey, setSurvey] = useState<StatementPackageSurvey | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lines = pathsOf(files);
  const paths = source === "folder" ? (folder.trim() ? [folder.trim()] : []) : lines;
  const deep = source === "folder" && recursive;
  // any change to what is surveyed drops the survey: the ticks belong to the files as they were read
  // 167 (review 160 U-3): a change also drops a survey still on its way (its late answer belongs to the files before)
  const asked = useRef(0);
  const reset = <T,>(set: (v: T) => void) => (v: T) => { set(v); asked.current += 1; setSurvey(null); setChosen(new Set()); };

  async function read() {
    setBusy(true);
    setError(null);
    try {
      const my = ++asked.current;
      const s = await api.packageStatementSurvey(wp.id, paths, deep);
      if (my !== asked.current) return;
      setSurvey(s);
      setChosen(new Set([...s.statements.filter((r) => r.chosen).map((r) => r.id), ...s.pdfs.filter((p) => p.chosen).map((p) => p.path)]));
    } catch (err) {
      setError(addFailure(err));
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
      await api.addPackageStatements(wp.id, { paths, expected_revision: wp.revision, ...(deep ? { recursive: true } : {}),
        statements: survey.statements.filter((r) => chosen.has(r.id)).map((r) => r.id),
        pdfs: survey.pdfs.filter((p) => chosen.has(p.path)).map((p) => p.path) });
      onDone();
    } catch (err) {
      setError(addFailure(err));
    } finally {
      setBusy(false);
    }
  }

  const nStatements = survey ? survey.statements.filter((r) => chosen.has(r.id)).length : 0;
  const nPdfs = survey ? survey.pdfs.filter((p) => chosen.has(p.path)).length : 0;
  return (
    <form className="add-flow inline-form" onSubmit={submit} aria-label={t("Add statements to the package")}>
      <AddSteps step={survey ? (nStatements + nPdfs ? 3 : 2) : 1} />
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
          <label className="check"><input type="checkbox" checked={recursive} onChange={(e) => reset(setRecursive)(e.target.checked)} /> {t("Include subfolders")}</label>
        </div>
      ) : (
        <div className="path-row">
          <label className="block grow">{t("The files' full paths, one per line")}
            <textarea value={files} onChange={(e) => reset(setFiles)(e.target.value)} rows={3} />
          </label>
          <BrowseButton kind="files" initial={lines[lines.length - 1]} onPick={(picked) => reset(setFiles)([...lines, ...picked].join("\n"))} />
        </div>
      )}
      {survey ? null : (
        <FormActions onCancel={onCancel} busy={busy}>
          <button type="button" className="primary" disabled={busy || !paths.length} onClick={() => void read()}>
            {busy && !survey ? t("Reading…") : t("Survey the files")}</button>
        </FormActions>
      )}
      {survey ? <SurveyChoices survey={survey} chosen={chosen} setChosen={setChosen} /> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {/* 263 (F1): one foot, "Cancel" and then the main step, on the right */}
      {survey ? (
        <FormActions onCancel={onCancel} busy={busy}>
          <button type="submit" className="primary" disabled={busy || !(nStatements + nPdfs)}>
            {t("Add {{n}} statement(s) and {{m}} PDF(s)", { n: nStatements, m: nPdfs })}</button>
        </FormActions>
      ) : null}
    </form>
  );
}
