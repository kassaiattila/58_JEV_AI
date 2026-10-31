// Shared table (056 U1): every list in the interface uses it. Search, filtering, sorting and paging are done by the
// local service (decision of 2026-09-28); here there is only the request state and the rendering. The headless
// engine (TanStack Table) provides the header, the sorting state, column visibility and selection; on a large page
// TanStack Virtual renders only the visible rows. Column visibility is kept per table (following the legacy project's
// DataTable.tsx, in local storage), and so are the column widths set by dragging (139, ColumnResize.tsx). 263 (plan E,
// E1; the owner's decisions of 2026-10-30: one list everywhere, searchable, sortable, grouped by more than one thing, a
// row opening its thing's page and the way back finding the list as it was): the rows may be grouped by a column the
// dataset offers (the service orders them and counts each group), a group closes and opens; a table with `persist`
// keeps its search, filters, order and grouping for the browser tab, and the order of its rows' pages for the previous
// and next buttons of a thing's page (`ItemSteps`).
import {
  flexRender, getCoreRowModel, useReactTable,
  type ColumnDef, type RowSelectionState, type SortingState, type VisibilityState,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { DsColumn, DsFilter, DsPage, DsRow, DsScope, DsSort } from "../api";
import { useDataset, useDebounced } from "../hooks";
import { getLocale, t, useLocale } from "../i18n";
import { fold, moneyText, numText, tmap, when } from "../labels";
import { settingsHash, wpHash } from "../route";
import { ColumnResizer, useColumnWidths } from "./ColumnResize";
import { DownloadPanel } from "./DownloadPanel";
import { Picker } from "./Picker";
import { Popover } from "./Popover";
import { Icon } from "./Icon";

export interface TableState { q: string; filters: DsFilter[]; sort: DsSort[]; offset: number; limit: number; group?: string; closed?: string[] }
export const EMPTY_STATE: TableState = { q: "", filters: [], sort: [], offset: 0, limit: 100 };
const PAGE_SIZES = [50, 100, 250, 500];
const VIRTUAL_MIN = 80; // above this many rows only the visible rows are rendered
const ROW_PX = 37;

interface Props {
  dataset: string;
  scope?: DsScope;
  label: string;
  /** controlled state (e.g. from the address bar); without it the table keeps it itself */
  state?: TableState;
  onStateChange?: (s: TableState) => void;
  initial?: Partial<TableState>;
  selectable?: boolean;
  pollMs?: number;
  /** key for saving column visibility (default: the dataset name) */
  storageId?: string;
  /** extra choice in the download panel (e.g. the run's full Excel bundle) */
  downloadExtras?: ReactNode;
  toolbar?: ReactNode;
  emptyText?: string;
  cell?: (col: DsColumn, row: DsRow) => ReactNode | undefined;
  maxHeight?: string;
  onPage?: (page: DsPage) => void;
  /** columns hidden by default in this context (e.g. the work package name inside the package) */
  defaultHidden?: string[];
  /** per-row actions (last column), e.g. removal */
  actions?: (row: DsRow) => ReactNode;
  /** 168: actions on the selected rows (with `selectable`), shown beside the selection's count */
  selectionActions?: (rows: DsRow[], clear: () => void) => ReactNode;
  actionsLabel?: string;
  /** 263: the name under which the table keeps its state for the browser tab and the order of its rows' pages */
  persist?: string;
  /** 263: the column the rows are grouped by at first */
  defaultGroup?: string;
}

// --- kept state and the rows' order (263) --------------------------------------------------------------------------

const stateKey = (id: string) => `jav.table.${id}`;
const orderKey = (id: string) => `jav.table.${id}.order`;
function loadState(id: string | undefined): Partial<TableState> {
  if (!id) return {};
  try {
    return JSON.parse(sessionStorage.getItem(stateKey(id)) ?? "{}") as Partial<TableState>;
  } catch {
    return {};
  }
}
function keep(key: string, value: unknown) {
  try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* private window: no storage */ }
}

