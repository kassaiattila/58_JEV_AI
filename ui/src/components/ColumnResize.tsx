// Column widths set by dragging (139, the owner's request of 2026-10-10). A table starts in the browser's automatic
// layout. The first drag (or arrow key on a column's edge) measures every column as it is drawn and switches the table
// to fixed widths: from then on only the dragged column changes, the table grows or shrinks with it, and the text
// wraps inside the cell. The widths are kept per table in local storage, like column visibility (DataTable.tsx); the
// column menu resets them, which returns the table to the automatic layout.
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type RefObject } from "react";
import { t } from "../i18n";

export type Widths = Record<string, number>;
export const MIN_WIDTH = 48;
export const MAX_WIDTH = 2000;
/** a column that appears after the widths were fixed (e.g. switched on in the column menu) */
export const DEFAULT_WIDTH = 160;
const KEY_STEP = 16;

const storageKey = (id: string) => `jav.table.${id}.widths`;

export function loadWidths(id: string): Widths {
  try {
    const raw = JSON.parse(localStorage.getItem(storageKey(id)) ?? "{}") as unknown;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
    return Object.fromEntries(Object.entries(raw as Record<string, unknown>)
      .filter(([, v]) => typeof v === "number" && v >= MIN_WIDTH && v <= MAX_WIDTH)) as Widths;
  } catch {
    return {};
  }
}

function saveWidths(id: string, widths: Widths): void {
  try {
    if (Object.keys(widths).length) localStorage.setItem(storageKey(id), JSON.stringify(widths));
    else localStorage.removeItem(storageKey(id));
  } catch {
    /* no storage in a private window: the widths last only for the session */
  }
}

export interface ColumnWidths {
  /** true once a width was set: the table is drawn with fixed widths */
  sized: boolean;
  widthOf: (col: string) => number;
  /** the table's width in fixed mode: the sum of the drawn columns */
  total: (cols: string[]) => number;
  /** the widths to start a change from: the saved ones, or the drawn ones measured on the first change */
  begin: () => Widths;
  resize: (col: string, width: number) => void;
  /** saves the widths after a drag or a key press */
  commit: () => void;
  reset: () => void;
}

/** The column widths of one table. Every header cell carries `data-col` with its column's id. */
export function useColumnWidths(storageId: string, table: RefObject<HTMLTableElement | null>): ColumnWidths {
  const [widths, setWidths] = useState<Widths>(() => loadWidths(storageId));
  const latest = useRef(widths);
  useEffect(() => {
    const saved = loadWidths(storageId);
    latest.current = saved;
    setWidths(saved);
  }, [storageId]);

  const sized = Object.keys(widths).length > 0;
  const widthOf = useCallback((col: string) => widths[col] ?? DEFAULT_WIDTH, [widths]);
  const total = useCallback((cols: string[]) => cols.reduce((s, c) => s + (widths[c] ?? DEFAULT_WIDTH), 0), [widths]);

  const begin = useCallback((): Widths => {
    const drawn: Widths = {};
    table.current?.querySelectorAll<HTMLTableCellElement>("thead th[data-col]").forEach((th) => {
      const col = th.dataset.col as string;
      // rounded up: a header drawn in a fraction of a pixel more would otherwise wrap after the switch
      const measured = Math.ceil(th.getBoundingClientRect().width);
      drawn[col] = latest.current[col] ?? (Object.keys(latest.current).length ? DEFAULT_WIDTH : Math.max(MIN_WIDTH, measured));
    });
    const next = { ...latest.current, ...drawn };
    latest.current = next;
    setWidths(next);
    return next;
  }, [table]);

  const resize = useCallback((col: string, width: number) => {
    const next = { ...latest.current, [col]: Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(width))) };
    latest.current = next;
    setWidths(next);
  }, []);

  const commit = useCallback(() => saveWidths(storageId, latest.current), [storageId]);
  const reset = useCallback(() => {
    latest.current = {};
    setWidths({});
    saveWidths(storageId, {});
  }, [storageId]);

  return { sized, widthOf, total, begin, resize, commit, reset };
}

/** The draggable right edge of a header cell (the cell needs a positioned context, e.g. `position: sticky`). With the
 *  keyboard: focus the edge, then the left and right arrows narrow or widen the column. */
export function ColumnResizer({ col, label, widths }: { col: string; label: string; widths: ColumnWidths }) {
  const drag = useRef<{ x: number; width: number } | null>(null);
  const start = (e: PointerEvent<HTMLSpanElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    drag.current = { x: e.clientX, width: widths.begin()[col] ?? DEFAULT_WIDTH };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const move = (e: PointerEvent<HTMLSpanElement>) => {
    if (drag.current) widths.resize(col, drag.current.width + e.clientX - drag.current.x);
  };
  const end = () => {
    if (!drag.current) return;
    drag.current = null;
    widths.commit();
  };
  const key = (e: KeyboardEvent<HTMLSpanElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const from = widths.begin()[col] ?? DEFAULT_WIDTH;
    widths.resize(col, from + (e.key === "ArrowRight" ? KEY_STEP : -KEY_STEP));
    widths.commit();
  };
  return (
    <span role="separator" aria-orientation="vertical" tabIndex={0} className="col-resizer"
      aria-label={t("Column width: {{label}}", { label })} aria-valuemin={MIN_WIDTH} aria-valuemax={MAX_WIDTH}
      aria-valuenow={widths.sized ? widths.widthOf(col) : undefined}
      title={t("Drag to change the column width (or use the arrow keys)")}
      onPointerDown={start} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onKeyDown={key}
      onClick={(e) => e.stopPropagation()} />
  );
}
