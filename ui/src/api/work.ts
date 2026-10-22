// The shared calls: work packages and their items, runs, the review and corrections, results and releases.
import type { Citation, NativeCitation, NativeCorrectionRequest, NativeItemResult, NativeSourcePage } from "../native";
import { enc, request } from "./client";
import type { AddSummary, Assignment, Budget, Call, CorrectionValue, ItemPreview, ItemResult, ItemSources, PackageResult, PackageRole, PackageVersion, Readiness, Reason, Run, RunView, SourcePage, SourceWord, Workpackage, WorkpackageBrief, WorkpackageRow, WorkpackageView } from "./types";


export const workApi = {
  workpackages: () => request<{ workpackages: WorkpackageRow[] }>("GET", "/workpackages"),
  workpackagesBrief: () => request<{ workpackages: WorkpackageBrief[] }>("GET", "/workpackages?brief=true"),
  workpackage: (id: string) => request<WorkpackageView>("GET", `/workpackages/${enc(id)}`),
  /** 081: `recursive` takes the PDFs of the subfolders too (the output folder of the named copies is left out). */
  createFromFolder: (folder: string, name?: string, recursive = false) =>
    request<{ workpackage: Workpackage; readiness: Readiness }>("POST", "/workpackages", { folder, ...(name ? { name } : {}), ...(recursive ? { recursive } : {}) }),
  /** 081: the operating system's own folder / file picker, opened by the local service on this machine. */
  pickFolder: (title: string, initial?: string) =>
    request<{ path: string | null }>("POST", "/local/pick-folder", { title, ...(initial ? { initial } : {}) }),
  pickFiles: (title: string, initial?: string) =>
    request<{ paths: string[] }>("POST", "/local/pick-files", { title, ...(initial ? { initial } : {}) }),
  createFromFiles: (paths: string[], name: string) =>
    request<{ workpackage: Workpackage; readiness: Readiness }>("POST", "/workpackages", { paths, name }),
  /** 187: `expectedState` is the task's `decision_state` as the page read it (a change on a stale page is a 409). */
  // 058: hiding (the runs and the results are kept), restoring, renaming; deletion only for a package without runs
  archiveWorkpackage: (id: string) => request<WorkpackageView>("POST", `/workpackages/${enc(id)}/archive`, {}),
  restoreWorkpackage: (id: string) => request<WorkpackageView>("POST", `/workpackages/${enc(id)}/restore`, {}),
  renameWorkpackage: (id: string, name: string) => request<WorkpackageView>("POST", `/workpackages/${enc(id)}/rename`, { name }),
  deleteWorkpackage: (id: string) => request<{ deleted: string }>("POST", `/workpackages/${enc(id)}/delete`, {}),
  /** 160-C S1 (decision 163 D2): a removal needs a reason; the person is the chosen user (the `X-Actor` header). */
  /** 160-C S2: documents added to an existing package; `added` says what happened (the service's own counts). */
  /** 168: what the person unticked in the preview stays out (`exclude`: new documents; `restore`: the only removed
   *  ones to bring back). */
  addItems: (id: string, sources: ItemSources, expected_revision: number, ticks?: { exclude: string[]; restore: string[] }) =>
    request<WorkpackageView & { added: AddSummary }>("POST", `/workpackages/${enc(id)}/items`, { ...sources, ...ticks, expected_revision }),
  /** 168: what adding the files or the folder would do, file by file; nothing is written. */
  previewItems: (id: string, sources: ItemSources) =>
    request<ItemPreview>("POST", `/workpackages/${enc(id)}/items/preview`, sources),
  /** 168: several items removed with one reason, or restored, in one step. */
  removeItems: (id: string, itemIds: string[], expected_revision: number, reason: string) =>
    request<WorkpackageView>("POST", `/workpackages/${enc(id)}/items/remove`, { item_ids: itemIds, expected_revision, reason }),
  restoreItems: (id: string, itemIds: string[], expected_revision: number) =>
    request<WorkpackageView>("POST", `/workpackages/${enc(id)}/items/restore`, { item_ids: itemIds, expected_revision }),
  /** 160-C S2: a statement package grows through its own survey (its party and period); 168: a folder's subfolders too. */
  removeItem: (id: string, itemId: string, expected_revision: number, reason: string) =>
    request<{ workpackage: Workpackage }>("POST", `/workpackages/${enc(id)}/items/${enc(itemId)}/remove`, { expected_revision, reason }),
  restoreItem: (id: string, itemId: string, expected_revision: number) =>
    request<{ workpackage: Workpackage }>("POST", `/workpackages/${enc(id)}/items/${enc(itemId)}/restore`, { expected_revision }),
  reviews: (id: string) =>
    request<{ items: { item_id: string; source_path: string; open_reasons: Reason[] }[]; open_reasons: number }>(
      "GET", `/workpackages/${enc(id)}/reviews`),
  saveWorkflow: (id: string, body: { recipe_id: string; params: Record<string, string>; expected_revision: number; note?: string }) =>
    request<{ assignment: Assignment }>("POST", `/workpackages/${enc(id)}/workflow`, body),
  readiness: (id: string) => request<Readiness>("GET", `/workpackages/${enc(id)}/workflow/readiness`),
  start: (id: string, body: { mode: "shadow" | "apply"; expected_revision: number; input_hash: string; rerun_of?: string; scope?: "all" | "pending" }) =>
    request<{ run_id: string; deduped: boolean; status: string }>("POST", `/workpackages/${enc(id)}/workflow/start`, body),
  wpRuns: (id: string) => request<{ runs: Run[] }>("GET", `/workpackages/${enc(id)}/runs`),
  runs: () => request<{ runs: Run[] }>("GET", "/runs"),
  run: (runId: string, names?: "original" | "unified") =>
    request<RunView>("GET", `/runs/${enc(runId)}${names === "unified" ? "?names=unified" : ""}`),
  journal: (runId: string) => request<{ calls: Call[]; budget: Budget }>("GET", `/runs/${enc(runId)}/journal`),
  cancel: (runId: string) => request<{ status: string }>("POST", `/runs/${enc(runId)}/cancel`, {}),
  supersede: (runId: string) =>
    request<{ run_id: string; superseded_by: string; reasons_closed: number; status: string }>("POST", `/runs/${enc(runId)}/supersede`, {}),
  /** 085: `reviewVersion` is the run view's `review_version` the approver saw; a correction saved since gives 409.
   *  160-C (decision 163 D7): `confirmRemoved` is the count of `removed_items` the approver saw (left out of the release). */
  approve: (runId: string, reviewVersion?: string, confirmRemoved?: number) =>
    request<RunView>("POST", `/runs/${enc(runId)}/approve`, {
      ...(reviewVersion ? { review_version: reviewVersion } : {}), ...(confirmRemoved ? { confirm_removed: confirmRemoved } : {}) }),
  /** 171/172: the package's current result and its release */
  packageResult: (wpId: string) => request<PackageResult>("GET", `/workpackages/${enc(wpId)}/result`),
  /** 172: Approve and release. `mark` is the result the person saw (a table's `result_mark`, else the view's);
   *  `confirmRemoved` the count of items removed from the package that the release leaves out. */
  releasePackage: (wpId: string, mark: string, confirmRemoved?: number) =>
    request<{ version: PackageVersion; result: PackageResult }>("POST", `/workpackages/${enc(wpId)}/release`, {
      expected_mark: mark, ...(confirmRemoved ? { confirm_removed: confirmRemoved } : {}) }),
  packageVersionFileUrl: (wpId: string, version: number, name: string) =>
    `/api/workpackages/${enc(wpId)}/versions/${version}/files/${enc(name)}`,
  packageResultXlsxUrl: (wpId: string) => `/api/workpackages/${enc(wpId)}/result/export.xlsx`,
  item: (runId: string, itemId: string) => request<ItemResult | NativeItemResult>("GET", `/runs/${enc(runId)}/items/${enc(itemId)}`),
  nativeSources: (runId: string, itemId: string, version: string, offset = 0) =>
    request<NativeSourcePage>("GET", `/runs/${enc(runId)}/items/${enc(itemId)}/sources?expected_result_version=${enc(version)}&offset=${offset}&limit=500`),
  resolveNativeCitations: (runId: string, itemId: string, version: string, citations: Citation[]) =>
    request<{ result_version: string; citations: NativeCitation[] }>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/citations/resolve`, { expected_result_version: version, citations }),
  saveNativeCorrection: (runId: string, itemId: string, body: NativeCorrectionRequest) =>
    request<NativeItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/correction`, body),
  saveCorrection: (runId: string, itemId: string, body: { fields: Record<string, CorrectionValue>; expected_revision: number; note?: string;
    sources?: Record<string, number[]>; confirm?: string[] }) =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/correction`, body),
  resolveReason: (reasonId: number, note?: string) =>
    request<{ status: string }>("POST", `/review-reasons/${reasonId}/resolve`, note ? { note } : {}),
  setOwner: (id: string, owner: string | null) => request<WorkpackageView>("POST", `/workpackages/${enc(id)}/owner`, { owner }),
  /** 181: an email routing package over email packages, and a person's decisions on its attachments */
  packageRoles: () => request<{ roles: PackageRole[] }>("GET", "/package-roles"),
  /** 181: a person gives the package its scope (any part may be left out) or takes its own scope away */
  setPackageScope: (id: string, scope: { party_id: string | null; period_start: string | null; period_end: string | null; role: string | null }) =>
    request<WorkpackageView>("POST", `/workpackages/${enc(id)}/scope`, scope),
  clearPackageScope: (id: string) => request<WorkpackageView>("POST", `/workpackages/${enc(id)}/scope/clear`, {}),
  writeNamedCopies: (runId: string) =>
    request<{ path: string; ready: number; review: number; skipped: number }>("POST", `/runs/${enc(runId)}/named-copies`, {}),
  namedCopiesZipUrl: (runId: string) => `/api/runs/${enc(runId)}/named-copies.zip`,
  exportUrl: (runId: string, format: "csv" | "xlsx" | "json", table = "documents") =>
    `/api/runs/${enc(runId)}/export?format=${format}&table=${table}`,
  sourceUrl: (wpId: string, itemId: string) => `/api/workpackages/${enc(wpId)}/items/${enc(itemId)}/source`,
  pageUrl: (wpId: string, itemId: string, page: number, dpi = 144) =>
    `/api/workpackages/${enc(wpId)}/items/${enc(itemId)}/pages/${page}.png?dpi=${dpi}`,
  /** 144: a page of the bank's PDF behind the statement of a line read by code */
  originalPageUrl: (wpId: string, lineId: string, page: number, dpi = 144) =>
    `/api/workpackages/${enc(wpId)}/reconcile/original/pages/${page}.png?line_id=${enc(lineId)}&dpi=${dpi}`,
  words: (runId: string, itemId: string) =>
    request<{ layer_id: string; pages: SourcePage[]; words: SourceWord[] }>("GET", `/runs/${enc(runId)}/items/${enc(itemId)}/words`),
};
