// Work folders (057, following how the legacy V4 „Figyelt mappák” (Watched folders) work): per folder a name, path,
// active flag, subfolders, packaging (one shared package / daily packages) and check interval (080: the package gets the default processing settings). Draft → save or
// discard; with unsaved changes, leaving the page or following an internal link asks for confirmation (the V4 pattern).
// The path can be any existing folder (061 decision; the restriction can be switched back on in the local service's
// settings); the worker checks the folder at intervals, and no paid run starts on its own. 078: below the list, the output
// folder of the content-named copies. 081: every path can be picked with the system's folder picker (Browse…).
import { useEffect, useState } from "react";
import { api, ApiError, getActor, NO_ACTOR, type WatchedFolder } from "../../api";
import { BrowseButton } from "../../components/BrowseButton";
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
      if (a && !window.confirm(t("A munkamappák módosításai nincsenek mentve. Elveted őket?"))) { e.preventDefault(); e.stopPropagation(); }
    };
    window.addEventListener("beforeunload", unload);
    document.addEventListener("click", click, true);
    return () => { window.removeEventListener("beforeunload", unload); document.removeEventListener("click", click, true); };
  }, [dirty]);

  const set = (i: number, patch: Partial<WatchedFolder>) => setDraft((d) => d.map((f, j) => (j === i ? { ...f, ...patch } : f)));

  async function save() {
    if (!getActor()) { setMsg({ error: true, text: t("Nem menthető: {{reason}}.", { reason: t(NO_ACTOR) }) }); return; }
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.saveFolders(draft);
      setDraft(res.folders);
      setMsg({ error: false, text: t("Mentve. A feldolgozó a gyakoriság szerint nézi át a mappákat.") });
      data.reload();
    } catch (e) {
      const err = e as ApiError;
      setMsg({ error: true, text: err.code === "forbidden_path" ? t("Egy útvonal az engedélyezett helyeken kívül van (lent látszanak).")
        : err.code === "folder_overlap" ? t("Egy munkamappa nem lehet a kimeneti mappán belül, és nem is tartalmazhatja (lent).") : err.message });
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
          ? t("Átnézve: {{n}} új irat, {{settling}} még íródik (a következő átnézésre marad).", { n: r.new ?? 0, settling: r.settling })
          : t("Átnézve: {{n}} új irat.", { n: r.new ?? 0 }))
        : r.error ?? t("Hiba") });
      data.reload();
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
    }
  }

  return (
    <section className="stage-stack" aria-label={t("Munkamappák")}>
      <p className="muted small">{t("A feldolgozó a megadott gyakorisággal átnézi a mappát, és az új PDF-ekből munkacsomag lesz (vagy a meglévő bővül). A forrásmappához csak olvasásra nyúl. A csomag az alap feldolgozási beállításokkal jön létre (a csomagon módosíthatók), de fizetős futás nem indul magától.")}</p>
      {data.error ? <p className="notice error">{data.error.message}</p> : null}
      {draft.map((f, i) => (
        <fieldset key={f.id ?? `new-${i}`} className="card wide folder-card">
          <legend>{f.name || t("Új munkamappa")}</legend>
          <div className="form-row">
            <label className="block">{t("Név")}<input value={f.name} maxLength={160} placeholder={t("(üresen: a mappa neve)")} onChange={(e) => set(i, { name: e.target.value })} /></label>
            <label className="block grow">{t("Mappa teljes útvonala")}<input value={f.path} maxLength={1024} required onChange={(e) => set(i, { path: e.target.value })} /></label>
            <BrowseButton kind="folder" initial={f.path} onPick={([p]) => set(i, { path: p })} />
          </div>
          <div className="form-row">
            <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => set(i, { enabled: e.target.checked })} /> {t("Aktív")}</label>
            <label className="check"><input type="checkbox" checked={f.recursive} onChange={(e) => set(i, { recursive: e.target.checked })} /> {t("Almappák is")}</label>
            <fieldset className="segmented">
              <legend className="sr-only">{t("Csomagolás")}</legend>
              <label><input type="radio" name={`mode-${i}`} checked={f.batch_mode === "folder"} onChange={() => set(i, { batch_mode: "folder" })} /> {t("Egy közös csomag")}</label>
              <label><input type="radio" name={`mode-${i}`} checked={f.batch_mode === "daily"} onChange={() => set(i, { batch_mode: "daily" })} /> {t("Napi csomagok")}</label>
            </fieldset>
          </div>
          <div className="form-row">
            <Picker label={t("Átnézés")} value={String(f.interval_min)} options={intervals().map(([m, label]) => ({ value: String(m), label }))}
              onChange={(v) => set(i, { interval_min: Number(v) })} />
          </div>
          <div className="button-row">
            {f.id && baseline.some((b) => b.id === f.id) ? <button type="button" className="secondary small-btn" disabled={dirty} title={dirty ? t("Előbb mentsd a módosításokat") : undefined}
              onClick={() => void scan(f.id!)}>{t("Átnézés most")}</button> : null}
            <button type="button" className="quiet small-btn" onClick={() => setDraft((d) => d.filter((_, j) => j !== i))}>{t("Eltávolítás")}</button>
            <span className="muted small">
              {f.last_at ? <>{t("Legutóbb: {{when}}", { when: when(f.last_at) })} · {f.last_status === "error" ? <span className="error-text">{f.last_result?.error}</span>
                : t("{{n}} új irat", { n: f.last_result?.new ?? 0 })}{f.last_result?.workpackage ? <> · <a href={`#/workpackages/${f.last_result.workpackage}`}>{t("csomag")}</a></> : null}</> : t("Még nem nézte át.")}
            </span>
          </div>
        </fieldset>
      ))}
      <div className="button-row">
        <button type="button" className="secondary" onClick={() => setDraft((d) => [...d, { ...EMPTY }])}><Icon name="plus" />{t("Munkamappa hozzáadása")}</button>
        <span className="dt-spacer" />
        <button type="button" className="secondary" disabled={!dirty || busy} onClick={() => setDraft(baseline)}>{t("Módosítások elvetése")}</button>
        <button type="button" className="primary" disabled={!dirty || busy} onClick={() => void save()}>{busy ? t("Mentés…") : t("Mentés")}</button>
      </div>
      <p className="muted small" role="status">{dirty ? t("Mentetlen módosítás van.") : ""}</p>
      {msg ? <p className={msg.error ? "notice error" : "notice"} role={msg.error ? "alert" : "status"}>{msg.text}</p> : null}
      {/* 061: by default there is no folder restriction; the list of locations only shows when it is switched on */}
      {data.data?.roots.length ? <p className="muted small">{t("Engedélyezett helyek: {{roots}}", { roots: data.data.roots.join(" · ") })}</p> : null}
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
    if (!getActor()) { setMsg({ error: true, text: t("Nem menthető: {{reason}}.", { reason: t(NO_ACTOR) }) }); return; }
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.saveOutputFolder(path.trim() || null);
      setDraft(res.path ?? "");
      setMsg({ error: false, text: res.path ? t("Mentve.") : t("A kimeneti mappa törölve.") });
      data.reload();
    } catch (e) {
      const err = e as ApiError;
      setMsg({ error: true, text: err.code === "folder_overlap" ? t("A kimeneti mappa és egy figyelt munkamappa nem lehet egymásban (a figyelő újra felvenné a másolatokat), és a program saját adatmappáiban sem lehet.")
        : err.code === "forbidden_path" ? t("Egy útvonal az engedélyezett helyeken kívül van (lent látszanak).") : err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset className="card wide folder-card" aria-label={t("Kimeneti mappa")}>
      <legend>{t("Kimeneti mappa")}</legend>
      <p className="muted small">{t("Ide kerülnek az iratok tartalom szerinti nevű másolatai (Eredmény › Fájlnevek). Minden kiírás új almappát kap; a program itt semmit nem ír felül és nem töröl. Nem lehet figyelt munkamappán belül.")}</p>
      <div className="form-row">
        <label className="block grow">{t("Mappa teljes útvonala")}<input value={path} maxLength={1024} placeholder={t("(üresen: nincs kimeneti mappa)")} onChange={(e) => setDraft(e.target.value)} /></label>
        <BrowseButton kind="folder" initial={path} onPick={([p]) => setDraft(p)} />
      </div>
      <div className="button-row">
        <span className="dt-spacer" />
        <button type="button" className="primary" disabled={busy || path.trim() === saved} onClick={() => void save()}>{busy ? t("Mentés…") : t("Mentés")}</button>
      </div>
      {msg ? <p className={msg.error ? "notice error" : "notice"} role={msg.error ? "alert" : "status"}>{msg.text}</p> : null}
    </fieldset>
  );
}
