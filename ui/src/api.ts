// Client of the local service (jav/api.py). Every call goes to the same address (/api), so there is no cross-origin
// request. On error, ApiError: the service's error code (not_found, revision_conflict, not_ready, invalid ...) and its
// message.
import { t } from "./i18n";
import type { Citation, DocumentFormat, NativeCitation, NativeCorrectionRequest, NativeItemResult, NativeSourcePage } from "./native";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public blockers: Blocker[] = [],
  ) {
    super(message);
  }
}

export interface Blocker { code: string; message: string }
/** 083: `field` is the simple field the to-do is about (null: about the document or a line item). */
export interface Reason { id: number; reason: string; producer: string; run_id: string; field?: string | null }
export interface Item { item_id: string; kind: string; source_path: string; sha256: string; added_revision: number; parent_item_id?: string }
export interface Assignment {
  workpackage_id: string; revision: number; recipe_id: string; recipe_version: number; recipe_hash: string;
  params: Record<string, string>; actor: string; note: string | null; created_at: string;
}
export interface Workpackage {
  id: string; name: string; source_kind: string; source_ref: string | null; revision: number; status: string;
  created_at: string; updated_at: string; items: Item[]; assignment: Assignment | null;
  owner?: string | null; // 061: the package's owner
}
export interface WorkpackageRow {
  id: string; name: string; source_kind: string; source_ref: string | null; revision: number; created_at: string;
  items: number; recipe_id: string | null; last_run_id: string | null; open_reasons: number;
}
/** 057: the package's next step (the service computes it in one place; both the list and the header button show it). */
export interface NextStep { code: string; label: string; stage: "process" | "review" | "result"; params?: Record<string, number> }
export interface RunRow {
  run_id: string; workpackage_id: string; workpackage_name: string; recipe_id: string; recipe_version: number; mode: "shadow" | "apply";
  status: string; approval: string | null; approved_by: string | null; actor: string; created_at: string; finished_at: string | null;
  items: number; items_done: number; open_reasons: number;
}
export interface WorkpackageView {
  workpackage: Workpackage; readiness: Readiness; titles?: Record<string, string>; next: NextStep; last_run: RunRow | null; runs: number;
  attachments_missing?: number; // 058 K5.2: in an email package, the number of PDF attachments not yet added
}
/** 080: what a run of the package will do (the pre-start overview): documents by their path known in advance (S / G /
 *  type not known yet), emails, emails with a task proposal, whether Azure may be used and earlier JEV answers reused. */
