import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Alternative, type ItemResult, type Provenance, type RunItem, type Workpackage } from "../api";
import { DatasetPicker, runOption } from "../components/DatasetPicker";
import { NameModeSwitch, NameWarning } from "../components/NameCell";
import { useDataset, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { FIELD, fieldLabel, fold, ITEM_STATUS, itemName } from "../labels";
import { useNameMode } from "../names";
import { go } from "../route";
import { draftKey, getDraft, setField, useDraft } from "../review/drafts";
import { EmailReview } from "../review/EmailReview";
import { FieldPanel } from "../review/FieldPanel";
import { classifyFields, initialFilter, nextAfterConfirm, type FieldFilter } from "../review/fieldFilter";
import { bandOf, bandsFor, orderFields, selectionText, type Bands } from "../review/geometry";
import { BAND_COLOR, PageViewer } from "../review/PageViewer";
import { Split } from "../review/Split";

const DEFAULT_BANDS: Bands = { confident: 0.9, check: 0.5 };

/** The item's status in the list (062): based on the current to-dos, not on the moment of the run — an item that had
 *  to-dos at run time is „rendezve” (resolved) once its own to-dos have been closed since. */
export function queueStatus(res: Pick<RunItem, "status" | "final_status"> | undefined, openOwn: number): string {
  if (!res) return t("még nem futott");
  if (res.status !== "done") return ITEM_STATUS[res.status] ?? res.status;
  if (res.final_status === "done") return t("lezárva");
  return openOwn > 0 ? t("teendő") : t("rendezve");
}
// 048: the tab viewed last (fields / line list) stays on the next item too, if that item has such a list as well
let lastTab = "fields";
// 083: the field filter chosen last stays on the next item too, while that item has fields in it
let lastFilter: FieldFilter | null = null;

/** The notice above the page view when the original file changed or disappeared since the document was added: with a
 *  source instance the document is still shown (the copy the result was made from); without one it cannot be. */
export function sourceFileNote(sf: ItemResult["source_file"]): string | null {
  if (!sf || sf.original === "same") return null;
  if (sf.copy) {
    return sf.original === "changed"
      ? t("Az eredeti fájl a felvétel óta megváltozott. Itt a felvételkori példány látható; az eredmény ebből készült.")
      : t("Az eredeti fájl a felvétel óta eltűnt vagy nem olvasható. Itt a felvételkori példány látható; az eredmény ebből készült.");
  }
  return sf.original === "changed"
    ? t("Az eredeti fájl a felvétel óta megváltozott, ezért nem jeleníthető meg (az irat még azelőtt került a csomagba, hogy a rendszer példányt tett volna el róla).")
    : t("Az eredeti fájl a felvétel óta eltűnt vagy nem olvasható, ezért nem jeleníthető meg (az irat még azelőtt került a csomagba, hogy a rendszer példányt tett volna el róla).");
}

function withNote(note: string | null, node: ReactNode): ReactNode {
  if (!note) return node;
  return <div className="viewer-stack"><p className="notice small" role="status">{note}</p>{node}</div>;
}

/** To-dos: the items on the left, the page image with the field frames in the middle, the to-dos and the fields on
 *  the right (045 K3b). We work on the result of one run (the latest by default); a correction belongs to that run. */
export function ReviewWorkspace({ wp, itemId }: { wp: Workpackage; itemId?: string }) {
  useLocale();
  const latest = useDataset("runs", { workpackage_id: wp.id }, { limit: 1 });
  const [runId, setRunId] = useState<string | null>(null);
  const chosen = runId ?? latest.data?.rows[0]?._key ?? null;
  const names = useNameMode();
  const view = useLoad(chosen ? `run:${chosen}:${names}` : null, () => api.run(chosen!, names));
  // 056 U1: the item list stays manageable even with several hundred items: filtering by name, only those with to-dos
  const [queueQ, setQueueQ] = useState("");
  const [onlyOpen, setOnlyOpen] = useState(false);

  if (latest.error) return <p className="notice error" role="alert">{latest.error.message}</p>;
  if (!latest.data) return <p className="muted">{t("Betöltés…")}</p>;
  if (latest.data.total === 0) {
    return <div className="empty">{t("Ezen a csomagon még nem futott feldolgozás, ezért nincs mit ellenőrizni. Indíts futást a")} <a href={`#/workpackages/${wp.id}/process`}>{t("Feldolgozás")}</a> {t("szakaszban.")}</div>;
  }
  if (!view.data) return view.error ? <p className="notice error">{view.error.message}</p> : <p className="muted">{t("Betöltés…")}</p>;

  const run = view.data.run;
  const items = run.input.items;
  const own = view.data.open_reasons;
  const earlier = view.data.earlier_open_reasons;
  const firstWithWork = items.find((i) => (own[i.item_id] ?? []).length > 0) ?? items[0];
  const selectedId = itemId ?? firstWithWork?.item_id;
  const selected = items.find((i) => i.item_id === selectedId);
  const index = items.findIndex((i) => i.item_id === selectedId);
  // 083: the next item with open to-dos in this run, after the current one (then from the start), for the keyboard and
  // the right panel
  const nextTodo = [...items.slice(index + 1), ...items.slice(0, Math.max(index, 0))].find((i) => (own[i.item_id] ?? []).length > 0);
  const pick = (id: string) => go({ view: "workpackages", wpId: wp.id, stage: "review", itemId: id });
  const ownTotal = Object.values(own).reduce((n, r) => n + r.length, 0);
  // 082: the unified name when chosen and already known; the original stays searchable and is in the tooltip
  const original = (i: (typeof items)[number]) => itemName(i, view.data?.titles);
  const unified = (i: (typeof items)[number]) => (names === "unified" ? view.data?.names?.[i.item_id] : undefined);
  const shown = (i: (typeof items)[number]) => unified(i)?.unified ?? original(i);
  const needle = fold(queueQ.trim());

  return (
    <>
      <div className="review-bar">
        <DatasetPicker dataset="runs" scope={{ workpackage_id: wp.id }} label={t("Futás")} hideLabel value={chosen} valueCol="run_id"
          toOption={runOption} onChange={setRunId} />
        <span className="muted small">{ownTotal ? t("{{n}} nyitott teendő ebben a futásban", { n: ownTotal }) : t("Ebben a futásban nincs nyitott teendő.")}</span>
        <a className="small" href={`#/runs/${run.run_id}`}>{t("A futás részletei")}</a>
        <NameModeSwitch />
        <span className="muted small kbd-help">{t("Tab / ↓ következő mező · Enter ✓ · Esc vissza · PageDown / PageUp tétel · Ctrl+Enter mentés")}</span>
      </div>
      <div className="review-grid">
        <nav className="queue" aria-label={t("Tételek")}>
          <div className="queue-filter">
            <input type="search" aria-label={t("Tétel keresése")} placeholder={t("Keresés {{n}} tétel között…", { n: items.length })} value={queueQ}
              onChange={(e) => setQueueQ(e.target.value)} />
            <label className="check small"><input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} />{t("csak teendős")}</label>
          </div>
          {items.filter((i) => (!onlyOpen || (own[i.item_id] ?? []).length > 0)
            && (!needle || fold(shown(i)).includes(needle) || fold(original(i)).includes(needle))).map((i) => {
            const n = (own[i.item_id] ?? []).length;
            const m = (earlier[i.item_id] ?? []).length;
            const res = run.items.find((x) => x.item_id === i.item_id);
            const u = unified(i);
            return (
              <QueueItem key={i.item_id} runId={run.run_id} itemId={i.item_id} name={shown(i)} active={i.item_id === selectedId}
                tip={u?.unified ? t("Eredeti név: {{name}}", { name: original(i) }) : undefined}
                warn={u?.state === "review" ? <NameWarning check={u.check} /> : null}
                status={queueStatus(res, n)}
                own={n} earlier={m} onClick={() => pick(i.item_id)} />
            );
          })}
        </nav>
        {!selected ? (
          <div className="empty">{t("A kért tétel ({{id}}) nem része ennek a futásnak. Válassz a listából.", { id: selectedId?.slice(0, 12) ?? "" })}</div>
        ) : (
          <ItemReview key={`${run.run_id}:${selected.item_id}`} wpId={wp.id} runId={run.run_id} itemId={selected.item_id}
            approved={Boolean(run.approval)} onChanged={view.reload}
            onNext={index < items.length - 1 ? () => pick(items[index + 1].item_id) : undefined}
            onPrev={index > 0 ? () => pick(items[index - 1].item_id) : undefined}
            onNextTodo={nextTodo ? () => pick(nextTodo.item_id) : undefined} />
        )}
      </div>
    </>
  );
}

