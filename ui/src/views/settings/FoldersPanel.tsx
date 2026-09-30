// Work folders (057, following how the legacy V4 „Figyelt mappák” (Watched folders) work): per folder a name, path,
// active flag, subfolders, packaging (one shared package / daily packages), recipe and check interval. Draft → save or
// discard; with unsaved changes, leaving the page or following an internal link asks for confirmation (the V4 pattern).
// The path can be any existing folder (061 decision; the restriction can be switched back on in the local service's
// settings); the worker checks the folder at intervals, and no paid run starts on its own.
import { useEffect, useState } from "react";
import { api, ApiError, getActor, NO_ACTOR, type WatchedFolder } from "../../api";
import { Picker } from "../../components/Picker";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { intervals, when } from "../../labels";
import { Icon } from "../../components/Icon";

const EMPTY: WatchedFolder = { name: "", path: "", enabled: true, recursive: false, batch_mode: "folder", recipe_id: null, params: {}, interval_min: 15 };

export function FoldersPanel() {
  useLocale();
  const data = useLoad("folders", api.folders);
  const recipes = useLoad("recipes", api.recipes);
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
      setMsg({ error: true, text: err.code === "forbidden_path" ? t("Egy útvonal az engedélyezett helyeken kívül van (lent látszanak).") : err.message });
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

  const recipeOptions = [{ value: "", label: t("Nincs (a csomagon kell kiválasztani)") },
    ...(recipes.data?.recipes ?? []).map((r) => ({ value: r.id, label: `${t(r.title)} (v${r.version})` }))];
  return (
    <section className="stage-stack" aria-label={t("Munkamappák")}>
      <p className="muted small">{t("A feldolgozó a megadott gyakorisággal átnézi a mappát, és az új PDF-ekből munkacsomag lesz (vagy a meglévő bővül). A forrásmappához csak olvasásra nyúl. A csomag megkapja a receptet, de fizetős futás nem indul magától.")}</p>
      {data.error ? <p className="notice error">{data.error.message}</p> : null}
      {draft.map((f, i) => (
        <fieldset key={f.id ?? `new-${i}`} className="card wide folder-card">
          <legend>{f.name || t("Új munkamappa")}</legend>
          <div className="form-row">
            <label className="block">{t("Név")}<input value={f.name} maxLength={160} placeholder={t("(üresen: a mappa neve)")} onChange={(e) => set(i, { name: e.target.value })} /></label>
            <label className="block grow">{t("Mappa teljes útvonala")}<input value={f.path} maxLength={1024} required onChange={(e) => set(i, { path: e.target.value })} /></label>
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
            <Picker label={t("Recept")} value={f.recipe_id ?? ""} options={recipeOptions} onChange={(v) => set(i, { recipe_id: v || null })} />
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
    </section>
  );
}
