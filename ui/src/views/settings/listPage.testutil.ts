// 263 (E1): a list of Settings is a dataset; the tests give its page as the service answers it.
import type { DsColumn, DsPage, DsRow } from "../../api";

/** A dataset's page with every row on it (no grouping). */
export function listPage(name: string, columns: DsColumn[], rows: DsRow[]): DsPage {
  return { dataset: { name, label: name, scope: [], optional_scope: [] }, columns, rows, total: rows.length, matched: rows.length,
    offset: 0, limit: 100, facets: {} };
}

/** A column that opens a thing's page in Settings (its section, and a product list's word). */
export const linkCol = (key: string, label: string, section: string, list?: string): DsColumn =>
  ({ key, label, kind: "text", hidden: false, labels: null, link: "settings", section, ...(list ? { list } : {}) });