/** The pages of the rows of a kept table, in the order they were last shown (empty when it was not shown here). */
export function rowOrder(id: string): string[] {
  try {
    const hrefs = JSON.parse(sessionStorage.getItem(orderKey(id)) ?? "[]") as unknown;
    return Array.isArray(hrefs) ? hrefs.filter((h): h is string => typeof h === "string") : [];
  } catch {
    return [];
  }
}

// --- cells -------------------------------------------------------------------------------------------------------

export function linkOf(col: DsColumn, row: DsRow): string | null {
  const e = encodeURIComponent;
  const item = (row.item_id as string | undefined) ?? row._key;
  const wp = row._wp ? wpHash(String(row._wp)) : null;  // 261 (B1c): a case's batch under its case
  switch (col.link) {
    case "run": return row._run ? `#/runs/${e(row._run)}` : null;
    case "workpackage": return wp;
    case "case": return row._wp ? `#/cases/${e(row._wp)}` : null;  // 231 (U2a): a case at its own address
    case "next": return wp && row._stage ? `${wp}/${String(row._stage)}` : wp;
    case "reviews": return wp ? `${wp}/review` : null;
    case "process": return wp ? `${wp}/process` : null; // 153: older runs to supersede
    case "settings": { // 263: a thing of Settings (an own party's row names its own section)
      const own = row._settings as string[] | undefined;
      if (own?.length) return settingsHash(own[0], own[1], own[2]);
      return col.section ? (col.list ? settingsHash(col.section, col.list, row._key) : settingsHash(col.section, row._key)) : null;
    }
    case "review":
    case "item": return wp ? `${wp}/review/${e(item)}` : null;
    default: return null;
  }
}

