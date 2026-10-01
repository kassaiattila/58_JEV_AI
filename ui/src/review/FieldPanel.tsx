// Field panel (045 K3b): to-dos, fields with a confidence band and a source marker, the selected field's source and
// alternatives, selection on the image → value, saving with a revision. The draft lives in the drafts.ts store (it
// survives switching items).
// 048: the line-item lists on separate tabs (ListTable), and the pack's checks on the saved, corrected data.
// 083 (the owner's trial): a tick (✓) and a cross (✗) right next to each field's value; a field's to-dos are shown at
// the field, only the document's to-dos stay at the top; a small filter above the fields.
import { useEffect, useRef, useState } from "react";
import { api, ApiError, getActor, NO_ACTOR, type Alternative, type CorrectionValue, type ItemResult, type Provenance } from "../api";
import { Icon } from "../components/Icon";
import { t, useLocale } from "../i18n";
import { checkText, editNumber, fieldLabel, reasonText, savedNumbers, tmap } from "../labels";
import { clearDraft, draftKey, isDirty, rebaseDraft, revertField, setField, setList, useDraft, type Draft } from "./drafts";
import { useResolve } from "./useResolve";
import { BAND_LABEL, type Band } from "./geometry";
import { EMPTY_FILTER, FIELD_FILTERS, FILTER_LABEL, isConfirmed, type FieldFilter } from "./fieldFilter";
import { fromRows, ListTable, toRows } from "./ListTable";
import { BAND_COLOR } from "./PageViewer";

const NUMERIC_KINDS = new Set(["money", "number"]);

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
 *  list: the whole list; if it equals the machine one, it is left out (reverts to the machine value). 081: an amount
 *  or a quantity equal to the machine value in its editing form ("35,56" for "35.56") is no change. */
