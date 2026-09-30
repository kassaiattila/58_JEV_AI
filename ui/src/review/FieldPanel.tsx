// Field panel (045 K3b): to-dos, fields with a confidence band and a source marker, the selected field's source and
// alternatives, selection on the image → value, saving with a revision. The draft lives in the drafts.ts store (it
// survives switching items).
// 048: the line-item lists on separate tabs (ListTable), and the pack's checks on the saved, corrected data.
import { useEffect, useRef, useState } from "react";
import { api, ApiError, getActor, NO_ACTOR, type Alternative, type CorrectionValue, type ItemResult, type Provenance, type Reason } from "../api";
import { Icon } from "../components/Icon";
import { t, useLocale } from "../i18n";
import { checkText, fieldLabel, reasonText, tmap } from "../labels";
import { clearDraft, draftKey, isDirty, rebaseDraft, revertField, setField, setList, useDraft, type Draft } from "./drafts";
import { useResolve } from "./useResolve";
import { BAND_LABEL, type Band } from "./geometry";
import { fromRows, ListTable, toRows } from "./ListTable";
import { BAND_COLOR } from "./PageViewer";

export const UNLOCATED: Record<string, string> = tmap({
  approximate: "Az értéket nem találtuk meg szó szerint; a szaggatott keret azt a sort mutatja, ahonnan a gép választotta. Ellenőrizd a képen, és ha kell, jelöld ki a pontos helyét.",
  ambiguous: "Az érték több helyen szerepel az iraton; nem választottunk bizonytalan keretet. A lehetséges helyek a képen szaggatottan látszanak.",
  context_rejected: "Az értéket megtaláltuk, de egy másik mező címkéje mellett áll, ezért nem kereteztük. Ellenőrizd a képen.",
  not_found: "Ezt az értéket nem találtuk meg szó szerint az iraton. Ellenőrizd a képen, vagy jelöld ki a helyét.",
  no_value: "A mező üres: a gép nem talált hozzá értéket. Ha szerepel az iraton, jelöld ki a képen.",
  no_layer: "Ehhez az irathoz nincs szóréteg (korábbi futás vagy régi OCR-eredmény), ezért keret sem. Az értéket a képen ellenőrizd.",
  error: "A forráshely számítása nem sikerült; az értéket a képen ellenőrizd.",
});

/** The full set of corrections to save: the earlier corrections + the draft's differences from the machine value
 *  (empty = no value). The sources (selected words) only go with the fields that remain in the correction. Line-item
 *  list: the whole list; if it equals the machine one, it is left out (reverts to the machine value). */
export function buildSave(machine: Record<string, unknown>, previous: ItemResult["correction"], draft: Draft | undefined,
  lists: ItemResult["lists"] = {}) {
  const fields: Record<string, CorrectionValue> = {};
  const sources: Record<string, number[]> = {};
  for (const [f, v] of Object.entries(previous.fields)) fields[f] = v === null || Array.isArray(v) ? v : String(v);
  for (const [f, ids] of Object.entries(previous.sources ?? {})) sources[f] = ids;
  for (const [f, v] of Object.entries(draft?.values ?? {})) {
    const m = machine[f] === null || machine[f] === undefined ? "" : String(machine[f]);
    delete sources[f];
    if (v === m && !draft?.sources[f]) delete fields[f];
    else fields[f] = v.trim() === "" ? null : v;
    if (draft?.sources[f]) sources[f] = draft.sources[f];
  }
  for (const [f, rows] of Object.entries(draft?.lists ?? {})) {
    const cols = lists?.[f]?.columns ?? [];
    const value = fromRows(rows, cols);
    if (JSON.stringify(value) === JSON.stringify(fromRows(toRows(machine[f], cols), cols))) delete fields[f];
    else fields[f] = value;
  }
  for (const f of Object.keys(sources)) if (!(f in fields)) delete sources[f];
  return { fields, sources };
}

