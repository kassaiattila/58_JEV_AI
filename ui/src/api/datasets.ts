// Datasets: the unified list query and download (056 U1, jav/api_datasets.py).
import { downloadPost, enc, request } from "./client";
import type { FilterOp } from "./types";

export type ColKind = "text" | "number" | "money" | "date" | "datetime" | "enum" | "bool" | "id";
export type LinkKind = "run" | "workpackage" | "next" | "reviews" | "review" | "item" | "process";
export interface DsColumn {
  key: string; label: string; kind: ColKind; hidden: boolean; labels: Record<string, string> | null; link?: LinkKind; field?: string;
  badge?: boolean; alert?: boolean; // 057: status badge; a value above 0 is highlighted
  percent?: boolean; // 062: a probability between 0 and 1, shown as a percentage
  names?: "original" | "unified"; // 082: the name column of an item list shows this name
  wrap?: "anywhere"; // 156: a name-like value (a file name, a path, an e-mail address) may break inside a word
  clamp?: number; // 183: the most lines a cell shows; the full value is its tooltip
}
export interface DsFilter { col: string; op: FilterOp; value?: string | string[] | null }
export interface DsSort { col: string; desc?: boolean }
export interface DsQuery { q?: string; filters?: DsFilter[]; sort?: DsSort[]; offset?: number; limit?: number; keys?: string[] }
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