export interface RunPlan {
  documents: number; emails: number; attachments: number; paths: { S: number; G: number; unknown: number };
  tasks_emails: number; azure: boolean; jev_reuse: boolean;
  arm?: string; // 082: the chosen path (with S, a document on the G path has a type without a JEV path)
  jev?: boolean; // 086: false = processing without JEV (GPT recognises the type, every document on the G path)
}
export interface Readiness {
  workpackage_id: string; ready: boolean; blockers: Blocker[]; warnings: Blocker[]; counts: { items: number };
  budget: Record<string, string>; assignment_revision: number; input_hash: string;
  plan?: RunPlan; // 080
  assignment_default?: boolean; // 080: no saved settings yet; the default ones apply and are saved at start
}
export interface RecipeParam { allowed?: string[]; allowed_from?: string; default?: string }
export interface Recipe {
  input_kinds?: string[];
  file_suffixes?: string[];
  id: string; version: number; status?: "active" | "internal" | "retired"; title: string; description: string; steps: string[]; requirements: string[];
  result: string; manual_action: string; params: Record<string, RecipeParam>; max_item_usd: Record<string, Record<string, string>>;
  // 058 K5.2–K5.3: per-item budget by item kind (email / attachment) and the setting-dependent extra (task proposal)
  max_item_usd_by_kind?: Record<string, Record<string, Record<string, string>>>;
  param_item_usd?: { param: string; value: string; kind?: string; usd: Record<string, string>; drop?: string[] }[];
}
/** 064: the status of the store backup (store/backups/backup-status.json) and the settings of the daily backup. */
export interface BackupRun {
  created_at: string; ok: boolean; error?: string; dir?: string;
  /** 070: the compressed file of the internal working documents (`internal-docs.zip`) with the `entries` count */
  files?: { file: string; bytes: number; integrity: string; entries?: number }[];
  copy?: { dir: string; ok: boolean; verified: boolean; error?: string } | null;
}
/** 071 S-verzió: `commit` / `dirty` are null if the service was started without git. */
export interface PdfProtection {
  state: "protected" | "unprotected" | "unknown" | "stale";
  reason: string;
  configured: { isolated: boolean; memory_mb: number; require_memory_limit: boolean } | null;
  effective_memory_mb: number | null;
  helper_pid: number | null;
  process_pid: number | null;
  observed_at: number | null;
  reported_at?: number | null;
  max_age_s?: number;
}
export interface Health {
  ok: boolean; api_version: string; service_config: string;
  version: string; commit: string | null; dirty: boolean | null; started_at: string;
  /** 091: a fingerprint of the UI build the service hands out now (null without a build; missing on older services). */
  ui_build?: string | null;
  /** Missing on older services: no evidence of PDF memory protection. */
  pdf_protection?: { service: PdfProtection; worker: PdfProtection };
}
/** 075: the last dependency audit (`runs/deps-audit.json`), as `jav/deps_audit.py` `status()` returns it. */
export interface DepsAuditInfo {
  status: {
    checked_at: string; age_days: number; stale: boolean; finding_count: number; errors: string[];
    python?: { packages?: number }; npm?: { packages?: number };
  } | null;
  max_age_days: number;
}
/** 076: a paid call with an uncertain outcome, awaiting manual settlement (`jav/runtime/calls.py` `uncertain_list`). */
export interface UncertainCall {
  id: number; run_id: string; step_id: string; attempt: number; provider: string; model_requested: string | null;
  budget_scope: string | null; max_cost_usd: string; created_at: string; status: string;
}

export interface BackupInfo {
  status: BackupRun | null;
  config: { schedule?: string; keep?: number; copy_to?: string | null; with_burr?: boolean; with_docs?: boolean; max_age_hours?: number };
}
/** 063: the recipe explanations (`configs/recipe_help.json`): when a recipe fits, what a setting and its value mean;
 *  080: the general introduction, the item kinds and the comparison of the paths. */
export interface RecipeHelp {
  intro?: string;
  kinds?: Record<string, string>;
  recipes: Record<string, {
    when: string; title?: string;
    inputs?: { label: string; description: string }[];
    params?: RecipeHelp["params"];
  }>;
  paths?: { intro: string; measured: string; columns: { S: string; G: string }; rows: { label: string; S: string; G: string }[] };
  params: Record<string, { help: string; options: Record<string, string> }>;
}
export interface RunItem {
  run_id: string; item_id: string; status: string; final_status: string | null; flow_run_id: string | null;
  error: string | null; updated_at: string;
}
export interface Run {
  run_id: string; workpackage_id: string; mode: "shadow" | "apply"; assignment_revision: number; recipe_id: string;
  recipe_version: number; params: Record<string, string>; input_hash: string; status: string;
  approval: string | null; approved_by: string | null; approved_at: string | null; actor: string; created_at: string;
  finished_at: string | null; input: { workpackage_id: string; workpackage_revision: number; items: Item[] };
  items: RunItem[]; jobs: Record<string, number>;
  recipe?: { title?: string }; // the run's recipe snapshot (its title is shown in the interface)
  plan?: RunPlan | null; // 082: the pre-start overview saved at the start (null for an older run)
}
export interface Budget {
  scope: string; committed_usd: string; providers: Record<string, { limit_usd: string; committed_usd: string }>;
}
export interface RunView {
  run: Run; budget: Budget; open_reasons: Record<string, Reason[]>; earlier_open_reasons: Record<string, Reason[]>;
  titles?: Record<string, string>; // 048 T2: the readable title of an email item
  tables?: string[]; // 058: the result's views that contain data (an empty view is not shown)
  names?: Record<string, ItemName>; // 082: the items' unified names (only when asked for)
  costs?: RunCostView; // 082: planned and actual cost per provider
  review_version?: string; // 085: the version of the result shown; the approval sends it back
}
/** 082: one provider of a run — what the pre-start overview expected (yes / maybe / no; null for an older run), the
 *  budget, the paid calls (failed among them, still open), the known cost, the reserved maximum of the calls without a
 *  known cost, the answers reused from earlier, the models; `unexpected`: called although the overview did not count
 *  on it. Amounts are decimal text. */
