import { useState } from "react";
import { api, ApiError } from "../api";
import { BrowseButton } from "../components/BrowseButton";
import { DocumentFormats } from "../components/DocumentFormats";
import { DataTable, linkOf } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { useActor } from "../hooks";
import { t, useLocale } from "../i18n";
import { Mailbox } from "./Mailbox";
import { RUN_STATUS, stepLabel } from "../labels";
import { go, type Route } from "../route";
import { WorkpackageDetail } from "./WorkpackageDetail";
import { ReconcileCreate } from "./reconcile/ReconcileCreate";

export function Workpackages({ route }: { route: Extract<Route, { view: "workpackages" }> }) {
  if (route.wpId) return <WorkpackageDetail route={route} wpId={route.wpId} />;
  return <WorkpackageList />;
}

function WorkpackageList() {
  useLocale();
  const [creating, setCreating] = useState(false);
  const [count, setCount] = useState<number | null>(null);
  const [archived, setArchived] = useState(false); // 058: hidden work packages are only shown on request
  const [mine, setMine] = useState(false); // 061: only those whose owner is the „Ki dolgozik?” (Who is working?) person
  const actor = useActor();
  const scope = { ...(archived ? { include_archived: "1" } : {}), ...(mine && actor ? { owner: actor } : {}) };
  return (
    <>
      <PageHeader title={t("Munkacsomagok")} badge={count !== null ? <span className="count">{count}</span> : null}
        summary={t("Egy munkacsomag iratai együtt futnak: feldolgozás, ellenőrzés, eredmény. A „Következő lépés” oszlop megmutatja, hol tart.")}
        actions={<button type="button" className="primary" onClick={() => setCreating((v) => !v)} aria-expanded={creating}>{t("Új munkacsomag")}</button>} />
      {creating ? <CreateForm onDone={(id) => go({ view: "workpackages", wpId: id, stage: "process" })} /> : null}
      <DataTable dataset="workpackages" label={t("Munkacsomagok")} onPage={(pg) => setCount(pg.total)} pollMs={10000}
        scope={Object.keys(scope).length ? scope : undefined}
        toolbar={<>
          <label className="check small" title={actor ? undefined : t("Előbb válaszd ki a neved fent")}>
            <input type="checkbox" checked={mine && Boolean(actor)} disabled={!actor} onChange={(e) => setMine(e.target.checked)} /> {t("Csak a saját csomagjaim")}
          </label>
          <label className="check small"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> {t("Elrejtett csomagok is")}</label>
        </>}
        cell={(col, row) => (col.key === "next_label" ? (
          // the next step in the chosen language (from the local service's code), with a link to the stage
          <a href={linkOf(col, row) ?? "#/workpackages"}>{stepLabel(String(row.next_code), row._next_params as Record<string, unknown>, String(row.next_label))}</a>
        ) : undefined)}
        emptyText={t("Még nincs munkacsomag. Az „Új munkacsomag” gombbal mappából, fájlokból vagy postafiókból hozhatsz létre.")} />
    </>
  );
}

// 081: exported for its tests (the subfolder switch and the Browse buttons)
export function CreateForm({ onDone }: { onDone: (id: string) => void }) {
  useLocale();
  const [mode, setMode] = useState<"folder" | "files" | "mailbox" | "reconcile">("folder");
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
    <section className="card create" aria-label={t("Új munkacsomag")}>
      <fieldset className="segmented">
        <legend className="sr-only">{t("Forrás")}</legend>
        <label><input type="radio" name="src" checked={mode === "folder"} onChange={() => setMode("folder")} /> {t("Documents from a folder")}</label>
        <label><input type="radio" name="src" checked={mode === "files"} onChange={() => setMode("files")} /> {t("Megadott fájlok")}</label>
        <label><input type="radio" name="src" checked={mode === "mailbox"} onChange={() => setMode("mailbox")} /> {t("Postafiókból")}</label>
        {/* 132: a reconciliation package pairs statement lines with invoices already processed */}
        <label><input type="radio" name="src" checked={mode === "reconcile"} onChange={() => setMode("reconcile")} /> {t("Reconciliation of statements and invoices")}</label>
      </fieldset>
      {mode === "reconcile" ? <ReconcileCreate onDone={(id) => onDone(id)} /> : mode === "mailbox" ? <Mailbox variant="pull" /> : (
        <form className="create" onSubmit={(e) => { e.preventDefault(); void submit(); }} aria-label={t("Mappa vagy fájlok")}>
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
      )}
    </section>
  );
}

export function RunStatus({ status }: { status: string }) {
  useLocale();
  return <span className={`status s-${status}`}>{RUN_STATUS[status] ?? status}</span>;
}
