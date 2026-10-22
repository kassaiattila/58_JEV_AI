// Output templates (jav/api_outputs.py).
import { enc, request } from "./client";

/** 178/179 (plan 170 L4): the outputs a person may give an own Excel template. */
export type OutputName = "package_result" | "utility_cost" | "reconcile_statement" | "quote";  // 196: the quote, a Word document
/** One problem or warning of a template's check: its code, the sheet or cell (`Sheet!B4`), a detail. */
export interface OutputTemplateIssue { code: string; where: string; detail: string }
export interface OutputTemplateCheck {
  output: OutputName; ok: boolean; problems: OutputTemplateIssue[]; warnings: OutputTemplateIssue[];
  values: string[]; tables: Record<string, string[]>;
}
export type OutputTemplateState = "draft" | "active" | "superseded" | "retired";
export interface OutputTemplateVersion {
  template: string; output: OutputName; name: string; version: number; state: OutputTemplateState; file_name: string;
  sha256: string; uploaded_by: string; uploaded_at: string; activated_by: string | null; activated_at: string | null;
  retired_by: string | null; retired_at: string | null; check: OutputTemplateCheck; size: number | null;
}
/** A template with its versions, newest first; `active`: the active version's number. */
export interface OutputTemplate {
  template: string; output: OutputName; name: string; active: number | null; retired: boolean; versions: OutputTemplateVersion[];
}
/** 179: a marker to copy (`{{invoices.amount}}`), its label in the built-in template, its kind, its total's marker. */
export interface OutputMarker { marker: string; label: string; kind: string; sum: string | null }
/** A group of markers: the values (`table` null), or a table (`part`: the document type of a table per type). */
export interface OutputMarkerGroup {
  table: string | null; part: string | null; label: string | null; count: string | null;
  months: { row: string; names: string } | null; rows: OutputMarker[];
}
export interface OutputTemplatesListing {
  templates: OutputTemplate[];
  outputs: Record<OutputName, { output: OutputName; what: string; format: "xlsx" | "docx"; markers: OutputMarkerGroup[] }>;
}
/** A package's choice per output: the chosen template (null: the built-in; `active` false: it was retired since, so
 *  the built-in is used) and the active templates it can choose. */
export interface PackageOutputChoice {
  chosen: { template: string; chosen_by: string; chosen_at: string; active: boolean; name: string | null; version: number | null } | null;
  templates: { template: string; name: string; version: number }[];
  /** 187: the choice's state, sent back with a change (`jav/decisions.py`). */
  decision_state?: number;
}
export interface PackageOutputChoices { workpackage_id: string; outputs: Partial<Record<OutputName, PackageOutputChoice>> }

export const outputsApi = {
  outputTemplates: () => request<OutputTemplatesListing>("GET", "/output-templates"),
  /** the service reads the file the system's file picker chose (a template can be larger than a request); a refused
   *  file gives 422 `template_refused` with the check (`ApiError.check`) */
  uploadOutputTemplate: (body: { output: OutputName; name: string; path: string; template?: string }) =>
    request<OutputTemplateVersion>("POST", "/output-templates", body),
  activateOutputTemplate: (template: string, version: number) =>
    request<OutputTemplateVersion>("POST", `/output-templates/${enc(template)}/versions/${version}/activate`, {}),
  retireOutputTemplate: (template: string) => request<OutputTemplateVersion>("POST", `/output-templates/${enc(template)}/retire`, {}),
  outputTemplateFileUrl: (template: string, version: number) => `/api/output-templates/${enc(template)}/versions/${version}/file`,
  outputTemplatePreviewUrl: (template: string, version: number, format: "xlsx" | "docx" = "xlsx") =>
    `/api/output-templates/${enc(template)}/versions/${version}/preview.${format}`,
  packageOutputTemplates: (wpId: string) => request<PackageOutputChoices>("GET", `/workpackages/${enc(wpId)}/output-templates`),
  choosePackageOutputTemplate: (wpId: string, output: OutputName, template: string | null, expectedState?: number) =>
    request<PackageOutputChoices>("PUT", `/workpackages/${enc(wpId)}/output-templates/${enc(output)}`,
      { template, ...(expectedState !== undefined ? { expected_state: expectedState } : {}) }),
};