export interface ProviderCost {
  provider: string; expected: "yes" | "maybe" | "no" | null; limit_usd: string | null; committed_usd: string | null;
  calls: number; failed: number; open: number; usd: string; held_usd: string; reused: number; models: string[]; unexpected: boolean;
}
/** 083: the run's actual cost over every provider; the reserved amount of the calls without a known cost apart. */
export interface CostTotal { usd: string; calls: number; failed: number; held_usd: string; reused: number }
export interface RunCostView { run_id: string; plan_saved: boolean; plan: RunPlan | null; providers: ProviderCost[]; total: CostTotal }
/** 082: an item's unified name. `state`: ready / review (uncertain, `check` says why) / pending (not processed yet) /
 *  none (an email has no file name of its own). */
export interface ItemName { unified: string | null; state: "ready" | "review" | "pending" | "none"; check: string | null; run_id: string | null }
export interface UtilitySource {
  item_id: string; file: string; amount: string; page: number | null; field: string; corrected: boolean; open_reasons: number;
  settlement?: boolean;
}
export interface UtilityCell { status: "ok" | "missing" | "partial" | "overlap"; amount: string | null; consumption: string | null; settlement: boolean; sources: UtilitySource[] }
export interface UtilitySeries {
  address: string; utility: string; summary_only: boolean; suppliers: string[]; consumption_unit: string | null; total: string;
  bills: number; cells: Record<string, UtilityCell>;
}
export interface UtilityReport {
  run_id: string; months: string[]; series: UtilitySeries[]; grand_total: string;
  unplaced: { item_id: string; file: string; doc_type: string; reason: string }[];
  duplicates: { item_id: string; file: string; doc_type: string; same_as: string; same_as_file: string; status?: "suspected" | "copy" | "variant" }[];
}
export interface Call {
  id: number; run_id: string; step_id: string; provider: string; model_actual: string | null; status: string;
  cost_usd: string | null; max_cost_usd: string; input_tokens: number | null; error: string | null; created_at: string;
}
export interface Correction {
  run_id: string; item_id: string; revision: number; fields: Record<string, CorrectionValue>;
  sources: Record<string, number[]>; actor: string | null; note: string | null; created_at: string | null;
  /** 083: the fields a person confirmed, with the value confirmed (it stays while the value does not change). */
  confirmed?: Record<string, unknown>;
}
/** Corrected value: a simple field, or a line list (rows with line-item fields / simple values) — 048. */
export type Cell = string | number | null;
export type CorrectionValue = Cell | (Record<string, Cell> | Cell)[];
export interface ListColumn { name: string; kind: string; options?: string[] }
/** One of the package's checks on the corrected (saved) data; `rows`: the failing row(s), numbered from 1, per list. */
export interface Check { name: string; ok: boolean; code: string; detail?: string | null; rows?: Record<string, number[]>; advisory?: boolean }
export type Box = [number, number, number, number];
export interface Region { page: number; bbox: Box; boxes: Box[]; word_ids: number[]; quote: string }
export interface Alternative extends Partial<Region> { value: string | null; raw?: string; p: number | null; machine?: boolean }
export type ProvStatus = "located" | "approximate" | "ambiguous" | "context_rejected" | "not_found" | "no_value" | "no_layer" | "error" | "list";
export interface Provenance extends Partial<Region> {
  status: ProvStatus; method: "pick" | "pick_line" | "search" | "manual" | "rows" | null; alternatives: Alternative[];
  confidence?: number | null; corrected?: boolean; present_p?: number | null; label?: boolean;
  multiple?: number | null; // 053: the number of places the value appears in (the box is on the most likely one)
  rows?: Provenance[]; // 053: line list — for each row, the row's location on the image
  // 091: a GPT field's confidence without JEV — the token probability of the value (null: not measurable), lowered by
  // a failed field check; it has its own band (`Bands.gpt`)
  confidence_basis?: { source: "gpt"; measure: string; token: number | null; failed_check: boolean } | null;
}
export interface SourcePage { page: number; width_pt: number; height_pt: number }
export interface SourceWord { id: number; page: number; line_no: number | null; text: string; x0: number; y0: number; x1: number; y1: number }
export interface Extraction {
  doc_type: string; arm: string; datapoints: Record<string, unknown>; field_conf: Record<string, number>;
  validation: { name: string; ok: boolean; code: string; detail?: string }[]; final_status: string;
  review_reasons: string[];
}
/** Email item (048 T2): the email and the result of intent recognition. */
export interface EmailItem {
  subject: string; sender: string | null; sender_name: string | null; to: string[]; received_at: string | null; mailbox: string | null;
  body: string; attachments: string[];
  /** 058 K5.1: how much of the email text intent recognition saw (computed in code). */
  body_coverage?: { status: "full" | "shortened" | "capped"; chars: number; own_chars: number; seen_chars: number; seen_lines: number;
    quoted_removed: boolean };
  result: { intent: string | null; intent_label: string | null; confidence: number | null; next_flow: string | null;
    attachments: { filename: string; doc_type?: string | null; status?: string | null }[]; from_this_run: boolean;
    signals: Record<string, number>; corrected?: boolean; machine_intent?: string | null } | null;
  /** 058 K5.3: task proposals after the gate, with the human decision (null = the run did not ask for proposals). */
  tasks?: { status: "proposed" | "skipped" | "error"; reason?: string | null; error?: string | null; tasks: EmailTask[];
    rejected: RejectedTask[] } | null;
  /** 086 (audit N04): the email as the item was added — `earlier`: it has changed since (this is the processed
   *  version); `changed`: that version is gone, no text is shown. */
  source_status?: "current" | "earlier" | "changed" | "unknown";
}
export interface EmailTask {
  index: number; action: string; title: string; due_date: string | null; assignee_hint: string | null;
  evidence: { pointer: string; quote: string }[];
  decision: { decision: "accepted" | "rejected"; actor: string; decided_at: string; done_by?: string | null; done_at?: string | null } | null;
  /** 062: how many identical proposals were merged into it (within one email). */
  merged?: number;
}
/** A proposal dropped by the evidence check in code; since 062 with its content and the part that failed (for earlier
 *  runs, only the reason). */