export function buildSave(machine: Record<string, unknown>, previous: ItemResult["correction"], draft: Draft | undefined,
  lists: ItemResult["lists"] = {}, kinds: Record<string, string> = {}) {
  const fields: Record<string, CorrectionValue> = {};
  const sources: Record<string, number[]> = {};
  for (const [f, v] of Object.entries(previous.fields)) fields[f] = v === null || Array.isArray(v) ? v : String(v);
  for (const [f, ids] of Object.entries(previous.sources ?? {})) sources[f] = ids;
  for (const [f, v] of Object.entries(draft?.values ?? {})) {
    const m = machine[f] === null || machine[f] === undefined ? "" : String(machine[f]);
    const same = v === m || (NUMERIC_KINDS.has(kinds[f]) && v === editNumber(m));
    delete sources[f];
    if (same && !draft?.sources[f]) delete fields[f];
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
  /** 083: every simple field of the item (`fields` may be a filtered part of it); defaults to `fields`. */
  allFields?: string[];
  /** 083: the cross started fixing the field (the caller activates it, turns on selection on the image, focuses it). */
  onStartFix?: (field: string) => void;
  /** 083: the field filter above the fields (shown when given). */
  filter?: FieldFilter;
  counts?: Record<FieldFilter, number>;
  onFilter?: (filter: FieldFilter) => void;
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

  const kinds = result.kinds ?? {};
  // 081: an amount or a quantity is shown in its editing form ("35,56"), the way the local service reads it back
  const edit = (f: string, v: unknown) => (v === null || v === undefined ? "" : NUMERIC_KINDS.has(kinds[f]) ? editNumber(v) : String(v));
  const shown = (f: string) => draft?.values[f] ?? edit(f, result.effective[f]);

  function applySelection() {
    if (!activeField || !norm?.ok || norm.value === null) return;
    setField(key, base, activeField, edit(activeField, norm.value), selection.ids);
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
    const body = buildSave(machine, result.correction, draft, lists, kinds);
    try {
      const saved = await api.saveCorrection(result.run_id, result.item_id, {
        fields: body.fields, expected_revision: base, ...(Object.keys(body.sources).length ? { sources: body.sources } : {}),
      });
      clearDraft(key);
      // 081: the amounts typed now, as the local service read them ("28.000" → 28 000)
      const typed = Object.fromEntries(Object.keys(draft?.values ?? {}).map((f) => [f, saved.correction.fields[f]]));
      const numbers = savedNumbers(typed, kinds);
      setState({ kind: "saved", msg: numbers ? t("Mentve. Rögzített érték: {{values}}", { values: numbers }) : t("Mentve.") });
      p.onSaved();
    } catch (e) {
      reportSaveError(e);
    } finally {
      saving.current = false;
    }
  }

  function reportSaveError(e: unknown) {
    const err = e instanceof ApiError ? e : new ApiError(0, "error", String(e));
    setState({ kind: "error", msg: err.status === 409
      ? t("Közben más is mentett erre a tételre. A módosításaid megmaradtak; frissítsd, és mentsd újra.")
      : err.code === "ambiguous_number"
        ? t("Nem sikerült menteni: egy szám kétféleképpen is olvasható. Tizedesvesszővel (28,50) vagy tagolás nélkül (28000) írd be. A módosításaid megmaradtak.")
        : t("Nem sikerült menteni: {{reason}}. A módosításaid megmaradtak.", { reason: err.message }) });
    if (err.status === 409) p.onSaved();
  }

  /** 083: the tick. Saves this field only (its typed or selected value, if any; empty = the value is not on the
   *  document), records it as checked by a person, and closes its to-dos in this run. The other fields' unsaved changes
   *  stay in the working copy, on the new version. */
  async function confirmField(f: string) {
    if (conflict || readOnly || saving.current) return;
    if (!getActor()) {
      setState({ kind: "error", msg: t("Nem sikerült menteni: {{reason}}. A módosításaid megmaradtak.", { reason: t(NO_ACTOR) }) });
      document.getElementById("actor")?.focus();
      return;
    }
    setState({ kind: "saving" });
    saving.current = true;
    const own: Draft | undefined = draft && f in draft.values
      ? { baseRevision: draft.baseRevision, values: { [f]: draft.values[f] }, sources: draft.sources[f] ? { [f]: draft.sources[f] } : {} }
      : undefined;
    const body = buildSave(machine, result.correction, own, lists, kinds);
    try {
      const saved = await api.saveCorrection(result.run_id, result.item_id, {
        fields: body.fields, expected_revision: base, ...(Object.keys(body.sources).length ? { sources: body.sources } : {}), confirm: [f],
      });
      revertField(key, f);
      rebaseDraft(key, saved.correction.revision);
      setState({ kind: "saved", msg: t("Mentve: {{field}} ellenőrizve.", { field: fieldLabel(f) }) });
      p.onSaved();
    } catch (e) {
      reportSaveError(e);
    } finally {
      saving.current = false;
    }
  }

  /** 083: the cross. Empties the field and starts fixing it: the right value comes from the image, from another
   *  candidate or by typing, and the tick saves it. */
  function startFix(f: string) {
    setField(key, base, f, "", null);
    onActivate(f);
    p.onStartFix?.(f);
  }

  saveRef.current = () => void save();

  const { resolve, pending: resolving, error: resolveError } = useResolve(p.onResolved);

  // 083: a to-do about one simple field is shown at that field; the others (about the document) stay at the top
  const simpleFields = new Set(p.allFields ?? fields);
  const atField = (f: string) => result.open_reasons.filter((r) => r.field === f);
  const documentReasons = result.open_reasons.filter((r) => !r.field || !simpleFields.has(r.field));
  const prov: Provenance | undefined = activeField ? result.provenance[activeField] : undefined;
  const listRows = (f: string) => draft?.lists?.[f] ?? toRows(result.effective[f], lists[f].columns);
  const goRow = (f: string, row: number) => { p.onTab?.(f); setFocusRow({ row, seq: Date.now() }); };

  return (
    <section className="panel" aria-label={t("Teendők és mezők")}>
      {resolveError ? <p className="notice error" role="alert">{resolveError}</p> : null}
      {documentReasons.length ? (
        <ul className="issues" aria-label={t("Nyitott teendők ebben a futásban")}>
          {documentReasons.map((r) => (
            <li key={r.id} className="issue">
              <span>{reasonText(r.reason)}</span>
              <button type="button" className="secondary small-btn" disabled={resolving !== null} onClick={() => void resolve(r)}><Icon name="check" />{t("Rendezve")}</button>
            </li>
          ))}
        </ul>
      ) : result.open_reasons.length ? null : <p className="ok pad-s">{t("Ebben a futásban nincs nyitott teendő ezen a tételen.")}</p>}
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
      {p.filter && p.counts ? (
        <div className="field-filter" role="group" aria-label={t("Mezők szűrése")}>
          {FIELD_FILTERS.map((k) => (
            <button key={k} type="button" className="chip" aria-pressed={p.filter === k} onClick={() => p.onFilter?.(k)}>
              {FILTER_LABEL[k]} ({p.counts![k]})
            </button>
          ))}
        </div>
      ) : null}
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

      {!fields.length && p.filter ? <p className="muted small pad-s">{EMPTY_FILTER[p.filter]}</p> : null}
      <ol className="fields" aria-label={t("Mezők")}>
        {fields.map((f) => {
          const pv = result.provenance[f];
          const band = bandOf(f);
          const isActive = f === activeField;
          const edited = draft?.values[f] !== undefined;
          const label = fieldLabel(f);
          const todo = atField(f);
          return (
            <li key={f} ref={isActive ? activeRow : undefined} className={`frow ${isActive ? "active" : ""} ${todo.length ? "has-todo" : ""}`} onClick={() => onActivate(f)}>
              <div className="frow-head">
                <label htmlFor={`fv-${f}`}>{label}</label>
                <span className="chips">
                  {edited ? <span className="badge">{t("mentetlen")}</span>
                    : isConfirmed(result, f) ? <span className="badge ok-badge" title={t("Egy ember ellenőrizte ezt az értéket.")}><Icon name="check" />{t("ellenőrizve")}</span>
                    : pv?.corrected ? <span className="badge">{t("javítva")}</span> : null}
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
              <div className="frow-value">
                <input id={`fv-${f}`} value={shown(f)} readOnly={readOnly} onFocus={() => onActivate(f)}
                  onChange={(e) => setField(key, base, f, e.target.value, null)} />
                <button type="button" className="verdict verdict-ok" aria-label={t("{{field}}: helyes", { field: label })}
                  title={t("Helyes: mentés és ellenőrzöttnek jelölés (a mező teendői lezárulnak)")}
                  disabled={readOnly || conflict || state.kind === "saving"} onClick={(e) => { e.stopPropagation(); void confirmField(f); }}>
                  <Icon name="check" />
                </button>
                {edited ? (
                  <button type="button" className="verdict" aria-label={t("{{field}}: visszaállítás", { field: label })} title={t("Az eredeti érték visszaállítása")}
                    disabled={readOnly} onClick={(e) => { e.stopPropagation(); revertField(key, f); }}>
                    <Icon name="restore" />
                  </button>
                ) : (
                  <button type="button" className="verdict verdict-bad" aria-label={t("{{field}}: hibás, javítom", { field: label })}
                    title={t("Hibás: a mező kiürül, és a helyes értéket kijelölheted a képen vagy beírhatod")}
                    disabled={readOnly || conflict} onClick={(e) => { e.stopPropagation(); startFix(f); }}>
                    <Icon name="close" />
                  </button>
                )}
              </div>
              {todo.length ? (
                <ul className="field-issues" aria-label={t("{{field}}: teendők", { field: label })}>
                  {todo.map((r) => <li key={r.id}>{reasonText(r.reason)}</li>)}
                </ul>
              ) : null}
              {edited && shown(f) === "" ? (
                <p className="small muted fix-hint">{t("Jelöld ki a helyes értéket a képen, írd be, vagy válassz jelöltet; üresen hagyva a ✓ azt rögzíti, hogy az iraton nincs érték.")}</p>
              ) : null}
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
