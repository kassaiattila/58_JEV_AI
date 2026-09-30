// Line-item list (048 T1-lista): a table of statement transactions, resolutions and line items with editable cells,
// and with adding and deleting rows. The correction covers the whole list (the local service checks the kind per cell);
// the draft lives in the drafts.ts store and is saved together with the field correction.
import { Picker } from "../components/Picker";
import { useEffect, useRef } from "react";
import type { Cell, CorrectionValue, ListColumn } from "../api";
import { t, useLocale } from "../i18n";
import { columnLabel, fieldLabel } from "../labels";
import type { ListRow } from "./drafts";
import { Icon } from "../components/Icon";

const NUMERIC = new Set(["money", "number"]);

/** Machine / corrected list → editable rows (text per cell; for a simple list, the `*` column). */
export function toRows(value: unknown, columns: ListColumn[]): ListRow[] {
  const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));
  if (!Array.isArray(value)) return [];
  if (columns.length === 1 && columns[0].name === "*") return value.map((v) => ({ "*": str(v) }));
  return value.map((row) => Object.fromEntries(columns.map((c) => [c.name, str((row as Record<string, unknown> | null)?.[c.name])])));
}

/** Edited rows → the list to save: an empty cell = no value; a completely empty row is left out. */
export function fromRows(rows: ListRow[], columns: ListColumn[]): CorrectionValue {
  const cell = (v: string | undefined): Cell => (v === undefined || v.trim() === "" ? null : v.trim());
  const filled = rows.filter((r) => columns.some((c) => cell(r[c.name]) !== null));
  if (columns.length === 1 && columns[0].name === "*") return filled.map((r) => cell(r["*"]));
  return filled.map((r) => Object.fromEntries(columns.map((c) => [c.name, cell(r[c.name])])));
}

interface Props {
  field: string;
  columns: ListColumn[];
  rows: ListRow[];
  badRows: number[]; // numbered from 1 (this is how the checks mark them)
  focusRow: { row: number; seq: number } | null;
  activeRow?: number | null; // 053: the row selected on the image (from 1), highlighted and scrolled into view
  onRowPick?: (row: number) => void; // 053: clicking the row / entering a cell jumps the image to the row's position
  edited: boolean;
  corrected: boolean;
  readOnly: boolean;
  onChange: (rows: ListRow[]) => void;
  onRevert: () => void;
}

export function ListTable(p: Props) {
  const { field, columns, rows, badRows, readOnly } = p;
  useLocale();
  const body = useRef<HTMLTableSectionElement | null>(null);
  const simple = columns.length === 1 && columns[0].name === "*";

  useEffect(() => {
    if (!p.focusRow) return;
    const tr = body.current?.querySelectorAll("tr")[p.focusRow.row - 1];
    tr?.scrollIntoView?.({ block: "center" });
    tr?.querySelector<HTMLInputElement | HTMLSelectElement>("input, select")?.focus();
  }, [p.focusRow]);

  useEffect(() => {
    if (!p.activeRow) return;
    body.current?.querySelectorAll("tr")[p.activeRow - 1]?.scrollIntoView?.({ block: "nearest" });
  }, [p.activeRow]);

  const set = (i: number, col: string, v: string) => p.onChange(rows.map((r, j) => (j === i ? { ...r, [col]: v } : r)));
  const add = () => p.onChange([...rows, Object.fromEntries(columns.map((c) => [c.name, ""]))]);
  const remove = (i: number) => p.onChange(rows.filter((_, j) => j !== i));

  return (
    <div className="list-view">
      <div className="list-head">
        <strong>{fieldLabel(field)}</strong>
        <span className="muted small">{t("{{n}} sor", { n: rows.length })}</span>
        {p.edited ? <span className="badge">{t("mentetlen")}</span> : p.corrected ? <span className="badge">{t("javítva")}</span> : null}
        <span className="spacer" />
        {p.edited ? <button type="button" className="quiet small-btn" onClick={p.onRevert}>{t("A lista visszaállítása")}</button> : null}
        <button type="button" className="secondary small-btn" disabled={readOnly} onClick={add}><Icon name="plus" />{t("Sor hozzáadása")}</button>
      </div>
      {rows.length === 0 ? <p className="muted small pad-s">{t("A lista üres: a gép nem talált ilyen sort. Ha az iraton van, add hozzá.")}</p> : (
        <div className="list-scroll">
          <table className="table compact list-table">
            <thead>
              <tr>
                <th className="num">#</th>
                {columns.map((c) => <th key={c.name} className={NUMERIC.has(c.kind) ? "num" : ""}>{simple ? t("Érték") : columnLabel(c.name)}</th>)}
                <th aria-label={t("Törlés")} />
              </tr>
            </thead>
            <tbody ref={body}>
              {rows.map((r, i) => (
                <tr key={i} className={[badRows.includes(i + 1) ? "row-bad" : "", p.activeRow === i + 1 ? "row-active" : ""].filter(Boolean).join(" ")}
                  onFocus={() => p.onRowPick?.(i + 1)} onClick={() => p.onRowPick?.(i + 1)}>
                  <td className="num muted">{i + 1}</td>
                  {columns.map((c) => {
                    const label = t("{{n}}. sor: {{col}}", { n: i + 1, col: simple ? fieldLabel(field) : columnLabel(c.name) });
                    const v = r[c.name] ?? "";
                    return (
                      <td key={c.name}>
                        {c.options ? (
                          <Picker label={label} hideLabel compact value={v} disabled={readOnly} onChange={(x) => set(i, c.name, x)}
                            options={[{ value: "", label: "–" }, ...c.options.map((o) => ({ value: o, label: columnLabel(`${c.name}=${o}`) })),
                              ...(v && !c.options.includes(v) ? [{ value: v, label: t("{{value}} (nem megengedett)", { value: v }) }] : [])]} />
                        ) : (
                          <input aria-label={label} value={v} readOnly={readOnly} className={NUMERIC.has(c.kind) ? "num" : c.kind === "date" ? "" : "wide"}
                            placeholder={c.kind === "date" ? t("ÉÉÉÉ-HH-NN") : undefined} onChange={(e) => set(i, c.name, e.target.value)} />
                        )}
                      </td>
                    );
                  })}
                  <td>
                    <button type="button" className="quiet small-btn" aria-label={t("{{n}}. sor törlése", { n: i + 1 })} disabled={readOnly}
                      onClick={() => remove(i)}>×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