interface Props {
  result: ItemResult;
  fields: string[];
  bandOf: (f: string) => Band;
  activeField: string | null;
  onActivate: (f: string) => void;
  selection: { ids: number[]; text: string };
  onClearSelection: () => void;
  selectMode: boolean;
  onToggleSelect: () => void;
  onSaved: () => void;
  onResolved: () => void;
  onChooseAlternative: (field: string, alt: Alternative) => void;
  readOnly: boolean;
  hasWords: boolean;
  tab?: string; // "fields" or the name of a line-item list
  onRowPick?: (field: string, row: number) => void; // 053: picking a line item (the image jumps to the row's position)
  onTab?: (tab: string) => void;
}

/** 053: the row number of a selection keyed `list[n]`, if it belongs to the given list. */
export function rowOf(key: string | null, list: string): number | null {
  const m = key?.match(/^(.+)\[(\d+)\]$/);
  return m && m[1] === list ? Number(m[2]) : null;
}

export function FieldPanel(p: Props) {
  const { result, fields, bandOf, activeField, onActivate, selection, selectMode, readOnly } = p;
  useLocale();
  const key = draftKey(result.run_id, result.item_id);
  const draft = useDraft(key);
  const base = result.correction.revision;
  const conflict = Boolean(draft && draft.baseRevision !== base);
  const dirty = isDirty(draft);
  const lists = result.lists ?? {};
  const listNames = Object.keys(lists);
  const tab = p.tab && (p.tab === "fields" || p.tab in lists) ? p.tab : "fields";
  const [focusRow, setFocusRow] = useState<{ row: number; seq: number } | null>(null);
  const failed = (result.checks ?? []).filter((c) => !c.ok);
  const machine = result.extraction?.datapoints ?? {};
  const [state, setState] = useState<{ kind: "idle" | "saving" | "saved" | "error"; msg?: string }>({ kind: "idle" });
  const [norm, setNorm] = useState<{ text: string; value: string | null; ok: boolean } | null>(null);
  const activeRow = useRef<HTMLLIElement | null>(null);

  useEffect(() => { activeRow.current?.scrollIntoView?.({ block: "nearest" }); }, [activeField]);

  // Ctrl+Enter: save (inside an input box too), V4's keyboard shortcut
  const saveRef = useRef<() => void>(() => {});
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      // 066 Á23: the auto-repeat of a held-down key does not start another save
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); if (!e.repeat) saveRef.current(); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  // selected text → a value matching the field's kind (the local service normalises it)
  useEffect(() => {
    if (!activeField || !selection.text || !result.extraction) { setNorm(null); return; }
    let alive = true;
    const timer = window.setTimeout(() => {
      api.normalize(result.extraction!.doc_type, activeField, selection.text)
        .then((r) => alive && setNorm({ text: selection.text, value: r.value, ok: r.ok }))
        .catch(() => alive && setNorm({ text: selection.text, value: null, ok: false }));
    }, 150);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [activeField, selection.text, result.extraction]);

  const shown = (f: string) => draft?.values[f] ?? (result.effective[f] === null || result.effective[f] === undefined ? "" : String(result.effective[f]));

  function applySelection() {
    if (!activeField || !norm?.ok || norm.value === null) return;
    setField(key, base, activeField, norm.value, selection.ids);
    p.onClearSelection();
  }

  const saving = useRef(false); // 066 Á23: synchronous lock; Ctrl+Enter bypassed the disabled button and saved twice
  async function save() {
    if (!dirty || conflict || readOnly || saving.current) return;
    if (!getActor()) {
      setState({ kind: "error", msg: t("Nem sikerült menteni: {{reason}}. A módosításaid megmaradtak.", { reason: t(NO_ACTOR) }) });
      document.getElementById("actor")?.focus();
      return;
    }
    setState({ kind: "saving" });
    saving.current = true;
    const body = buildSave(machine, result.correction, draft, lists);
    try {
      await api.saveCorrection(result.run_id, result.item_id, {
        fields: body.fields, expected_revision: base, ...(Object.keys(body.sources).length ? { sources: body.sources } : {}),
      });
      clearDraft(key);
      setState({ kind: "saved", msg: t("Mentve.") });
      p.onSaved();
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, "error", String(e));
      setState({ kind: "error", msg: err.status === 409
        ? t("Közben más is mentett erre a tételre. A módosításaid megmaradtak; frissítsd, és mentsd újra.")
        : t("Nem sikerült menteni: {{reason}}. A módosításaid megmaradtak.", { reason: err.message }) });
      if (err.status === 409) p.onSaved();
    } finally {
      saving.current = false;
    }
  }

  saveRef.current = () => void save();

  const { resolve, pending: resolving, error: resolveError } = useResolve(p.onResolved);

  const reasonField = (r: Reason) => r.reason.split(":")[2];
  const prov: Provenance | undefined = activeField ? result.provenance[activeField] : undefined;
  const listRows = (f: string) => draft?.lists?.[f] ?? toRows(result.effective[f], lists[f].columns);
  const goRow = (f: string, row: number) => { p.onTab?.(f); setFocusRow({ row, seq: Date.now() }); };

  return (
    <section className="panel" aria-label={t("Teendők és mezők")}>
      {resolveError ? <p className="notice error" role="alert">{resolveError}</p> : null}
      {result.open_reasons.length ? (
        <ul className="issues" aria-label={t("Nyitott teendők ebben a futásban")}>
          {result.open_reasons.map((r) => (
            <li key={r.id} className="issue">
              <button type="button" className="link-btn" onClick={() => reasonField(r) && onActivate(reasonField(r))}>{reasonText(r.reason)}</button>
              <button type="button" className="secondary small-btn" disabled={resolving !== null} onClick={() => void resolve(r)}><Icon name="check" />{t("Rendezve")}</button>
            </li>
          ))}
        </ul>
      ) : <p className="ok pad-s">{t("Ebben a futásban nincs nyitott teendő ezen a tételen.")}</p>}
      {result.earlier_open_reasons.length ? (
        <details className="details">
          <summary>{t("Korábbi teendők az iraton ({{n}}) — ezt a futást nem akadályozzák", { n: result.earlier_open_reasons.length })}</summary>
          <ul className="issues">
            {result.earlier_open_reasons.map((r) => (
              <li key={r.id} className="issue quiet-issue"><span>{reasonText(r.reason)}</span>
                <button type="button" className="quiet small-btn" disabled={resolving !== null} onClick={() => void resolve(r)}>{t("Rendezve")}</button></li>
            ))}
          </ul>
        </details>
      ) : null}

      {failed.length ? (
        <ul className="issues checks" aria-label={t("Ellenőrzések a mentett adaton")}>
          {failed.map((c) => (
            <li key={c.name} className="issue">
              <span className="small">{checkText(c.code, c.detail)}{c.advisory ? ` — ${t("csak jelzés, nem teendő")}` : ""}</span>
              {Object.entries(c.rows ?? {}).flatMap(([f, rows]) => rows.map((n) => (
                <button key={`${f}:${n}`} type="button" className="secondary small-btn" onClick={() => goRow(f, n)}>{t("{{n}}. sor", { n })}</button>
              )))}
            </li>
          ))}
        </ul>
      ) : null}

      {listNames.length ? (
        <div className="tabs panel-tabs" role="tablist" aria-label={t("Mezők és tételes listák")}>
          {["fields", ...listNames].map((name) => {
            const n = name === "fields" ? null : listRows(name).length;
            const edited = name === "fields" ? Object.keys(draft?.values ?? {}).length > 0 : draft?.lists?.[name] !== undefined;
            return (
              <button key={name} type="button" role="tab" className="tab" aria-selected={tab === name} onClick={() => p.onTab?.(name)}>
                {name === "fields" ? t("Mezők") : `${fieldLabel(name)} (${n})`}{edited ? " •" : ""}
              </button>
            );
          })}
        </div>
      ) : null}

      {tab !== "fields" ? (
        <ListTable field={tab} columns={lists[tab].columns} rows={listRows(tab)}
          badRows={(result.checks ?? []).flatMap((c) => (c.ok ? [] : c.rows?.[tab] ?? []))} focusRow={focusRow}
          activeRow={rowOf(activeField, tab)} onRowPick={(n) => p.onRowPick?.(tab, n)}
          edited={draft?.lists?.[tab] !== undefined} corrected={Boolean(result.provenance[tab]?.corrected)} readOnly={readOnly}
          onChange={(rows) => setList(key, base, tab, rows)} onRevert={() => revertField(key, tab)} />
      ) : <>
      <div className="panel-tools">
        <button type="button" className={selectMode ? "primary small-btn" : "secondary small-btn"} aria-pressed={selectMode}
          disabled={!p.hasWords || readOnly} onClick={p.onToggleSelect}
          title={p.hasWords ? t("Szavak kijelölése a képen (kattintás vagy téglalap) — S") : t("Ehhez az irathoz nincs szóréteg")}>
          {selectMode ? t("Kijelölés bekapcsolva") : t("Kijelölés a képen")}
        </button>
        <span className="legend" aria-label={t("A modellbecslés színei")}>
          {(["confident", "check", "likely_wrong"] as Band[]).map((b) => (
            <span key={b} className="legend-item"><i style={{ borderColor: BAND_COLOR[b] }} />{BAND_LABEL[b]}</span>
          ))}
        </span>
      </div>

      {selectMode && selection.ids.length ? (
        <div className="selection-bar" role="status">
          <div className="small">{t("Kijelölve:")} „{selection.text}”</div>
          {activeField ? (
            norm && norm.text === selection.text ? (
              norm.ok ? (
                <div className="button-row">
                  <span className="small">→ {fieldLabel(activeField)}: <strong className="mono">{norm.value}</strong></span>
                  <button type="button" className="primary small-btn" onClick={applySelection}>{t("Beírás a mezőbe")}</button>
                  <button type="button" className="quiet small-btn" onClick={p.onClearSelection}>{t("Mégse")}</button>
                </div>
              ) : <div className="error-text small">{t("Ez a szöveg nem értelmezhető „{{field}}” értékként. Jelölj ki mást.", { field: fieldLabel(activeField) })}</div>
            ) : <div className="muted small">{t("Értelmezés…")}</div>
          ) : <div className="muted small">{t("Válaszd ki, melyik mezőbe kerüljön.")}</div>}
        </div>
      ) : null}

      <ol className="fields" aria-label={t("Mezők")}>
        {fields.map((f) => {
          const pv = result.provenance[f];
          const band = bandOf(f);
          const isActive = f === activeField;
          const edited = draft?.values[f] !== undefined;
          return (
            <li key={f} ref={isActive ? activeRow : undefined} className={`frow ${isActive ? "active" : ""}`} onClick={() => onActivate(f)}>
              <div className="frow-head">
                <label htmlFor={`fv-${f}`}>{fieldLabel(f)}</label>
                <span className="chips">
                  {edited ? <span className="badge">{t("mentetlen")}</span> : pv?.corrected ? <span className="badge">{t("javítva")}</span> : null}
                  <span className="band" style={{ color: BAND_COLOR[band], borderColor: BAND_COLOR[band] }}
                    title={pv?.confidence != null ? t("Modellbecslés: {{p}}%", { p: Math.round(pv.confidence * 100) }) : t("Nincs becslés")}>
                    {pv?.confidence != null ? `${Math.round(pv.confidence * 100)}%` : "–"}
                  </span>
                  <span className={`src ${pv?.status === "located" ? "src-ok" : pv?.status === "approximate" ? "src-approx" : "src-none"}`}
                    title={pv?.status === "located" ? t("Forrás: {{how}}", { how: pv.method === "manual" ? t("kézi kijelölés") : pv.method === "pick" ? t("a választott jelölt helye") : t("keresés") }) : UNLOCATED[pv?.status ?? "no_layer"]}>
                    {pv?.status === "located" ? "◉" : pv?.status === "approximate" ? "◎" : "○"}
                  </span>
                </span>
              </div>
              <input id={`fv-${f}`} value={shown(f)} readOnly={readOnly} onFocus={() => onActivate(f)}
                onChange={(e) => setField(key, base, f, e.target.value, null)} />
              {isActive ? (
                <div className="fdetail">
                  {prov?.status === "located" && prov.quote ? <div className="small">{t("Forrásszöveg:")} „{prov.quote}”{prov.page ? ` · ${t("{{n}}. oldal", { n: prov.page })}` : ""}
                      {prov.multiple && prov.multiple > 1 ? ` · ${t("{{n}} helyen szerepel az iraton; a keret a legvalószínűbbön, a többi szaggatottan", { n: prov.multiple })}` : ""}</div>
                    : <div className="small muted">{UNLOCATED[prov?.status ?? "no_layer"]}{prov?.status === "approximate" && prov.quote ? ` ${t("A sor:")} „${prov.quote}”.` : ""}</div>}
                  {edited || pv?.corrected ? <div className="small muted">{t("Gépi érték:")} {machine[f] === null || machine[f] === undefined ? "–" : String(machine[f])}</div> : null}
                  {prov?.alternatives?.length ? (
                    <div className="alts">
                      <span className="small muted">{t("Más jelöltek:")}</span>
                      {prov.alternatives.map((a, i) => (
                        <button key={i} type="button" className="secondary small-btn" disabled={readOnly}
                          onClick={(e) => { e.stopPropagation(); p.onChooseAlternative(f, a); }}>
                          {a.machine ? t("gépi érték helye") : a.value ?? a.quote}{a.p != null ? ` · ${Math.round(a.p * 100)}%` : ""}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {edited ? <button type="button" className="quiet small-btn" onClick={(e) => { e.stopPropagation(); revertField(key, f); }}>{t("Visszaállítás")}</button> : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
      </>}

      <div className="actions">
        {readOnly ? <p className="muted small">{t("A jóváhagyott futás javítása le van zárva.")}</p> : (
          <>
            {conflict ? (
              <div className="notice error small" role="alert">
                {t("A tételre közben újabb javítás került (verzió {{rev}}). A munkapéldányod megmaradt.", { rev: base })}
                <div className="button-row">
                  <button type="button" className="secondary small-btn" onClick={() => rebaseDraft(key, base)}>{t("Alkalmazás az új verzióra")}</button>
                  <button type="button" className="quiet small-btn" onClick={() => clearDraft(key)}>{t("Munkapéldány elvetése")}</button>
                </div>
              </div>
            ) : null}
            <button type="button" className="primary" disabled={!dirty || conflict || state.kind === "saving"} onClick={() => void save()}>
              {state.kind === "saving" ? t("Mentés…") : t("Javítás mentése")} <span className="kbd">Ctrl+Enter</span>
            </button>
            {dirty ? <button type="button" className="quiet small-btn" onClick={() => clearDraft(key)}>{t("Minden módosítás elvetése")}</button> : null}
          </>
        )}
        <p role="status" className={`save-state ${state.kind === "error" ? "error" : ""}`}>
          {state.msg ?? (dirty ? t("Mentetlen módosítás — tételváltáskor is megmarad.") : t("Javítás verziója: {{rev}}", { rev: base }))}
        </p>
      </div>
    </section>
  );
}