export interface RejectedTask {
  code: string; index?: number; action?: string; details?: string[];
  title?: string | null; due_date?: string | null; assignee_hint?: string | null;
  failed_parts?: ("task" | "evidence" | "due_date" | "assignee")[];
  quotes?: { part: "evidence" | "due_date" | "assignee"; pointer: string | null; quote: string; ok: boolean }[];
}
export interface MailboxRequest {
  accounts: string[]; folders?: string[]; subfolders?: boolean; since_days?: number | null;
  received_from?: string | null; received_to?: string | null; max_items?: number;
}
// 065: `eligible` = the (new) emails to download, `in_period` = all emails of the period
export interface MailboxCount { label: string; eligible: number; in_period: number; already_read: number; scanned: number; window: { from: string | null; to: string | null } }
export interface MailboxPull {
  id: string; schedule_id: string | null; request: MailboxRequest; label: string; actor: string; status: "queued" | "running" | "ok" | "error";
  result: { new?: number; changed?: number; duplicate?: number; workpackage?: string | null; error?: string; log?: string[] } | null;
  created_at: string; finished_at: string | null;
}
export interface MailboxSchedule {
  id: string; request: MailboxRequest; label: string; interval_min: number; enabled: boolean; actor: string; next_at: string;
  last_at: string | null; last_status: "ok" | "error" | null; last_result: MailboxPull["result"];
}
export interface ItemResult {
  run_id: string; item_id: string; kind?: "document" | "email"; email?: EmailItem; page_count?: number | null; extraction: Extraction | null; correction: Correction;
  attachment_items?: { item_id: string; filename: string }[]; // 058 K5.2: the email's attachments that ran as documents
  effective: Record<string, unknown>; open_reasons: Reason[]; earlier_open_reasons: Reason[];
  provenance: Record<string, Provenance>;
  lists?: Record<string, { columns: ListColumn[] }>; checks?: Check[];
  /** 081: the field kinds (money, number, date …), so amounts and quantities are edited the Hungarian way. */
  kinds?: Record<string, string>;
  source: { layer_id: string; text_source: string | null; pages: SourcePage[] } | null;
  /** Whether the document is shown from the copy kept when it was added (its source instance), and the state of the
   *  original file since then. */
  source_file?: { copy: boolean; original: "same" | "changed" | "missing" };
  /** 126: the duplicate suspicions and decisions of the document, the other document's values side by side. */
  duplicates?: DuplicatePair[];
}
/** 126: the code's kind of a suspected duplicate and a person's decision on the pair. */
export type DuplicateKind = "copy" | "variant" | "undecidable";
export type DuplicateDecision = "copy" | "variant" | "different";
export interface DuplicatePair {
  other_doc_id: string; other_file: string | null; other_run_id: string | null; other_item_id: string | null;
  other_workpackage_id: string | null;
  kind: DuplicateKind; reason_id: number | null; repeat: boolean;
  fields: { field: string; value: unknown; other_value: unknown; differs: boolean; missing: boolean }[];
  decision: DuplicateDecision | null; decided_by: string | null; decided_at: string | null;
}