export function cellText(col: DsColumn, v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  // the label of an enumerated value comes from the local service (Hungarian key); it is translated here
  if (col.labels && typeof v !== "object") {
    const l = col.labels[String(v)];
    return l === undefined ? String(v) : t(l);
  }
  if (col.kind === "money") return moneyText(v); // 167 (review 160 U-13)
  if (col.kind === "number" && col.percent) return `${numText(Math.round(Number(v) * 100), 0)} %`; // 062: probability
  if (col.kind === "number") return numText(v, 6);
  if (col.kind === "datetime") return when(String(v));
  if (col.kind === "bool") return v ? t("yes") : t("no");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** 264 (F5): the column as this row shows it - a column whose rows say their kind takes the row's (an amount among
 *  the data points' values reads as an amount). */
export function rowColumn(col: DsColumn, row: DsRow): DsColumn {
  const kind = col.kind_from ? row[col.kind_from] : undefined;
  return typeof kind === "string" && kind && kind !== col.kind ? { ...col, kind: kind as DsColumn["kind"] } : col;
}

function Cell({ col: shown, row, custom }: { col: DsColumn; row: DsRow; custom?: Props["cell"] }) {
  const own = custom?.(shown, row);
  if (own !== undefined) return <>{own}</>;
  const col = rowColumn(shown, row);
  const raw = row[col.key];
  const text = cellText(col, raw);
  if (!text) return <span className="muted">–</span>;
  // 058: a value of 0 in an attention count is neither a link nor highlighted — there is nothing to open
  if (col.alert && Number(raw) === 0) return <span className="muted">{text}</span>;
  const href = linkOf(col, row);
  // 057: status as a badge, an attention count above 0 highlighted (the column description says which column is one)
  const body = col.badge ? <span className={`status s-${col.marks?.[String(raw)] ?? String(raw)}`}>{text}</span>
    : col.alert && Number(raw) > 0 ? <span className="count-alert">{text}</span>
      : col.kind === "id" ? <span className="mono small">{text}</span>
        : col.kind === "datetime" ? <When text={text} /> : text;
  return href ? <a href={href}>{body}</a> : <>{body}</>;
}

/** 155: a date-time as its date and its time, so that a narrow column puts the time under the date instead of breaking
 *  the date itself; the text (and what a test or a screen reader reads) stays the same. */
function When({ text }: { text: string }) {
  // the time is the last part that starts with h:mm (with any AM/PM after it): "2026. 10. 13. 19:03", "10/13/26, 7:03 PM"
  const m = /^(.*\S)(\s+)(\d{1,2}[:.]\d{2}\D*)$/.exec(text);
  if (!m) return <>{text}</>;
  return <span className="when"><span>{m[1]}</span>{m[2]}<span>{m[3]}</span></span>;
}

const NUMERIC = new Set(["number", "money"]);

/** 058: the sortability mark on every column header — a faint double arrow; on a sorted column the highlighted
 *  direction (and the level, when sorting by several columns). Screen readers get `aria-sort`; the mark is purely
 *  visual. */
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

// --- filters -----------------------------------------------------------------------------------------------------

const OP_TEXT: Record<string, string> = tmap({ contains: "contains", eq: "=", neq: "≠", gte: "≥", lte: "≤", empty: "is empty", notempty: "is not empty" });

export function filterText(f: DsFilter, col: DsColumn | undefined): string {
  const label = col ? t(col.label) : f.col;
  if (f.op === "empty" || f.op === "notempty") return `${label}: ${OP_TEXT[f.op]}`;
  // a filter's amount as the person gave it ("≥ 12 000"), not padded to a cell's two decimals
  const show = (v: string) => (col ? (col.kind === "money" && !col.labels ? numText(v, 2) : cellText(col, v)) || v : v);
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
        aria-label={current.length ? t("Filter: {{label}} (active)", { label }) : t("Filter: {{label}}", { label })} title={t("Filter: {{label}}", { label })} onClick={() => setOpen((o) => !o)}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 3h12l-4.5 5.5V13l-3 1V8.5z" /></svg>
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label={t("Filter: {{label}}", { label })} className="filter-pop">
        <form onSubmit={(e) => { e.preventDefault(); apply(); }} className="filter-form">
          <strong className="small">{label}</strong>
          {isSet ? (
            <>
              {(facets?.length ?? 0) > 8 ? (
                <input autoFocus className="picker-search" aria-label={t("Search values")} placeholder={t("Search…")} value={search} onChange={(e) => setSearch(e.target.value)} />
              ) : null}
              <div className="check-list" role="group" aria-label={t("Values")}>
                {options.map((v) => (
                  <label key={v} className="check">
                    <input type="checkbox" checked={chosen.includes(v)}
                      onChange={(e) => setChosen((c) => (e.target.checked ? [...c, v] : c.filter((x) => x !== v)))} />
                    {cellText(col, v) || v}
                  </label>
                ))}
                {options.length === 0 ? <span className="muted small">{t("No values.")}</span> : null}
              </div>
            </>
          ) : isRange ? (
            <div className="range">
              <label>{t("At least")}<input type={isDate ? "date" : "text"} inputMode={isDate ? undefined : "decimal"} value={from} onChange={(e) => setFrom(e.target.value)} /></label>
              <label>{t("At most")}<input type={isDate ? "date" : "text"} inputMode={isDate ? undefined : "decimal"} value={to} onChange={(e) => setTo(e.target.value)} /></label>
            </div>
          ) : (
            <label className="block-label">{t("Contains")}<input autoFocus value={text} onChange={(e) => setText(e.target.value)} /></label>
          )}
          <div className="blank-row" role="radiogroup" aria-label={t("Empty values")}>
            {([["", t("all")], ["empty", t("empty only")], ["notempty", t("filled only")]] as const).map(([v, text]) => (
              <label key={v} className="check"><input type="radio" name={`blank-${col.key}`} checked={blank === v} onChange={() => setBlank(v)} />{text}</label>
            ))}
          </div>
          <div className="button-row">
            <button type="submit" className="primary small-btn">{t("Filter")}</button>
            <button type="button" className="secondary small-btn" onClick={() => { onApply([]); setOpen(false); }}>{t("Clear filter")}</button>
          </div>
        </form>
      </Popover>
    </>
  );
}

// --- column picker ----------------------------------------------------------------------------------------------