function QueueItem({ runId, itemId, name, tip, warn, active, status, own, earlier, onClick }: {
  runId: string; itemId: string; name: string; tip?: string; warn?: ReactNode; active: boolean; status: string; own: number; earlier: number;
  onClick: () => void;
}) {
  useLocale();
  const draft = useDraft(draftKey(runId, itemId));
  return (
    <button type="button" className="work-item" aria-pressed={active} onClick={onClick}>
      <span className="work-title" title={tip ? `${name}
${tip}` : name}>{warn}{name}</span>
      <small>{status}</small>
      {own ? <span className="tag">{t("{{n}} teendő", { n: own })}</span> : null}
      {earlier ? <span className="tag quiet-tag" title={t("Korábbi futásból vagy mérésből nyitva maradt teendő ezen a tételen. Ennek a futásnak az állapotát és jóváhagyását nem befolyásolja.")}>{t("{{n}} korábbi teendő", { n: earlier })}</span> : null}
      {draft ? <span className="tag draft-tag">{t("mentetlen")}</span> : null}
    </button>
  );
}

function ItemReview({ wpId, runId, itemId, approved, onChanged, onNext, onPrev, onNextTodo }: {
  wpId: string; runId: string; itemId: string; approved: boolean; onChanged: () => void; onNext?: () => void; onPrev?: () => void;
  onNextTodo?: () => void;
}) {
  useLocale();
  const res = useLoad(`item:${runId}:${itemId}`, () => api.item(runId, itemId));
  const settings = useLoad("settings", api.settings);
  // 083 (the owner's decision): selection on the image is always on when the document has a word layer
  const selectMode = Boolean(res.data?.source);
  const words = useLoad(selectMode ? `words:${runId}:${itemId}` : null, () => api.words(runId, itemId));
  const [active, setActive] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const [selected, setSelected] = useState<number[]>([]);
  const [tab, setTabState] = useState(lastTab);
  const setTab = useCallback((next: string) => { lastTab = next; setTabState(next); }, []);
  const data = res.data;
  const onList = tab !== "fields" && Boolean(data?.lists?.[tab]);
  const bands = settings.data?.confidence_bands ?? DEFAULT_BANDS;
  const key = draftKey(runId, itemId);

  const band = useCallback((f: string) => {
    const p = data?.provenance[f];
    return bandOf(p?.confidence, bandsFor(p, bands), Boolean(p?.corrected) || getDraft(key)?.values[f] !== undefined);
  }, [data, bands, key]);

  const allFields = useMemo(() => {
    const machine = data?.extraction?.datapoints ?? {};
    const order = Object.keys(FIELD);
    // only fields with a simple value (line items and other compound fields do not belong here)
    const scalar = Object.keys(machine).filter((f) => machine[f] === null || typeof machine[f] !== "object");
    const base = scalar.sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
    const reasonFields = new Set((data?.open_reasons ?? []).map((r) => r.field).filter((f): f is string => Boolean(f)));
    return orderFields(base, reasonFields, band);
  }, [data, band]);

  // 083: the field filter (Javítandó / Bizonytalan / Mind). The item opens on the filter chosen last while it has
  // fields here, otherwise on the fields to fix, otherwise on all; after that the choice stays on this item even when
  // its last field is confirmed (the panel then says that nothing is left).
  const groups = useMemo(() => (data ? classifyFields(allFields, data, bands) : null), [data, allFields, bands]);
  const counts = groups ? { fix: groups.fix.length, uncertain: groups.uncertain.length, all: groups.all.length } : null;
  const [filter, setFilterState] = useState<FieldFilter | null>(null);
  useEffect(() => {
    if (counts && filter === null) setFilterState(initialFilter(counts, lastFilter));
  }, [counts, filter]);
  const chooseFilter = useCallback((next: FieldFilter) => { lastFilter = next; setFilterState(next); }, []);
  const fields = groups && filter ? groups[filter] : allFields;

  const activate = useCallback((f: string) => {
    setActive(f);
    setFocusRequest((n) => n + 1);
  }, []);

  // 083: the keyboard works in the field's box: the cursor goes into it with its text selected (typing replaces it)
  const focusField = useCallback((f: string) => {
    activate(f);
    window.requestAnimationFrame(() => {
      const el = document.getElementById(`fv-${f}`) as HTMLInputElement | null;
      el?.focus();
      el?.select();
    });
  }, [activate]);

  // on first opening (once the filter is set), the most important field (to-do > weak estimate > first), with the cursor
  // in it; 083: after Enter confirmed a field, the next field (or, after the last, the next item with to-dos); when the
  // active field leaves the filter otherwise (confirmed with the tick), the field that took its place
  const shownBefore = useRef<string[]>([]);
  const advance = useRef<{ field: string; before: string[]; revision: number } | null>(null);
  useEffect(() => {
    const pending = advance.current;
    if (pending && data && data.correction.revision >= pending.revision) {
      advance.current = null;
      const next = nextAfterConfirm(pending.before, fields, pending.field);
      if (next) focusField(next);
      else onNextTodo?.();
    } else if (data && filter !== null && active === null && fields.length) {
      focusField(fields[0]);
    } else if (active && !active.includes("[") && !fields.includes(active) && fields.length && !pending) {
      const i = shownBefore.current.indexOf(active);
      setActive(fields[Math.min(Math.max(i, 0), fields.length - 1)]);
    }
    shownBefore.current = fields;
  }, [data, fields, active, filter, focusField, onNextTodo]);

  const navigate = useCallback((delta: 1 | -1) => {
    const j = (active ? fields.indexOf(active) : -1) + delta;
    if (j < 0 || j >= fields.length) return false;
    focusField(fields[j]);
    return true;
  }, [active, fields, focusField]);

  const confirmed = useCallback((f: string, viaKeyboard: boolean, revision: number) => {
    if (viaKeyboard) advance.current = { field: f, before: fields, revision };
  }, [fields]);

  // 083: the cross: the field is being fixed — it is active, the cursor is in it (selection on the image is always on)
  const startFix = useCallback((f: string) => {
    activate(f);
    setSelected([]);
    window.requestAnimationFrame(() => document.getElementById(`fv-${f}`)?.focus());
  }, [activate]);

  // keyboard shortcuts. In a field's box the panel handles Tab, the arrows, Enter and Esc (FieldPanel); here: PageDown /
  // PageUp switch items (in a field's box too, 083), Esc first clears the selection on the image and then leaves the
  // box, and outside the boxes ↑/↓ (j/k) move between the fields, n/p switch items and Enter goes into the field
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      const typing = el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT");
      const inField = typing && el.id.startsWith("fv-");
      if ((e.key === "PageDown" || e.key === "PageUp") && (!typing || inField) && !(e.ctrlKey || e.metaKey || e.altKey)) {
        e.preventDefault();
        (e.key === "PageDown" ? onNext : onPrev)?.();
        return;
      }
      if (e.key === "Escape") {
        if (selected.length) setSelected([]);
        else if (typing) (el as HTMLInputElement).blur();
        return;
      }
      if (typing || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
      if (onList && e.key !== "n" && e.key !== "p") return; // on the line list tab only item switching works
      const i = active ? fields.indexOf(active) : -1;
      if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); if (fields.length) focusField(fields[Math.min(fields.length - 1, i + 1)]); }
      else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); if (fields.length) focusField(fields[Math.max(0, i - 1)]); }
      else if (e.key === "n") onNext?.();
      else if (e.key === "p") onPrev?.();
      else if (e.key === "Enter" && active) focusField(active);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [active, fields, focusField, onNext, onPrev, selected.length, onList]);

  if (res.error) return <p className="notice error" role="alert">{res.error.message}</p>;
  if (!data) return <p className="muted pad">{t("Betöltés…")}</p>;
  if (data.kind === "email" && data.email) return <EmailReview data={data} wpId={wpId} onChanged={() => { res.reload(); onChanged(); }} />;

  const machine = data.extraction?.datapoints ?? {};
  // 053: on the list tab the image shows where the rows are (with the key `lista[n]`), on the fields tab the fields
  const viewerProv: Record<string, Provenance> = onList
    ? Object.fromEntries((data.provenance[tab]?.rows ?? []).map((r, i) => [`${tab}[${i + 1}]`, r]))
    : Object.fromEntries(Object.entries(data.provenance).filter(([, v]) => v.status !== "list"));
  const labelOf = (k: string) => {
    const m = k.match(/^(.+)\[(\d+)\]$/);
    return m ? t("{{field}}: {{n}}. sor", { field: fieldLabel(m[1]), n: m[2] }) : fieldLabel(k);
  };
  const chooseAlternative = (f: string, a: Alternative) => {
    const value = a.machine ? String(machine[f] ?? "") : String(a.value ?? a.quote ?? "");
    setField(key, data.correction.revision, f, value, a.word_ids ?? null);
    activate(f);
  };
  const colorOf = (f: string) => {
    const row = viewerProv[f];
    if (row?.method === "rows") return row.status === "located" ? BAND_COLOR.confident : BAND_COLOR.check;
    return data.provenance[f]?.method === "manual" ? BAND_COLOR.manual : BAND_COLOR[band(f)];
  };
  const pages = data.source?.pages ?? [];
  const selText = words.data ? selectionText(words.data.words, selected) : "";

  return (
    <Split variant={onList ? "list" : "fields"}
      left={withNote(sourceFileNote(data.source_file), data.source ? (
        <PageViewer pageUrl={(n) => api.pageUrl(wpId, itemId, n)} pages={pages} pageCount={data.page_count} prov={viewerProv} activeField={active}
          focusRequest={focusRequest} colorOf={colorOf} labelOf={labelOf} onPickField={activate}
          onChooseAlternative={chooseAlternative} selectMode={selectMode} words={words.data?.words ?? null}
          selected={selected} onSelect={setSelected} />
      ) : (
        <div className="viewer-stack">
          <p className="notice small">{t("Ehhez az irathoz nincs szóréteg (korábbi futás vagy régi OCR-eredmény), ezért a mezők helye nem keretezhető és a mezőre nem ugrik. Lapozni lehet; a keretekhez futtasd újra a receptet (a helyi OCR a szóhelyeket pótolja).")}</p>
          <PageViewer pageUrl={(n) => api.pageUrl(wpId, itemId, n)} pages={[]} pageCount={data.page_count} prov={{}} activeField={null}
            focusRequest={0} colorOf={colorOf} labelOf={fieldLabel} onPickField={activate} onChooseAlternative={chooseAlternative}
            selectMode={false} words={null} selected={[]} onSelect={() => {}} />
        </div>
      ))}
      right={
        <FieldPanel result={data} fields={fields} bandOf={band} activeField={active} onActivate={activate}
          selection={{ ids: selected, text: selText }} onClearSelection={() => setSelected([])}
          selectMode={selectMode}
          onSaved={() => { res.reload(); onChanged(); }} onResolved={() => { res.reload(); onChanged(); }}
          onChooseAlternative={chooseAlternative} readOnly={approved} hasWords={Boolean(data.source)} tab={tab} onTab={setTab}
          onRowPick={(f, n) => activate(`${f}[${n}]`)} allFields={allFields} onStartFix={startFix}
          filter={filter ?? undefined} counts={counts ?? undefined} onFilter={chooseFilter}
          onNavigate={navigate} onConfirmed={confirmed} onPrevItem={onPrev} onNextItem={onNext} onNextTodo={onNextTodo} />
      }
    />
  );
}
