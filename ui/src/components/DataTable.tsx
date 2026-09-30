// Közös táblázat (056 U1): a felület minden listája ezt használja. A keresést, a szűrést, a rendezést és a lapozást
// a helyi szolgáltatás végzi (döntés 2026-09-28), itt csak a kérés állapota és a kirajzolás van. A megjelenés nélküli
// motor (TanStack Table) adja a fejlécet, a rendezés-állapotot, az oszlopláthatóságot és a kijelölést; nagy lapnál a
// TanStack Virtual csak a látható sorokat rajzolja ki. Az oszlopok láthatósága táblánként megmarad (a régi projekt
// DataTable.tsx mintája, helyi tárolóban).
import {
  flexRender, getCoreRowModel, useReactTable,
  type ColumnDef, type RowSelectionState, type SortingState, type VisibilityState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { DsColumn, DsFilter, DsPage, DsRow, DsScope, DsSort } from "../api";
import { useDataset, useDebounced } from "../hooks";
import { getLocale, t, useLocale } from "../i18n";
import { fold, numText, tmap, when } from "../labels";
import { DownloadPanel } from "./DownloadPanel";
import { Picker } from "./Picker";
import { Popover } from "./Popover";
import { Icon } from "./Icon";

export interface TableState { q: string; filters: DsFilter[]; sort: DsSort[]; offset: number; limit: number }
export const EMPTY_STATE: TableState = { q: "", filters: [], sort: [], offset: 0, limit: 100 };
const PAGE_SIZES = [50, 100, 250, 500];
const VIRTUAL_MIN = 80; // ennyi sor fölött csak a látható sorok rajzolódnak
const ROW_PX = 37;

interface Props {
  dataset: string;
  scope?: DsScope;
  label: string;
  /** vezérelt állapot (pl. a címsorból); nélküle a táblázat maga tartja */
  state?: TableState;
  onStateChange?: (s: TableState) => void;
  initial?: Partial<TableState>;
  selectable?: boolean;
  pollMs?: number;
  /** oszlopláthatóság mentésének kulcsa (alap: az adatkészlet neve) */
  storageId?: string;
  /** a letöltés-panel többlet-választása (pl. a futás teljes Excel-csomagja) */
  downloadExtras?: ReactNode;
  toolbar?: ReactNode;
  emptyText?: string;
  cell?: (col: DsColumn, row: DsRow) => ReactNode | undefined;
  maxHeight?: string;
  onPage?: (page: DsPage) => void;
  /** ebben a környezetben alapból rejtett oszlopok (pl. a csomagon belül a csomag neve) */
  defaultHidden?: string[];
  /** soronkénti műveletek (utolsó oszlop), pl. eltávolítás */
  actions?: (row: DsRow) => ReactNode;
  actionsLabel?: string;
}

// --- cellák ------------------------------------------------------------------------------------------------------

export function linkOf(col: DsColumn, row: DsRow): string | null {
  const e = encodeURIComponent;
  const item = (row.item_id as string | undefined) ?? row._key;
  const wp = row._wp ? `#/workpackages/${e(row._wp)}` : null;
  switch (col.link) {
    case "run": return row._run ? `#/runs/${e(row._run)}` : null;
    case "workpackage": return wp;
    case "next": return wp && row._stage ? `${wp}/${String(row._stage)}` : wp;
    case "reviews": return wp ? `${wp}/review` : null;
    case "review":
    case "item": return wp ? `${wp}/review/${e(item)}` : null;
    default: return null;
  }
}

export function cellText(col: DsColumn, v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  // a felsorolt érték felirata a szolgáltatásból jön (magyar kulcs), itt fordítjuk
  if (col.labels && typeof v !== "object") {
    const l = col.labels[String(v)];
    return l === undefined ? String(v) : t(l);
  }
  if (col.kind === "money") return numText(v, 2);
  if (col.kind === "number" && col.percent) return `${numText(Math.round(Number(v) * 100), 0)} %`; // 062: valószínűség
  if (col.kind === "number") return numText(v, 6);
  if (col.kind === "datetime") return when(String(v));
  if (col.kind === "bool") return v ? t("igen") : t("nem");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function Cell({ col, row, custom }: { col: DsColumn; row: DsRow; custom?: Props["cell"] }) {
  const own = custom?.(col, row);
  if (own !== undefined) return <>{own}</>;
  const raw = row[col.key];
  const text = cellText(col, raw);
  if (!text) return <span className="muted">–</span>;
  // 058: a figyelmet kérő szám 0 értéke nem hivatkozás és nem kiemelt — nincs mit megnyitni
  if (col.alert && Number(raw) === 0) return <span className="muted">{text}</span>;
  const href = linkOf(col, row);
  // 057: állapot jelvényként, a 0-nál több figyelmet kérő szám kiemelve (az oszlopleírás mondja meg, melyik ilyen)
  const body = col.badge ? <span className={`status s-${String(raw)}`}>{text}</span>
    : col.alert && Number(raw) > 0 ? <span className="count-alert">{text}</span>
      : col.kind === "id" ? <span className="mono small">{text}</span> : text;
  return href ? <a href={href}>{body}</a> : <>{body}</>;
}

const NUMERIC = new Set(["number", "money"]);

/** 058: a rendezhetőség jele minden oszlopfejlécen — halvány kettős nyíl, rendezett oszlopon a kiemelt irány (és a szint,
 *  ha több oszlop szerint rendez). A felolvasó az `aria-sort`-ot kapja, a jel csak látványelem. */
function SortMark({ dir, level }: { dir: false | "asc" | "desc"; level: number | null }) {
  return (
    <span className={dir ? "sort-mark on" : "sort-mark"} aria-hidden="true" data-dir={dir || "none"}>
      <svg viewBox="0 0 10 14">
        {dir !== "desc" ? <path d="M2 5.5 5 2.5 8 5.5" /> : null}
        {dir !== "asc" ? <path d="M2 8.5 5 11.5 8 8.5" /> : null}
      </svg>
      {level ? <span className="sort-level">{level}</span> : null}
    </span>
  );
}

// --- szűrők ------------------------------------------------------------------------------------------------------

const OP_TEXT: Record<string, string> = tmap({ contains: "tartalmazza", eq: "=", neq: "≠", gte: "≥", lte: "≤", empty: "üres", notempty: "nem üres" });

export function filterText(f: DsFilter, col: DsColumn | undefined): string {
  const label = col ? t(col.label) : f.col;
  if (f.op === "empty" || f.op === "notempty") return `${label}: ${OP_TEXT[f.op]}`;
  const show = (v: string) => (col ? cellText(col, v) || v : v);
  if (f.op === "in") return `${label}: ${(Array.isArray(f.value) ? f.value : [f.value ?? ""]).map((v) => show(String(v))).join(", ")}`;
  const v = String(f.value ?? "").replace(/T99$/, "");
  return `${label} ${OP_TEXT[f.op]} ${f.op === "contains" ? `„${v}”` : show(v)}`;
}

function ColumnFilter({ col, facets, current, onApply }: {
  col: DsColumn; facets: string[] | undefined; current: DsFilter[]; onApply: (filters: DsFilter[]) => void;
}) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [blank, setBlank] = useState<"" | "empty" | "notempty">("");
  useLocale();
  const label = t(col.label);
  const isSet = col.kind === "enum" || col.kind === "bool";
  const isRange = NUMERIC.has(col.kind) || col.kind === "date" || col.kind === "datetime";
  const isDate = col.kind === "date" || col.kind === "datetime";

  useEffect(() => {
    if (!open) return;
    const get = (op: string) => current.find((f) => f.op === op)?.value;
    setText(String(get("contains") ?? ""));
    setFrom(String(get("gte") ?? ""));
    setTo(String(get("lte") ?? "").replace(/T99$/, ""));
    const inV = get("in");
    setChosen(Array.isArray(inV) ? inV.map(String) : []);
    setBlank((current.find((f) => f.op === "empty" || f.op === "notempty")?.op as "empty" | "notempty") ?? "");
    setSearch("");
  }, [open, current]);

  const apply = () => {
    const out: DsFilter[] = [];
    if (blank) out.push({ col: col.key, op: blank });
    else if (isSet && chosen.length) out.push({ col: col.key, op: "in", value: chosen });
    else if (isRange) {
      if (from.trim()) out.push({ col: col.key, op: "gte", value: from.trim() });
      if (to.trim()) out.push({ col: col.key, op: "lte", value: col.kind === "datetime" ? `${to.trim()}T99` : to.trim() });
    } else if (text.trim()) out.push({ col: col.key, op: "contains", value: text.trim() });
    onApply(out);
    setOpen(false);
  };
  const options = (facets ?? []).filter((v) => !search.trim() || fold(cellText(col, v) || v).includes(fold(search.trim())));
  return (
    <>
      <button ref={anchor} type="button" className={`th-filter ${current.length ? "on" : ""}`} aria-expanded={open}
        aria-label={current.length ? t("Szűrő: {{label}} (aktív)", { label }) : t("Szűrő: {{label}}", { label })} title={t("Szűrő: {{label}}", { label })} onClick={() => setOpen((o) => !o)}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 3h12l-4.5 5.5V13l-3 1V8.5z" /></svg>
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label={t("Szűrő: {{label}}", { label })} className="filter-pop">
        <form onSubmit={(e) => { e.preventDefault(); apply(); }} className="filter-form">
          <strong className="small">{label}</strong>
          {isSet ? (
            <>
              {(facets?.length ?? 0) > 8 ? (
                <input autoFocus className="picker-search" aria-label={t("Értékek keresése")} placeholder={t("Keresés…")} value={search} onChange={(e) => setSearch(e.target.value)} />
              ) : null}
              <div className="check-list" role="group" aria-label={t("Értékek")}>
                {options.map((v) => (
                  <label key={v} className="check">
                    <input type="checkbox" checked={chosen.includes(v)}
                      onChange={(e) => setChosen((c) => (e.target.checked ? [...c, v] : c.filter((x) => x !== v)))} />
                    {cellText(col, v) || v}
                  </label>
                ))}
                {options.length === 0 ? <span className="muted small">{t("Nincs érték.")}</span> : null}
              </div>
            </>
          ) : isRange ? (
            <div className="range">
              <label>{t("Legalább")}<input type={isDate ? "date" : "text"} inputMode={isDate ? undefined : "decimal"} value={from} onChange={(e) => setFrom(e.target.value)} /></label>
              <label>{t("Legfeljebb")}<input type={isDate ? "date" : "text"} inputMode={isDate ? undefined : "decimal"} value={to} onChange={(e) => setTo(e.target.value)} /></label>
            </div>
          ) : (
            <label className="block-label">{t("Tartalmazza")}<input autoFocus value={text} onChange={(e) => setText(e.target.value)} /></label>
          )}
          <div className="blank-row" role="radiogroup" aria-label={t("Üres értékek")}>
            {([["", t("mind")], ["empty", t("csak üres")], ["notempty", t("csak kitöltött")]] as const).map(([v, text]) => (
              <label key={v} className="check"><input type="radio" name={`blank-${col.key}`} checked={blank === v} onChange={() => setBlank(v)} />{text}</label>
            ))}
          </div>
          <div className="button-row">
            <button type="submit" className="primary small-btn">{t("Szűrés")}</button>
            <button type="button" className="secondary small-btn" onClick={() => { onApply([]); setOpen(false); }}>{t("Szűrő törlése")}</button>
          </div>
        </form>
      </Popover>
    </>
  );
}

// --- oszlopválasztó ---------------------------------------------------------------------------------------------

function ColumnMenu({ columns, visible, onChange, onReset }: {
  columns: DsColumn[]; visible: (c: DsColumn) => boolean; onChange: (key: string, on: boolean) => void; onReset: () => void;
}) {
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  useLocale();
  const shown = columns.filter((c) => !q.trim() || fold(t(c.label)).includes(fold(q.trim())));
  const count = columns.filter(visible).length;
  return (
    <>
      <button ref={anchor} type="button" className="secondary small-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name="columns" />{t("Oszlopok ({{shown}}/{{all}})", { shown: count, all: columns.length })}
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label={t("Oszlopok")} className="filter-pop" align="right">
        {columns.length > 8 ? <input className="picker-search" aria-label={t("Oszlop keresése")} placeholder={t("Keresés…")} value={q} onChange={(e) => setQ(e.target.value)} /> : null}
        <div className="check-list" role="group" aria-label={t("Látható oszlopok")}>
          {shown.map((c) => (
            <label key={c.key} className="check">
              <input type="checkbox" checked={visible(c)} onChange={(e) => onChange(c.key, e.target.checked)} />{t(c.label)}
            </label>
          ))}
        </div>
        <button type="button" className="link-btn small" onClick={onReset}>{t("Alaphelyzet")}</button>
      </Popover>
    </>
  );
}

// --- oszlopláthatóság mentése -------------------------------------------------------------------------------------

function loadVisibility(id: string): VisibilityState {
  try {
    return JSON.parse(localStorage.getItem(`jav.table.${id}.cols`) ?? "{}") as VisibilityState;
  } catch {
    return {};
  }
}

function saveVisibility(id: string, v: VisibilityState): void {
  try {
    localStorage.setItem(`jav.table.${id}.cols`, JSON.stringify(v));
  } catch {
    /* privát ablakban nincs tárolás: a beállítás csak a munkamenetig él */
  }
}

// --- a táblázat ---------------------------------------------------------------------------------------------------

export function DataTable(p: Props) {
  const lang = useLocale();
  const [own, setOwn] = useState<TableState>({ ...EMPTY_STATE, ...p.initial });
  const state = p.state ?? own;
  const setState = (next: TableState) => (p.onStateChange ? p.onStateChange(next) : setOwn(next));
  const patch = (x: Partial<TableState>) => setState({ ...state, offset: 0, ...x });

  const [search, setSearch] = useState(state.q);
  useEffect(() => setSearch(state.q), [state.q]);
  const debounced = useDebounced(search);
  useEffect(() => {
    if (debounced !== state.q) patch({ q: debounced });
  }, [debounced]); // eslint-disable-line react-hooks/exhaustive-deps

  const scope = p.scope ?? {};
  const query = useMemo(() => ({ q: state.q || undefined, filters: state.filters, sort: state.sort, offset: state.offset, limit: state.limit }),
    [state.q, state.filters, state.sort, state.offset, state.limit]);
  const page = useDataset(p.dataset, scope, query, p.pollMs);
  const data = page.data;
  useEffect(() => { if (data) p.onPage?.(data); }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  // más adatkészlet vagy hatókör: a kijelölés nem vihető át
  const ident = JSON.stringify([p.dataset, scope]);
  const [selection, setSelection] = useState<RowSelectionState>({});
  useEffect(() => setSelection({}), [ident]);

  const storageId = p.storageId ?? p.dataset;
  const [visibility, setVisibility] = useState<VisibilityState>(() => loadVisibility(storageId));
  useEffect(() => setVisibility(loadVisibility(storageId)), [storageId]);
  const columns = data?.columns ?? [];
  const isVisible = (c: DsColumn) => visibility[c.key] ?? !(c.hidden || p.defaultHidden?.includes(c.key));
  const colVisibility = Object.fromEntries(columns.map((c) => [c.key, isVisible(c)]));
  const setVisible = (key: string, on: boolean) => {
    const next = { ...visibility, [key]: on };
    setVisibility(next);
    saveVisibility(storageId, next);
  };

  const defs = useMemo<ColumnDef<DsRow>[]>(() => {
    const cols: ColumnDef<DsRow>[] = columns.map((c) => ({
      id: c.key, accessorFn: (r: DsRow) => r[c.key], header: t(c.label), enableSorting: true, meta: c,
    }));
    if (p.selectable) {
      cols.unshift({
        id: "_select", enableSorting: false, enableHiding: false,
        header: ({ table }) => (
          <input type="checkbox" aria-label={t("A lap összes sorának kijelölése")} checked={table.getIsAllPageRowsSelected()}
            ref={(el) => { if (el) el.indeterminate = table.getIsSomePageRowsSelected(); }}
            onChange={table.getToggleAllPageRowsSelectedHandler()} />
        ),
        cell: ({ row }) => (
          <input type="checkbox" aria-label={t("Sor kijelölése")} checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} />
        ),
      });
    }
    if (p.actions) {
      const render = p.actions;
      cols.push({
        id: "_actions", enableSorting: false, enableHiding: false,
        header: () => <span className="sr-only">{p.actionsLabel ?? t("Műveletek")}</span>,
        cell: ({ row }) => <span className="dt-actions">{render(row.original)}</span>,
      });
    }
    return cols;
  }, [columns, p.selectable, p.actions, lang]); // eslint-disable-line react-hooks/exhaustive-deps

  const sorting: SortingState = state.sort.map((s) => ({ id: s.col, desc: Boolean(s.desc) }));
  const natural = data?.dataset.natural_sort ?? [];
  const table = useReactTable({
    data: data?.rows ?? [], columns: defs, getRowId: (r) => r._key, getCoreRowModel: getCoreRowModel(),
    manualSorting: true, manualFiltering: true, manualPagination: true, enableMultiSort: true, sortDescFirst: false,
    isMultiSortEvent: (e) => (e as MouseEvent).shiftKey,
    state: { sorting, columnVisibility: colVisibility, rowSelection: selection },
    onSortingChange: (up) => {
      const next = typeof up === "function" ? up(sorting) : up;
      patch({ sort: next.map((s) => ({ col: s.id, desc: s.desc })) });
    },
    onRowSelectionChange: setSelection, enableRowSelection: Boolean(p.selectable),
  });

  const rows = table.getRowModel().rows;
  const scrollRef = useRef<HTMLDivElement>(null);
  const virtual = rows.length > VIRTUAL_MIN;
  const virtualizer = useVirtualizer({
    count: virtual ? rows.length : 0, getScrollElement: () => scrollRef.current, estimateSize: () => ROW_PX, overscan: 12,
  });
  const items = virtual ? virtualizer.getVirtualItems() : [];
  const padTop = virtual && items.length ? items[0].start : 0;
  const padBottom = virtual && items.length ? virtualizer.getTotalSize() - items[items.length - 1].end : 0;
  const drawn = virtual ? items.map((v) => rows[v.index]) : rows;
  const visibleCount = table.getVisibleLeafColumns().length;

  const byKey = Object.fromEntries(columns.map((c) => [c.key, c]));
  const filtersOf = (key: string) => state.filters.filter((f) => f.col === key);
  const setColumnFilters = (key: string, fs: DsFilter[]) => patch({ filters: [...state.filters.filter((f) => f.col !== key), ...fs] });
  const selectedKeys = Object.keys(selection).filter((k) => selection[k]);
  const filtered = Boolean(state.q || state.filters.length);

  const total = data?.total ?? 0;
  const matched = data?.matched ?? 0;
  const from = matched ? state.offset + 1 : 0;
  const to = Math.min(state.offset + state.limit, matched);
  const lastOffset = Math.max(0, Math.floor((matched - 1) / state.limit) * state.limit);

  return (
    <div className="dt" aria-busy={page.loading}>
      <div className="dt-bar">
        <input type="search" className="dt-search" aria-label={t("Keresés: {{label}}", { label: p.label })} placeholder={t("Keresés az összes oszlopban…")}
          value={search} onChange={(e) => setSearch(e.target.value)} />
        {p.toolbar}
        <span className="dt-spacer" />
        {columns.length ? <ColumnMenu columns={columns} visible={isVisible} onChange={setVisible}
          onReset={() => { setVisibility({}); saveVisibility(storageId, {}); }} /> : null}
        <DownloadPanel dataset={p.dataset} scope={scope} label={p.label} query={query} total={total} matched={matched}
          filtered={filtered} selectedKeys={selectedKeys} columns={columns} visibleKeys={columns.filter(isVisible).map((c) => c.key)}
          extras={p.downloadExtras} />
      </div>
      {state.filters.length || selectedKeys.length ? (
        <div className="dt-chips" aria-label={t("Aktív szűrők")}>
          {state.filters.map((f, i) => (
            <span key={`${f.col}-${f.op}-${i}`} className="chip">
              {filterText(f, byKey[f.col])}
              <button type="button" aria-label={t("Szűrő törlése: {{filter}}", { filter: filterText(f, byKey[f.col]) })}
                onClick={() => patch({ filters: state.filters.filter((_, j) => j !== i) })}>×</button>
            </span>
          ))}
          {state.filters.length > 1 ? <button type="button" className="link-btn small" onClick={() => patch({ filters: [] })}>{t("Minden szűrő törlése")}</button> : null}
          {selectedKeys.length ? (
            <span className="chip sel">{t("{{n}} kijelölt sor", { n: selectedKeys.length })}
              <button type="button" aria-label={t("Kijelölés törlése")} onClick={() => setSelection({})}>×</button></span>
          ) : null}
        </div>
      ) : null}
      {page.error ? <p className="notice error" role="alert">{page.error.message}</p> : null}
      {!data && !page.error ? <p className="muted small pad">{t("Betöltés…")}</p> : null}
      {data ? (
        <div className="dt-scroll" ref={scrollRef} style={{ maxHeight: p.maxHeight ?? "70vh" }}>
          <table className="table dt-table" aria-label={p.label} aria-rowcount={matched + 1}>
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((h) => {
                    const c = h.column.columnDef.meta as DsColumn | undefined;
                    const sorted = h.column.getIsSorted();
                    // 062: kért rendezés nélkül a szolgáltatás alapsorrendje látszik (pl. a legújabb csomag elöl)
                    const nat = !state.sort.length ? natural.find((n) => n.col === c?.key) : undefined;
                    const dir = sorted || (nat ? (nat.desc ? "desc" : "asc") : false);
                    const idx = h.column.getSortIndex();
                    const next = h.column.getNextSortingOrder();
                    const hint = `${next === "asc" ? t("Kattints: növekvő sorrend") : next === "desc" ? t("Kattints: csökkenő sorrend") : t("Kattints: rendezés kikapcsolása")} · ${t("Shift + kattintás: további rendezési szint")}`;
                    return (
                      <th key={h.id} className={c && NUMERIC.has(c.kind) ? "num" : undefined}
                        aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : undefined}>
                        {c ? (
                          <span className="th-in">
                            <button type="button" className={dir ? "th-sort sorted" : "th-sort"} onClick={h.column.getToggleSortingHandler()}
                              title={nat ? `${nat.desc ? t("Alapsorrend: csökkenő") : t("Alapsorrend: növekvő")} · ${hint}` : hint}>
                              {flexRender(h.column.columnDef.header, h.getContext())}
                              <SortMark dir={dir} level={sorted && sorting.length > 1 ? idx + 1 : null} />
                            </button>
                            <ColumnFilter col={c} facets={data.facets[c.key]} current={filtersOf(c.key)} onApply={(fs) => setColumnFilters(c.key, fs)} />
                          </span>
                        ) : flexRender(h.column.columnDef.header, h.getContext())}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {padTop > 0 ? <tr aria-hidden="true"><td colSpan={visibleCount} style={{ height: padTop, padding: 0 }} /></tr> : null}
              {drawn.map((row) => (
                <tr key={row.id} className={row.getIsSelected() ? "row-selected" : undefined}>
                  {row.getVisibleCells().map((cell) => {
                    const c = cell.column.columnDef.meta as DsColumn | undefined;
                    return (
                      <td key={cell.id} className={c && NUMERIC.has(c.kind) ? "num" : undefined}>
                        {c ? <Cell col={c} row={row.original} custom={p.cell} /> : flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {padBottom > 0 ? <tr aria-hidden="true"><td colSpan={visibleCount} style={{ height: padBottom, padding: 0 }} /></tr> : null}
              {rows.length === 0 ? (
                <tr><td colSpan={Math.max(1, visibleCount)} className="muted">{filtered ? t("Nincs a szűrésnek megfelelő sor.") : p.emptyText ?? t("Nincs adat.")}</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}
      {data ? (
        <div className="dt-foot">
          <span className="small" role="status">
            {filtered
              ? t("{{from}}–{{to}} / {{matched}} sor (szűrve, összesen {{total}})", { from, to, matched: matched.toLocaleString(getLocale()), total: total.toLocaleString(getLocale()) })
              : t("{{from}}–{{to}} / {{matched}} sor", { from, to, matched: matched.toLocaleString(getLocale()) })}
          </span>
          <span className="dt-spacer" />
          <Picker label={t("Sor laponként")} compact value={String(state.limit)}
            options={PAGE_SIZES.map((n) => ({ value: String(n), label: t("{{n}} / lap", { n }) }))} onChange={(v) => patch({ limit: Number(v) })} hideLabel />
          <div className="pager" role="group" aria-label={t("Lapozás")}>
            <button type="button" className="secondary small-btn" aria-label={t("Első lap")} disabled={state.offset === 0} onClick={() => setState({ ...state, offset: 0 })}>«</button>
            <button type="button" className="secondary small-btn" aria-label={t("Előző lap")} disabled={state.offset === 0}
              onClick={() => setState({ ...state, offset: Math.max(0, state.offset - state.limit) })}>‹</button>
            <button type="button" className="secondary small-btn" aria-label={t("Következő lap")} disabled={to >= matched}
              onClick={() => setState({ ...state, offset: state.offset + state.limit })}>›</button>
            <button type="button" className="secondary small-btn" aria-label={t("Utolsó lap")} disabled={to >= matched}
              onClick={() => setState({ ...state, offset: lastOffset })}>»</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
