// 082: the item lists' names. The switch above a list chooses between the original and the unified (content-based)
// file name; the name cell marks an uncertain unified name and shows the other name in its tooltip. The service
// delivers the chosen name in the `name` column, so searching, sorting and filtering follow what is shown.
import { useId, type ReactNode } from "react";
import type { DsColumn, DsRow } from "../api";
import { t, useLocale } from "../i18n";
import { setNameMode, useNameMode } from "../names";
import { linkOf } from "./DataTable";

/** The mark on an uncertain unified name: its copy would go to the review folder; the reason is in the label. */
export function NameWarning({ check }: { check: string | null | undefined }) {
  const label = check ? t("Ellenőrzendő név: {{why}}", { why: check }) : t("Ellenőrzendő név");
  return <span className="name-warn" role="img" aria-label={label} title={label}>⚠</span>;
}

/** The name column (when the unified name is chosen) and the added „Egységes név” column; `undefined` leaves the cell
 *  to the table. */
export function nameCell(col: DsColumn, row: DsRow): ReactNode | undefined {
  const unifiedColumn = col.key === "unified_name";
  if (!unifiedColumn && !(col.key === "name" && col.names === "unified")) return undefined;
  const unified = row.unified_name ? String(row.unified_name) : null;
  if (unifiedColumn && !unified) return <span className="muted">{row.name_state === "pending" ? t("még nincs") : "–"}</span>;
  const text = unifiedColumn ? unified : String(row.name ?? "");
  const tip = unified
    ? t("Eredeti név: {{name}}", { name: String(row.original_name ?? "") })
    : row.name_state === "pending" ? t("Még nincs egységes név: a tétel még nem futott le.") : undefined;
  const warn = unified && row.name_state === "review" ? <NameWarning check={row._name_check as string | null} /> : null;
  const href = linkOf(col, row);
  const body = href ? <a href={href} title={tip}>{text}</a> : <span title={tip}>{text}</span>;
  return <>{warn}{body}</>;
}

/** The switch above an item list: „Eredeti” (original) or „Egységes” (unified) name. */
export function NameModeSwitch() {
  useLocale();
  const mode = useNameMode();
  const group = useId();
  return (
    <fieldset className="segmented name-switch" title={t("Az egységes név a tartalom alapján képzett fájlnév (dátum, típus, partner, azonosító). A feldolgozás előtt az eredeti név látszik.")}>
      <legend className="sr-only">{t("Megjelenített név")}</legend>
      <span className="small muted">{t("Név:")}</span>
      <label><input type="radio" name={group} checked={mode === "original"} onChange={() => setNameMode("original")} /> {t("Eredeti")}</label>
      <label><input type="radio" name={group} checked={mode === "unified"} onChange={() => setNameMode("unified")} /> {t("Egységes")}</label>
    </fieldset>
  );
}