// --- 056 U1: datasets (unified list query and download) -------------------------------------------------------
export type ColKind = "text" | "number" | "money" | "date" | "datetime" | "enum" | "bool" | "id";
export type LinkKind = "run" | "workpackage" | "next" | "reviews" | "review" | "item";
export interface DsColumn {
  key: string; label: string; kind: ColKind; hidden: boolean; labels: Record<string, string> | null; link?: LinkKind; field?: string;
  badge?: boolean; alert?: boolean; // 057: status badge; a value above 0 is highlighted
  percent?: boolean; // 062: a probability between 0 and 1, shown as a percentage
  names?: "original" | "unified"; // 082: the name column of an item list shows this name
}
export type FilterOp = "contains" | "eq" | "neq" | "in" | "gte" | "lte" | "empty" | "notempty";
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
}
export type DsScope = Record<string, string>;
export type ExportFormat = "xlsx" | "csv" | "json";
export type ExportRows = "all" | "filtered" | "selected";
export interface DsExport { format: ExportFormat; rows: ExportRows; columns?: string[] | null; query: DsQuery }

/** The download's file name from the header: the exact (UTF-8, RFC 5987) name, failing that the ASCII fallback
 *  (066: accented name). */
export function filenameFromDisposition(disp: string): string {
  const exact = /filename\*=UTF-8''([^;]+)/i.exec(disp)?.[1];
  if (exact) {
    try { return decodeURIComponent(exact); } catch { /* invalid encoding: the fallback name */ }
  }
  return /filename="([^"]+)"/.exec(disp)?.[1] ?? "letoltes";
}

/** Download by request → file (the legacy project's `downloadExport` pattern): the request can be a POST with a body,
 *  and it could carry the author header too (the export endpoints do not ask for one, so it is not sent). */
async function downloadPost(path: string, body: unknown): Promise<{ filename: string; rows: number }> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "offline", t("A helyi szolgáltatás nem érhető el. Fut a scripts\\dev.ps1 start?"));
  }
  if (!res.ok) {
    let d: { error?: string; message?: string } = {};
    try { d = await res.json(); } catch { /* the error response is not JSON */ }
    throw new ApiError(res.status, d.error ?? "error", d.message ?? `HTTP ${res.status}`);
  }
  const filename = filenameFromDisposition(res.headers.get("Content-Disposition") ?? "");
  const rows = Number(res.headers.get("X-Export-Rows") ?? "0");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { filename, rows };
}

