// Datasets: the unified list query and download (056 U1, jav/service/api_results.py).
import { downloadPost, enc, request } from "./client";
import type { FilterOp } from "./types";

export type ColKind = "text" | "number" | "money" | "date" | "datetime" | "enum" | "bool" | "id";
export type LinkKind = "run" | "workpackage" | "case" | "next" | "reviews" | "review" | "item" | "process" | "settings";
export interface DsColumn {
  key: string; label: string; kind: ColKind; hidden: boolean; labels: Record<string, string> | null; link?: LinkKind; field?: string;
  badge?: boolean; alert?: boolean; // 057: status badge; a value above 0 is highlighted
  percent?: boolean; // 062: a probability between 0 and 1, shown as a percentage
  names?: "original" | "unified"; // 082: the name column of an item list shows this name
  wrap?: "anywhere"; // 156: a name-like value (a file name, a path, an e-mail address) may break inside a word
  clamp?: number; // 183: the most lines a cell shows; the full value is its tooltip
  group?: boolean; // 263: the rows may be grouped by this column
  marks?: Record<string, string>; // 263: a badge's state mark by value (a version's state: active green, a draft a ring)
  /** 263: a link to a thing of Settings: its section, and the list its things stand in (a product's list) */
  section?: string; list?: string;
  /** 264: the row field that says this row's kind (the data points' value column holds every field's values) */
  kind_from?: string;
}
export interface DsFilter { col: string; op: FilterOp; value?: string | string[] | null }
export interface DsSort { col: string; desc?: boolean }
export interface DsQuery { q?: string; filters?: DsFilter[]; sort?: DsSort[]; offset?: number; limit?: number; keys?: string[]; group?: string }
export type DsRow = Record<string, unknown> & { _key: string; _run?: string | null; _wp?: string | null };
export interface DatasetSpec {
  name: string; label: string; scope: string[]; optional_scope: string[];
  /** 062: the service's default order (when no sort is requested, the rows come in this order). */
  natural_sort?: DsSort[];
}
export interface DsPage {
  dataset: DatasetSpec; columns: DsColumn[]; rows: DsRow[]; total: number; matched: number; offset: number; limit: number;
  facets: Record<string, string[]>;
  /** 086 (audit N01): a run's table — the version of the reviewed result these rows show */
  review_version?: string;
  /** 172: a table of the package's current result — the mark of the result these rows show (Approve and release) */
  result_mark?: string;
  /** 153: the package list's last rows, served while newer ones are being built */
  refreshing?: boolean;
  /** 263: the column the rows are grouped by, and each group's value (null: empty) with how many rows match */
  group?: string | null;
  groups?: { value: string | null; count: number }[];
}
export type DsScope = Record<string, string>;
export type ExportFormat = "xlsx" | "csv" | "json";
export type ExportRows = "all" | "filtered" | "selected";
export interface DsExport { format: ExportFormat; rows: ExportRows; columns?: string[] | null; query: DsQuery }


export const datasetsApi = {
  datasets: () => request<{ datasets: DatasetSpec[] }>("GET", "/datasets"),
  datasetQuery: (name: string, scope: DsScope, query: DsQuery) =>
    request<DsPage>("POST", `/datasets/${enc(name)}/query`, { scope, query }),
  datasetExport: (name: string, scope: DsScope, body: DsExport) =>
    downloadPost(`/datasets/${enc(name)}/export`, { scope, ...body }),
};
