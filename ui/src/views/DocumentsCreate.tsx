// A documents package from a folder (its direct contents, or with the subfolders) or from given files (081: the
// Windows pickers). 146: taken out of the new work package form, so the new work wizard shows it as the documents
// template's last step.
import { useState } from "react";
import { api, ApiError } from "../api";
import { BrowseButton } from "../components/BrowseButton";
import { DocumentFormats } from "../components/DocumentFormats";
import { t, useLocale } from "../i18n";

export function DocumentsCreate({ onDone }: { onDone: (id: string) => void }) {
  useLocale();
  const [mode, setMode] = useState<"folder" | "files">("folder");
  const [folder, setFolder] = useState("");
  const [recursive, setRecursive] = useState(false);
  const [files, setFiles] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lines = files.split(/\r?\n/).map((s) => s.trim().replace(/^"|"$/g, "")).filter(Boolean);

  // 081: the picked files are added after the lines already there, each path only once
  function addFiles(picked: string[]) {
    const seen = new Set(lines.map((s) => s.toLowerCase()));
    setFiles([...lines, ...picked.filter((p) => !seen.has(p.toLowerCase()))].join("\n"));
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const res = mode === "folder"
        ? await api.createFromFolder(folder.trim(), name.trim() || undefined, recursive)
        : await api.createFromFiles(lines, name.trim());
      onDone(res.workpackage.id);
    } catch (e) {
      const err = e as ApiError;
      setError(err.code === "forbidden_path"
        ? t("Ez a mappa nincs az engedélyezett helyek között (configs/service.json, vagy a JAV_API_ROOTS környezeti változó).")
        : err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="create" onSubmit={(e) => { e.preventDefault(); void submit(); }} aria-label={t("Mappa vagy fájlok")}>
      <fieldset className="segmented">
        <legend className="sr-only">{t("Forrás")}</legend>
        <label><input type="radio" name="src" checked={mode === "folder"} onChange={() => setMode("folder")} /> {t("Documents from a folder")}</label>
        <label><input type="radio" name="src" checked={mode === "files"} onChange={() => setMode("files")} /> {t("Megadott fájlok")}</label>
      </fieldset>
      <DocumentFormats />
      {mode === "folder" ? (
        <>
          <div className="path-row">
            <label className="block grow">{t("Mappa teljes útvonala")}
              <input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder={t("C:\\…\\szamlak\\2026-09")} required />
            </label>
            <BrowseButton kind="folder" initial={folder} onPick={([p]) => setFolder(p)} />
          </div>
          <label className="check"><input type="checkbox" checked={recursive} onChange={(e) => setRecursive(e.target.checked)} /> {t("Almappák is")}</label>
        </>
      ) : (
        <div className="path-row">
          <label className="block grow">{t("Fájlok teljes útvonala, soronként egy")}
            <textarea value={files} onChange={(e) => setFiles(e.target.value)} rows={4} required />
          </label>
          <BrowseButton kind="files" initial={lines[lines.length - 1]} onPick={addFiles} />
        </div>
      )}
      <label className="block">{t("Név")} {mode === "folder" ? <span className="muted">{t("(elhagyható: a mappa neve)")}</span> : null}
        <input value={name} onChange={(e) => setName(e.target.value)} required={mode === "files"} maxLength={200} />
      </label>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      <button type="submit" className="primary" disabled={busy}>{busy ? t("Létrehozás…") : t("Létrehozás")}</button>
    </form>
  );
}