/** 057: watched work folder (modelled on the legacy V4 „Figyelt mappák” (Watched folders)). */
export interface WatchedFolder {
  id?: string | null; name: string; path: string; enabled: boolean; recursive: boolean; batch_mode: "folder" | "daily";
  recipe_id: string | null; params: Record<string, string>; interval_min: number;
  next_at?: string | null; last_at?: string | null; last_status?: "ok" | "error" | null;
  last_result?: { new?: number; settling?: number; workpackage?: string | null; error?: string } | null;
}

const ACTOR_KEY = "jav.actor";
/** For a human decision (correction, approval, closing a to-do) the service requires the author's name. The Hungarian
 *  text is the translation key: displayed as `t(NO_ACTOR)`. */
export const NO_ACTOR = "add meg a neved fent a „Ki dolgozik?” mezőben (a javítás és a jóváhagyás szerzőhöz kötött)";

export function getActor(): string {
  try {
    return localStorage.getItem(ACTOR_KEY) ?? memoryActor;
  } catch {
    return memoryActor;
  }
}

/** 061: the views learn of changes to „Ki dolgozik?” (Who is working?) and to the name list from an event
 *  (`useActor`, `useEvent`). */
export const ACTOR_EVENT = "jav-actor";
export const USERS_EVENT = "jav-users";
/** 061: the service rejected the name because it is not on the Users list. Displayed as `t(UNKNOWN_ACTOR)`. */
export const UNKNOWN_ACTOR = "a „Ki dolgozik?” mezőben válaszd ki a neved a Felhasználók listájából";

let memoryActor = ""; // if the browser does not allow storage (private window), the name lasts for the session

// 066 Á21: the name is in the storage shared by the tabs, and a request always sends the name stored there. If it is
// changed in another tab, this tab's display updates too, so the tab shows the name its actions are sent with.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key === ACTOR_KEY || e.key === null) window.dispatchEvent(new Event(ACTOR_EVENT));
  });
}

export function setActor(name: string): void {
  memoryActor = name.trim();
  try {
    localStorage.setItem(ACTOR_KEY, memoryActor);
  } catch {
    /* storage may be forbidden in a private window; the name then lasts only for the session */
  }
  window.dispatchEvent(new Event(ACTOR_EVENT));
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const actor = getActor();
  if (actor) headers["X-Actor"] = encodeURIComponent(actor); // the service decodes it (accents in the header)
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "offline", t("A helyi szolgáltatás nem érhető el. Fut a scripts\\dev.ps1 start?"));
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const d = (data ?? {}) as { error?: string; message?: string; detail?: unknown; blockers?: Blocker[] };
    const missingActor = Array.isArray(d.detail) && d.detail.some((x) => Array.isArray(x?.loc) && x.loc.includes("x-actor"));
    const message = missingActor ? t(NO_ACTOR) : d.error === "unknown_user" ? t(UNKNOWN_ACTOR)
      : d.message ?? (typeof d.detail === "string" ? d.detail : `HTTP ${res.status}`);
    throw new ApiError(res.status, d.error ?? (res.status === 422 ? "invalid" : "error"), message, d.blockers ?? []);
  }
  return data as T;
}

const enc = encodeURIComponent;