function ColumnMenu({ columns, visible, onChange, onReset, onResetWidths }: {
  columns: DsColumn[]; visible: (c: DsColumn) => boolean; onChange: (key: string, on: boolean) => void; onReset: () => void;
  /** 139: only while a column width is set */
  onResetWidths?: () => void;
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
        <Icon name="columns" />{t("Columns ({{shown}}/{{all}})", { shown: count, all: columns.length })}
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label={t("Columns")} className="filter-pop" align="right">
        {columns.length > 8 ? <input className="picker-search" aria-label={t("Search columns")} placeholder={t("Search…")} value={q} onChange={(e) => setQ(e.target.value)} /> : null}
        <div className="check-list" role="group" aria-label={t("Visible columns")}>
          {shown.map((c) => (
            <label key={c.key} className="check">
              <input type="checkbox" checked={visible(c)} onChange={(e) => onChange(c.key, e.target.checked)} />{t(c.label)}
            </label>
          ))}
        </div>
        <button type="button" className="link-btn small" onClick={onReset}>{t("Reset")}</button>
        {onResetWidths ? <button type="button" className="link-btn small" onClick={onResetWidths}>{t("Reset column widths")}</button> : null}
      </Popover>
    </>
  );
}

// --- saving column visibility -------------------------------------------------------------------------------------

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
    /* no storage in a private window: the setting only lasts for the session */
  }
}

// --- the table ----------------------------------------------------------------------------------------------------

export function DataTable(p: Props) {
  const lang = useLocale();
  const [own, setOwn] = useState<TableState>(() => ({ ...EMPTY_STATE, group: p.defaultGroup, ...p.initial, ...loadState(p.persist) }));
  const state = p.state ?? own;
  const setState = (next: TableState) => {
    if (p.persist) keep(stateKey(p.persist), next);
    if (p.onStateChange) p.onStateChange(next);
    else setOwn(next);
  };
  const patch = (x: Partial<TableState>) => setState({ ...state, offset: 0, ...x });

  const [search, setSearch] = useState(state.q);
  useEffect(() => setSearch(state.q), [state.q]);
  const debounced = useDebounced(search);
  useEffect(() => {
    if (debounced !== state.q) patch({ q: debounced });
  }, [debounced]); // eslint-disable-line react-hooks/exhaustive-deps

  const scope = p.scope ?? {};
  const query = useMemo(() => ({ q: state.q || undefined, filters: state.filters, sort: state.sort, offset: state.offset, limit: state.limit,
    ...(state.group ? { group: state.group } : {}) }), [state.q, state.filters, state.sort, state.offset, state.limit, state.group]);
  const page = useDataset(p.dataset, scope, query, p.pollMs);
  const data = page.data;
  useEffect(() => { if (data) p.onPage?.(data); }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { // 263: the order of the rows' pages, for a thing's previous and next
    if (!data || !p.persist) return;
    const linked = data.columns.find((c) => c.link);
    if (linked) keep(orderKey(p.persist), data.rows.map((r) => linkOf(linked, r)).filter(Boolean));
  }, [data, p.persist]);

  // a different dataset or scope: the selection cannot be carried over
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
          <input type="checkbox" aria-label={t("Select all rows on this page")} checked={table.getIsAllPageRowsSelected()}
            ref={(el) => { if (el) el.indeterminate = table.getIsSomePageRowsSelected(); }}
            onChange={table.getToggleAllPageRowsSelectedHandler()} />
        ),
        cell: ({ row }) => (
          <input type="checkbox" aria-label={t("Select row")} checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} />
        ),
      });
    }
    if (p.actions) {
      const render = p.actions;
      cols.push({
        id: "_actions", enableSorting: false, enableHiding: false,
        header: () => <span className="sr-only">{p.actionsLabel ?? t("Actions")}</span>,
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

  // 263: the grouping column, each group's count, and the closed groups (their rows are not drawn)
  const groupCol = data?.group ? columns.find((c) => c.key === data.group) : undefined;
  const groupOf = (r: DsRow) => (groupCol ? (r[groupCol.key] === null || r[groupCol.key] === undefined || r[groupCol.key] === "" ? null : String(r[groupCol.key])) : null);
  const groupCount = new Map((data?.groups ?? []).map((g) => [g.value, g.count]));
  const closed = new Set(state.closed ?? []);
  const closedKey = (v: string | null) => v ?? "\u0000";
  const toggleGroup = (v: string | null) => {
    const k = closedKey(v);
    setState({ ...state, closed: closed.has(k) ? [...closed].filter((x) => x !== k) : [...closed, k] });
  };
  const allRows = table.getRowModel().rows;
  const rows = groupCol ? allRows.filter((r) => !closed.has(closedKey(groupOf(r.original)))) : allRows;
  const scrollRef = useRef<HTMLDivElement>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const widths = useColumnWidths(storageId, tableRef);
  const virtual = !groupCol && rows.length > VIRTUAL_MIN;  // a grouped page draws every row (at most a page of them)
  // 139: a wrapped row is taller than the estimate, so the drawn rows are measured
  const virtualizer = useVirtualizer({
    count: virtual ? rows.length : 0, getScrollElement: () => scrollRef.current, estimateSize: () => ROW_PX, overscan: 12,
  });
  const items = virtual ? virtualizer.getVirtualItems() : [];
  const padTop = virtual && items.length ? items[0].start : 0;
  const padBottom = virtual && items.length ? virtualizer.getTotalSize() - items[items.length - 1].end : 0;
  const drawn = virtual ? items.map((v) => ({ row: rows[v.index], index: v.index })) : rows.map((row, index) => ({ row, index }));
  // 263: a grouped page as its lines - a group's head before its first row, its rows unless it is closed
  type Line = { kind: "head"; value: string | null } | { kind: "row"; row: (typeof rows)[number]; index: number };
  const lines: Line[] = groupCol ? allRows.flatMap((row, index): Line[] => {
    const v = groupOf(row.original);
    const head: Line[] = index === 0 || groupOf(allRows[index - 1].original) !== v ? [{ kind: "head", value: v }] : [];
    return closed.has(closedKey(v)) ? head : [...head, { kind: "row", row, index }];
  }) : drawn.map((d) => ({ kind: "row" as const, ...d }));
  const leafIds = table.getVisibleLeafColumns().map((c) => c.id);
  const visibleCount = leafIds.length;

  const byKey = Object.fromEntries(columns.map((c) => [c.key, c]));
  const filtersOf = (key: string) => state.filters.filter((f) => f.col === key);
  const setColumnFilters = (key: string, fs: DsFilter[]) => patch({ filters: [...state.filters.filter((f) => f.col !== key), ...fs] });
  const selectedKeys = Object.keys(selection).filter((k) => selection[k]);
  // D0-f: an action gets every selected row, as it was last seen on any page (the count names them all); a row on the
  // page shown is always its newest version
  const lastSeen = useRef<Record<string, DsRow>>({});
  const onPage = useMemo(() => new Map((data?.rows ?? []).map((r) => [r._key, r])), [data]);
  const selectedRows = useMemo(() => {
    const next: Record<string, DsRow> = {};
    for (const k of Object.keys(selection)) {
      const row = selection[k] ? onPage.get(k) ?? lastSeen.current[k] : undefined;
      if (row) next[k] = row;
    }
    lastSeen.current = next;
    return Object.values(next);
  }, [selection, onPage]);
  const offPage = selectedKeys.filter((k) => !onPage.has(k)).length;
  const filtered = Boolean(state.q || state.filters.length);

  const total = data?.total ?? 0;
  const matched = data?.matched ?? 0;
  const from = matched ? state.offset + 1 : 0;
  const to = Math.min(state.offset + state.limit, matched);
  const lastOffset = Math.max(0, Math.floor((matched - 1) / state.limit) * state.limit);

  return (
    <div className="dt" aria-busy={page.loading}>
      <div className="dt-bar">
        <input type="search" className="dt-search" aria-label={t("Search: {{label}}", { label: p.label })} placeholder={t("Search all columns…")}
          value={search} onChange={(e) => setSearch(e.target.value)} />
        {columns.some((c) => c.group) ? (  // 263: the columns the dataset lets the rows be grouped by
          <Picker label={t("Group by")} hideLabel compact value={state.group ?? ""}
            options={[{ value: "", label: t("No grouping") }, ...columns.filter((c) => c.group).map((c) => ({ value: c.key, label: t("Grouped by {{name}}", { name: t(c.label) }) }))]}
            onChange={(v) => patch({ group: v || undefined, closed: [] })} />
        ) : null}
        {p.toolbar}
        <span className="dt-spacer" />
        {columns.length ? <ColumnMenu columns={columns} visible={isVisible} onChange={setVisible}
          onReset={() => { setVisibility({}); saveVisibility(storageId, {}); }} onResetWidths={widths.sized ? widths.reset : undefined} /> : null}
        <DownloadPanel dataset={p.dataset} scope={scope} label={p.label} query={query} total={total} matched={matched}
          filtered={filtered} selectedKeys={selectedKeys} columns={columns} visibleKeys={columns.filter(isVisible).map((c) => c.key)}
          extras={p.downloadExtras} />
      </div>
      {state.filters.length || selectedKeys.length ? (
        <div className="dt-chips" aria-label={t("Active filters")}>
          {state.filters.map((f, i) => (
            <span key={`${f.col}-${f.op}-${i}`} className="chip">
              {filterText(f, byKey[f.col])}
              <button type="button" aria-label={t("Remove filter: {{filter}}", { filter: filterText(f, byKey[f.col]) })}
                onClick={() => patch({ filters: state.filters.filter((_, j) => j !== i) })}>×</button>
            </span>
          ))}
          {state.filters.length > 1 ? <button type="button" className="link-btn small" onClick={() => patch({ filters: [] })}>{t("Clear all filters")}</button> : null}
          {selectedKeys.length ? (
            <span className="chip sel">{t("{{n}} rows selected", { n: selectedKeys.length })}
              {offPage ? ` · ${t("{{n}} of them not on this page", { n: offPage })}` : null}
              <button type="button" aria-label={t("Clear selection")} onClick={() => setSelection({})}>×</button></span>
          ) : null}
          {selectedKeys.length && p.selectionActions ? p.selectionActions(selectedRows, () => setSelection({})) : null}
        </div>
      ) : null}
      {page.error ? <p className="notice error" role="alert">{page.error.message}</p> : null}
      {!data && !page.error ? <p className="muted small pad">{t("Loading…")}</p> : null}
      {data ? (
        <div className="dt-scroll" ref={scrollRef} style={{ maxHeight: p.maxHeight ?? "70vh" }}>
          <table ref={tableRef} className={widths.sized ? "table dt-table sized" : "table dt-table"} aria-label={p.label} aria-rowcount={matched + 1}
            data-dataset={p.dataset}
            style={widths.sized ? { width: widths.total(leafIds) } : undefined}>
            {widths.sized ? <colgroup>{leafIds.map((id) => <col key={id} style={{ width: widths.widthOf(id) }} />)}</colgroup> : null}
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((h) => {
                    const c = h.column.columnDef.meta as DsColumn | undefined;
                    const sorted = h.column.getIsSorted();
                    // 062: without a requested sort, the service's default order shows (e.g. newest package first)
                    const nat = !state.sort.length ? natural.find((n) => n.col === c?.key) : undefined;
                    const dir = sorted || (nat ? (nat.desc ? "desc" : "asc") : false);
                    const idx = h.column.getSortIndex();
                    const next = h.column.getNextSortingOrder();
                    const hint = `${next === "asc" ? t("Click: ascending order") : next === "desc" ? t("Click: descending order") : t("Click: turn sorting off")} · ${t("Shift + click: add another sort level")}`;
                    return (
                      <th key={h.id} data-col={h.column.id} className={c && NUMERIC.has(c.kind) ? "num" : undefined}
                        aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : undefined}>
                        {c ? (
                          <span className="th-in">
                            <button type="button" className={dir ? "th-sort sorted" : "th-sort"} onClick={h.column.getToggleSortingHandler()}
                              title={nat ? `${nat.desc ? t("Default order: descending") : t("Default order: ascending")} · ${hint}` : hint}>
                              {flexRender(h.column.columnDef.header, h.getContext())}
                              <SortMark dir={dir} level={sorted && sorting.length > 1 ? idx + 1 : null} />
                            </button>
                            <ColumnFilter col={c} facets={data.facets[c.key]} current={filtersOf(c.key)} onApply={(fs) => setColumnFilters(c.key, fs)} />
                          </span>
                        ) : flexRender(h.column.columnDef.header, h.getContext())}
                        {c ? <ColumnResizer col={h.column.id} label={t(c.label)} widths={widths} /> : null}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {padTop > 0 ? <tr aria-hidden="true"><td colSpan={visibleCount} style={{ height: padTop, padding: 0 }} /></tr> : null}
              {lines.map((line) => line.kind === "head" ? (
                <tr key={`group:${closedKey(line.value)}`} className="dt-group">
                  <td colSpan={Math.max(1, visibleCount)}>
                    <button type="button" className="dt-group-toggle" aria-expanded={!closed.has(closedKey(line.value))} onClick={() => toggleGroup(line.value)}>
                      <Icon name="chevron" />
                      <span className="dt-group-name">{line.value === null ? t("(not given)") : groupCol?.kind === "bool" ? (line.value === "true" ? t("yes") : t("no"))
                        // 263 (F3): a group's name is shown as its cells show the value (a pack's title translated)
                        : groupCol ? (p.cell?.(groupCol, { _key: "", [groupCol.key]: line.value }) ?? cellText(groupCol, line.value)) : line.value}</span>
                      <span className="dt-group-count">{groupCount.get(line.value) ?? 0}</span>
                    </button>
                  </td>
                </tr>
              ) : (({ row, index }) => (
                <tr key={row.id} className={row.getIsSelected() ? "row-selected" : undefined}
                  data-index={index} ref={virtual ? virtualizer.measureElement : undefined}>
                  {row.getVisibleCells().map((cell) => {
                    const c = cell.column.columnDef.meta as DsColumn | undefined;
                    return (
                      <td key={cell.id} data-col={cell.column.id} data-wrap={c?.wrap} className={c && NUMERIC.has(c.kind) ? "num" : undefined}>
                        {c?.clamp ? (
                          // 183: at most this many lines; the full value is the tooltip
                          <div className="dt-clamp" style={{ WebkitLineClamp: c.clamp }} title={cellText(c, row.original[c.key])}>
                            <Cell col={c} row={row.original} custom={p.cell} />
                          </div>
                        ) : c ? <Cell col={c} row={row.original} custom={p.cell} /> : flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    );
                  })}
                </tr>
              ))(line))}
              {padBottom > 0 ? <tr aria-hidden="true"><td colSpan={visibleCount} style={{ height: padBottom, padding: 0 }} /></tr> : null}
              {rows.length === 0 ? (
                <tr><td colSpan={Math.max(1, visibleCount)} className="muted">{filtered ? t("No rows match the filter.") : p.emptyText ?? t("No data.")}</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}
      {data ? (
        <div className="dt-foot">
          <span className="small" role="status">
            {filtered
              ? t("{{from}}–{{to}} of {{matched}} rows (filtered, {{total}} in total)", { from, to, matched: matched.toLocaleString(getLocale()), total: total.toLocaleString(getLocale()) })
              : t("{{from}}–{{to}} of {{matched}} rows", { from, to, matched: matched.toLocaleString(getLocale()) })}
          </span>
          {data.refreshing ? <span className="small muted">{t("Updating…")}</span> : null}
          <span className="dt-spacer" />
          <Picker label={t("Rows per page")} compact value={String(state.limit)}
            options={PAGE_SIZES.map((n) => ({ value: String(n), label: t("{{n}} / page", { n }) }))} onChange={(v) => patch({ limit: Number(v) })} hideLabel />
          <div className="pager" role="group" aria-label={t("Pagination")}>
            <button type="button" className="secondary small-btn" aria-label={t("First page")} disabled={state.offset === 0} onClick={() => setState({ ...state, offset: 0 })}>«</button>
            <button type="button" className="secondary small-btn" aria-label={t("Previous sheet")} disabled={state.offset === 0}
              onClick={() => setState({ ...state, offset: Math.max(0, state.offset - state.limit) })}>‹</button>
            <button type="button" className="secondary small-btn" aria-label={t("Next sheet")} disabled={to >= matched}
              onClick={() => setState({ ...state, offset: state.offset + state.limit })}>›</button>
            <button type="button" className="secondary small-btn" aria-label={t("Last page")} disabled={to >= matched}
              onClick={() => setState({ ...state, offset: lastOffset })}>»</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