export const api = {
  // 080: `recipes` holds only the active processing; `titles` every recipe's title (old runs, packages not yet migrated)
  recipes: () => request<{ recipes: Recipe[]; help?: RecipeHelp; titles?: Record<string, string> }>("GET", "/recipes"),
  workpackages: () => request<{ workpackages: WorkpackageRow[] }>("GET", "/workpackages"),
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
  decideTask: (runId: string, itemId: string, index: number, decision: "accepted" | "rejected") =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/tasks/${index}/decision`, { decision }),
  /** 126: a person's decision on a suspected duplicate pair (copy, modified version, not the same invoice). */
  decideDuplicate: (runId: string, itemId: string, otherDocId: string, decision: DuplicateDecision) =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/duplicates/${enc(otherDocId)}/decision`, { decision }),
  /** 062: the accepted task marked as done by hand (or unmarked). */
  markTaskDone: (runId: string, itemId: string, index: number, done: boolean) =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/tasks/${index}/done`, { done }),
  addAttachments: (id: string, expected_revision: number) =>
    request<WorkpackageView>("POST", `/workpackages/${enc(id)}/attachments`, { expected_revision }),
  // 058: hiding (the runs and the results are kept), restoring, renaming; deletion only for a package without runs
  archiveWorkpackage: (id: string) => request<WorkpackageView>("POST", `/workpackages/${enc(id)}/archive`, {}),
  restoreWorkpackage: (id: string) => request<WorkpackageView>("POST", `/workpackages/${enc(id)}/restore`, {}),
  renameWorkpackage: (id: string, name: string) => request<WorkpackageView>("POST", `/workpackages/${enc(id)}/rename`, { name }),
  deleteWorkpackage: (id: string) => request<{ deleted: string }>("POST", `/workpackages/${enc(id)}/delete`, {}),
  removeItem: (id: string, itemId: string, expected_revision: number) =>
    request<{ workpackage: Workpackage }>("POST", `/workpackages/${enc(id)}/items/${enc(itemId)}/remove`, { expected_revision }),
  reviews: (id: string) =>
    request<{ items: { item_id: string; source_path: string; open_reasons: Reason[] }[]; open_reasons: number }>(
      "GET", `/workpackages/${enc(id)}/reviews`),
  workflow: (id: string) =>
    request<{ assignment: Assignment | null; history: Assignment[] }>("GET", `/workpackages/${enc(id)}/workflow`),
  saveWorkflow: (id: string, body: { recipe_id: string; params: Record<string, string>; expected_revision: number; note?: string }) =>
    request<{ assignment: Assignment }>("POST", `/workpackages/${enc(id)}/workflow`, body),
  readiness: (id: string) => request<Readiness>("GET", `/workpackages/${enc(id)}/workflow/readiness`),
  start: (id: string, body: { mode: "shadow" | "apply"; expected_revision: number; input_hash: string; rerun_of?: string }) =>
    request<{ run_id: string; deduped: boolean; status: string }>("POST", `/workpackages/${enc(id)}/workflow/start`, body),
  wpRuns: (id: string) => request<{ runs: Run[] }>("GET", `/workpackages/${enc(id)}/runs`),
  runs: () => request<{ runs: Run[] }>("GET", "/runs"),
  run: (runId: string, names?: "original" | "unified") =>
    request<RunView>("GET", `/runs/${enc(runId)}${names === "unified" ? "?names=unified" : ""}`),
  journal: (runId: string) => request<{ calls: Call[]; budget: Budget }>("GET", `/runs/${enc(runId)}/journal`),
  cancel: (runId: string) => request<{ status: string }>("POST", `/runs/${enc(runId)}/cancel`, {}),
  /** 085: `reviewVersion` is the run view's `review_version` the approver saw; a correction saved since gives 409. */
  approve: (runId: string, reviewVersion?: string) =>
    request<RunView>("POST", `/runs/${enc(runId)}/approve`, reviewVersion ? { review_version: reviewVersion } : {}),
  documentFormats: () => request<{ formats: DocumentFormat[]; native_limits: Record<string, unknown> }>("GET", "/document-formats"),
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
  worker: () => request<{ running: boolean; stop_requested: boolean; jobs: Record<string, number>; pdf_protection?: PdfProtection }>("GET", "/worker"),
  users: () => request<{ users: string[] }>("GET", "/settings/users"),
  saveUsers: (users: string[]) => request<{ users: string[] }>("PUT", "/settings/users", { users }),
  setOwner: (id: string, owner: string | null) => request<WorkpackageView>("POST", `/workpackages/${enc(id)}/owner`, { owner }),
  folders: () => request<{ folders: WatchedFolder[]; roots: string[] }>("GET", "/settings/folders"),
  saveFolders: (folders: WatchedFolder[]) => request<{ folders: WatchedFolder[]; roots: string[] }>("PUT", "/settings/folders", {
    folders: folders.map(({ id, name, path, enabled, recursive, batch_mode, recipe_id, params, interval_min }) =>
      ({ id: id ?? null, name, path, enabled, recursive, batch_mode, recipe_id, params, interval_min })),
  }),
  scanFolder: (id: string) => request<{ status: string; new?: number; settling?: number; workpackage?: string | null; error?: string }>(
    "POST", `/settings/folders/${enc(id)}/scan`, {}),
  /** 078: where the content-named copies of a run are written (never inside a watched folder). */
  outputFolder: () => request<{ path: string | null }>("GET", "/settings/output-folder"),
  saveOutputFolder: (path: string | null) => request<{ path: string | null }>("PUT", "/settings/output-folder", { path }),
  /** 078: the run's documents under content-based names, with the manifest, into a new subfolder of the output folder. */
  writeNamedCopies: (runId: string) =>
    request<{ path: string; ready: number; review: number; skipped: number }>("POST", `/runs/${enc(runId)}/named-copies`, {}),
  namedCopiesZipUrl: (runId: string) => `/api/runs/${enc(runId)}/named-copies.zip`,
  workerStop: () => request<Record<string, unknown>>("POST", "/worker/stop", {}),
  /** 071: the running service's version and the commit recorded at start-up. */
  health: () => request<Health>("GET", "/health"),
  backupStatus: () => request<BackupInfo>("GET", "/system/backup"),
  depsAudit: () => request<DepsAuditInfo>("GET", "/system/deps-audit"),
  uncertainCalls: () => request<{ calls: UncertainCall[] }>("GET", "/system/uncertain-calls"),
  resolveUncertainCall: (id: number, body: { cost_usd: string | null; note: string }) =>
    request<{ ok: boolean }>("POST", `/system/uncertain-calls/${id}/resolve`, body),
  backupNow: () => request<BackupRun & { dir: string; copy: BackupRun["copy"] }>("POST", "/system/backup", {}),
  mailbox: () => request<{ schedules: MailboxSchedule[]; pulls: MailboxPull[]; bridge_available: boolean; accounts?: string[];
    defaults: { interval_min: number; lookback_days: number } }>("GET", "/mailbox"),
  mailboxCount: (req: MailboxRequest) => request<MailboxCount>("POST", "/mailbox/count", req),
  mailboxPull: (req: MailboxRequest) => request<MailboxPull>("POST", "/mailbox/pulls", req),
  createSchedule: (req: MailboxRequest, interval_min: number) =>
    request<MailboxSchedule>("POST", "/mailbox/schedules", { request: req, interval_min }),
  updateSchedule: (id: string, body: { enabled?: boolean; interval_min?: number }) =>
    request<MailboxSchedule>("PATCH", `/mailbox/schedules/${enc(id)}`, body),
  deleteSchedule: (id: string) => request<{ deleted: string }>("POST", `/mailbox/schedules/${enc(id)}/delete`, {}),
  utilityCost: (runId: string) => request<UtilityReport>("GET", `/runs/${enc(runId)}/reports/utility-cost`),
  datasets: () => request<{ datasets: DatasetSpec[] }>("GET", "/datasets"),
  datasetQuery: (name: string, scope: DsScope, query: DsQuery) =>
    request<DsPage>("POST", `/datasets/${enc(name)}/query`, { scope, query }),
  datasetExport: (name: string, scope: DsScope, body: DsExport) =>
    downloadPost(`/datasets/${enc(name)}/export`, { scope, ...body }),
  exportUrl: (runId: string, format: "csv" | "xlsx" | "json", table = "documents") =>
    `/api/runs/${enc(runId)}/export?format=${format}&table=${table}`,
  sourceUrl: (wpId: string, itemId: string) => `/api/workpackages/${enc(wpId)}/items/${enc(itemId)}/source`,
  pageUrl: (wpId: string, itemId: string, page: number, dpi = 144) =>
    `/api/workpackages/${enc(wpId)}/items/${enc(itemId)}/pages/${page}.png?dpi=${dpi}`,
  words: (runId: string, itemId: string) =>
    request<{ layer_id: string; pages: SourcePage[]; words: SourceWord[] }>("GET", `/runs/${enc(runId)}/items/${enc(itemId)}/words`),
  settings: () => request<{ confidence_bands: { confident: number; check: number; gpt?: { confident: number; check: number } } }>("GET", "/settings"),
  normalize: (doc_type: string, field: string, text: string) =>
    request<{ ok: boolean; value: string | null; reasons: string[]; kind: string }>("POST", "/normalize", { doc_type, field, text }),
};
