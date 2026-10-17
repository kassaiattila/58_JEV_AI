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
    /** 153: the field a correction's value could not be read in, and its kind (money, number or date) */
    public detail: { field?: string | null; kind?: string | null } = {},
  ) {
    super(message);
  }
}

export interface Blocker { code: string; message: string }
/** 083: `field` is the simple field the to-do is about (null: about the document or a line item). */
/** 150: `trial` (on an earlier reason only): raised by a trial run; the review page hides those by default. */
export interface Reason { id: number; reason: string; producer: string; run_id: string; field?: string | null; trial?: boolean }
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
/** 154: a package as stored, without its to-dos and next step (the workflow pickers need the name and the kind). */
export type WorkpackageBrief = Omit<WorkpackageRow, "open_reasons">;
/** 057: the package's next step (the service computes it in one place; both the list and the header button show it). */
export interface NextStep { code: string; label: string; stage: "process" | "review" | "result"; params?: Record<string, number> }
export interface RunRow {
  run_id: string; workpackage_id: string; workpackage_name: string; recipe_id: string; recipe_version: number; mode: "shadow" | "apply";
  status: string; approval: string | null; approved_by: string | null; actor: string; created_at: string; finished_at: string | null;
  items: number; items_done: number; open_reasons: number;
}
export interface WorkpackageView {
  workpackage: Workpackage; readiness: Readiness; titles?: Record<string, string>; next: NextStep; last_run: RunRow | null; runs: number;
  /** 153: the run the next step is about (a later run a person stopped does not hide an earlier finished one) */
  current_run?: RunRow | null;
  attachments_missing?: number; // 058 K5.2: in an email package, the number of PDF attachments not yet added
  /** 131: a reconciliation package's scope, counts and coverage (it has no files and no runs) */
  reconcile?: { scope: ReconcileScope; counts: ReconcileCounts; coverage: ReconcileCoverage[]; approval?: ReconcileApproval };
  /** 140: a statement package's party, period and each item's statement */
  statements?: StatementPackageView;
  /** 146: the workflow the package is a step of */
  workflow?: WorkflowRef | null;
  /** 152: the older live runs a person can supersede, oldest first */
  supersedable?: SupersedableRun[];
}
/** 080: what a run of the package will do (the pre-start overview): documents by their path known in advance (S / G /
 *  type not known yet), emails, emails with a task proposal, whether Azure may be used and earlier JEV answers reused. */
export interface RunPlan {
  documents: number; emails: number; attachments: number; paths: { S: number; G: number; unknown: number };
  tasks_emails: number; azure: boolean; jev_reuse: boolean;
  arm?: string; // 082: the chosen path (with S, a document on the G path has a type without a JEV path)
  jev?: boolean; // 086: false = processing without JEV (GPT recognises the type, every document on the G path)
  statement_tables?: number; // 136: statements from a bank's table export, read by code (free)
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
    /** 158: the running Python against the latest patch of its version line. */
    runtime?: { ok: boolean; running: string; latest?: string; latest_date?: string | null; error?: string };
    runtime_outdated?: boolean;
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
/** 146: one kind of bank file and its reader (`configs/bank_files.json` with the reader's own configuration). A reader
 *  nobody described yet is listed from its configuration alone (`described` false). */
export interface BankFile {
  id: string; reader: { profile?: string; type?: string }; read_by: "code" | "ai"; bank: string | null;
  statement: string | null; formats: string[]; suffixes: string[]; kinds: string[]; version: string;
  header: string[]; reads: string[]; not_read: string[]; checks: string[]; notes: string[]; described: boolean;
}
/** 146: which bank files the system reads; the texts are English source strings, `labels` the facts' field labels. */
export interface BankFilesCatalogue {
  version: string; intro: string; read_by: Record<"code" | "ai", string>; checks: Record<string, string>;
  files: BankFile[]; not_read: string[]; labels: Record<string, string>;
}
/** 146: the new work wizard's templates (`configs/workflows.json`); texts are English source strings. */
export type WorkKind = "documents" | "emails" | "statements" | "reconcile";
export type WorkSourceKind = "folder" | "files" | "mailbox" | "package" | "none";
export interface WorkflowTemplateStep { id: string; kind: WorkKind; title?: string; after?: string[] }
export interface WorkflowTemplate { id: string; group: string; title: string; description: string; steps: WorkflowTemplateStep[] }
export interface WorkflowTemplates {
  intro: string; groups: { id: string; title: string; description: string }[];
  kinds: Record<WorkKind, { title: string; description: string; sources: WorkSourceKind[]; cost: string }>;
  templates: WorkflowTemplate[];
}
export interface WorkflowSource {
  kind: WorkSourceKind; folder?: string; recursive?: boolean; paths?: string[]; request?: MailboxRequest; workpackage_id?: string;
  /** 147: a documents step takes only the documents no live run has processed yet */
  only_new?: boolean;
}
export type WorkflowBudget = Partial<Record<"jev" | "openai" | "azure_di", string>>;
/** 160-D: the AI engine — JEV and GPT (the default) or GPT only, without JEV. */
export type Engine = "jev" | "gpt";
/** 160-D: the application's AI engine, the default of every new processing setting that does not name one. */
export interface EngineSetting { engine: Engine; actor: string | null; updated_at: string | null }
export interface WorkflowEstimate {
  items: number | null; usd: WorkflowBudget; note: string | null; statements?: number; pdfs?: number; per_item?: WorkflowBudget;
  left_out?: number;
}
/** What a person sees of a step: the stored automation state and the package's own next step. */
export type WorkflowStepStatus = "waiting" | "ready" | "starting" | "pulling" | "needs_budget" | "nothing_new" | "failed"
  | "running" | "review" | "approve" | "approved" | "pairing" | "attention" | "missing";
export interface WorkflowStep {
  id: string; kind: WorkKind; title: string; kind_title: string; after: string[];
  source: { kind: WorkSourceKind; folder?: string; recursive?: boolean; count?: number; first?: string; accounts?: string[];
    folders?: string[]; workpackage_id?: string; only_new?: boolean };
  budget: WorkflowBudget; name: string; state: string; status: WorkflowStepStatus; done: boolean;
  /** 160-D: the step's own AI engine; null: the application's when the step starts */
  engine?: Engine | null;
  note: string | { estimate: WorkflowBudget; budget: WorkflowBudget; over: WorkflowBudget } | null;
  package: { id: string; name: string | null; next: NextStep | null } | null; run_id: string | null; pull_id: string | null;
  updated_at: string;
}
export interface WorkflowInfo {
  id: string; template: string; template_title: string; name: string; party_id: string; party: string;
  period_start: string; period_end: string; auto: boolean; status: "open" | "archived"; actor: string;
  created_at: string; updated_at: string;
}
export interface WorkflowView {
  workflow: WorkflowInfo; steps: WorkflowStep[]; done: number; total: number;
  next: { step: string; status: WorkflowStepStatus } | null;
  events: { step: string | null; action: string; actor: string; detail: Record<string, unknown>; created_at: string }[];
  /** 147: the workflow this one repeats for the next period, and the ones repeating it */
  repeat_of?: WorkflowBrief | null; repeated_as?: WorkflowBrief[];
}
/** 147: the quick review of a reconciliation package (jav/reconcile_review.py): the lines to decide in groups by what
 *  is known of them, each group accepted at once. */
export type QuickReviewGroupId = "sure_pairs" | "earlier" | "bank_category" | "salary_rule" | "ai_sure" | "ai_review"
  | "expects_invoice" | "rest";
export interface QuickReviewLine {
  id: string; statement_id: string; booking_date: string | null; amount: string | null; currency: string | null;
  direction: string | null; counterparty_name: string | null; memo: string | null; description: string | null;
  file?: string | null; partner?: string | null;
  /** the reason a mark group suggests */
  category?: string;
  /** the invoices a sure pair pays */
  invoices?: { id: string; number: string | null; supplier_name: string | null; partner_name?: string | null; amount: string | null; currency: string | null;
    issue_date: string | null }[];
  ai?: Partial<Record<"jev" | "gpt", { kind: string; probability: number | null }>>;
  earlier_lines?: number;
}
export interface QuickReviewGroup {
  id: QuickReviewGroupId; action: "pair" | "mark" | "none"; lines: QuickReviewLine[]; count: number; totals: Record<string, string>;
  /** 158: how many of the lines a person decides (the incoming money "an invoice is expected" shows is information only). */
  to_decide?: number;
}
export interface QuickReview {
  workpackage_id: string; threshold: number; groups: QuickReviewGroup[];
  excluded: Record<string, { count: number; totals: Record<string, string>; lines: QuickReviewLine[] }>;
  decided: Record<string, number>;
}
export interface WorkflowBrief { id: string; name: string; period_start: string; period_end: string }
/** 147: a workflow for the next period, as the wizard shows it filled in (a step without a source is asked for). */
export interface WorkflowDraft {
  template: string; party_id: string; period_start: string; period_end: string; name: string | null; auto: boolean;
  previous: string; steps: Record<string, { source: WorkflowSource | null; budget: WorkflowBudget; engine?: Engine | null }>;
}
export interface WorkflowRow extends WorkflowInfo {
  done: number; total: number; next: { step: string; status: WorkflowStepStatus } | null;
  steps: { id: string; title: string; status: WorkflowStepStatus }[];
}
export interface WorkflowRef { id: string; name: string; step: string; step_title: string }
export interface CreateWorkflowBody {
  template: string; party_id: string; period_start: string; period_end: string; name?: string; auto: boolean;
  names?: Record<string, string>; steps: Record<string, { source: WorkflowSource; budget?: WorkflowBudget; engine?: Engine | null }>;
  previous?: string;
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
  supersede?: SupersedeInfo | null; // 151: a later live run repeated this one; it can be superseded
  superseded?: { by: string; actor: string; at: string; reasons_closed: number } | null; // 151: who superseded it
  engine?: Engine | null; // 160-D: the AI engine the run ran with (absent from an older service)
}
/** 151: the later live run that repeated this one, its own open to-dos that would close, and the human work done on it. */
export interface SupersedeInfo { by: string; open_reasons: number; resolved_reasons: number; corrected_items: number }
/** 152: an older live run of a package that a person can supersede, with the offer of its own page */
export interface SupersedableRun extends SupersedeInfo { run_id: string; created_at: string }
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
    // 126: shown_type = the type the attachment was processed as (e.g. a foreign receipt as a foreign invoice)
    attachments: { filename: string; doc_type?: string | null; shown_type?: string | null; status?: string | null }[]; from_this_run: boolean;
    signals: Record<string, number>; corrected?: boolean; machine_intent?: string | null;
    /** 149: read from the Sent Items folder, so its intent was not asked. */
    sent?: boolean } | null;
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
  run_id: string; item_id: string; kind?: "document" | "email" | "statement_table"; email?: EmailItem; page_count?: number | null; extraction: Extraction | null; correction: Correction;
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
  /** 139: the statement that replaced this one, the ones it replaced, and the undecided ones of the same days. */
  statements?: StatementRelation[];
  /** 160-D: the AI engine of the run that produced the result shown; null for a statement read by code and for an
   *  email intent taken from another run. */
  engine?: Engine | null;
}
/** 139: one statement of the same account and days as this one: it replaced this one (`replaced_by`), this one replaced
 *  it (`replaces`), or neither, and a person chooses (`conflict`); `how`: by the rule of ranks or by a person. */
export type StatementRelationKind = "replaced_by" | "replaces" | "conflict";
export interface StatementRelation {
  other_doc_id: string; other_file: string | null; relation: StatementRelationKind; how: "rule" | "person" | null;
  other_run_id: string | null; other_item_id: string | null; other_workpackage_id: string | null;
  period: [string | null, string | null]; other_period: [string | null, string | null];
  rank: string; other_rank: string; lines: number; other_lines: number;
  carried: number | null; left_over: number | null; reason_id: number | null;
  kept: string | null; decided_by: string | null; decided_at: string | null;
}
export type StatementKeep = "this" | "other" | "rule";
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
/** 131: the payment method (an invoice payable by cheque, a line through a cheque payment app) and a name learnt from an
 * earlier confirmed pair also tie a line to an invoice. */
export type ReconcileSignal = "invoice_number" | "reference" | "supplier_account" | "supplier_name" | "supplier_name_fuzzy"
  | "payment_channel" | "learned_name";
/** 130: how the amounts of a pair relate; the fx ones are a card line against an invoice of another currency. */
/** 141: combined - one of the invoices a line's memo names, whose amounts together are the line's */
export type ReconcileRelation = "equal" | "different" | "fx_within" | "fx_outside" | "no_rate" | "combined";
/** 130: a card pair's conversion at the MNB rate of the invoice's issue date (deviation: the line's, as a fraction). */
export interface ReconcileFx { rate: string; rate_day: string; source: string; converted: string; deviation: string;
  /** 149: a forint bank line's rate day: the invoice's fulfilment day or the line's booking day (none: a card line). */
  basis?: "fulfillment" | "booking" }

// --- 131–132: the reconciliation package (jav/reconcile_package.py) -----------------------------------------------
/** An own account or card the store has statements of (the scope is chosen from these). */
export interface ReconcileAccount {
  key: string; account: string | null; statement_types: string[]; currencies: string[]; statements: number;
  first: string | null; last: string | null;
  party?: PartyRef | null; // 133: the own party the account belongs to
  registered?: (AccountDetails & { label: string }) | null; // 138: registered with its party (statements may be 0)
}
export interface ReconcileScope {
  workpackage_id: string; accounts: string[]; period_start: string; period_end: string; revision: number; updated_at: string;
  party_id?: string | null; party?: PartyRef | null; // 133: the package's own party; none: every invoice is its own
}
/** A line's state: proposed / amount_only / partly_allocated / open still need a person; allocated, marked (needs no
 *  invoice) and excluded (no usable amount) do not. */
export type ReconcileLineState = "proposed" | "amount_only" | "partly_allocated" | "open" | "allocated" | "marked" | "excluded";
export const OPEN_LINE_STATES: ReconcileLineState[] = ["proposed", "amount_only", "partly_allocated", "open"];
export interface ReconcileCandidate {
  invoice_id: string; line_id: string; proposed: boolean; amount_only: boolean; signals: ReconcileSignal[];
  amount_relation: ReconcileRelation | null; multiple_candidates: boolean; source_review_required: boolean; fx: ReconcileFx | null;
  /** 134: how strongly it is tied (0-100), the days from the issue date to the booking, booked by the due date */
  strength?: number; days_after_issue?: number | null; by_due?: boolean;
  /** 137: compared on the card purchase's original amount, as the bank printed it */
  original?: { amount: string; currency: string } | null;
  /** 141: a combined payment's invoices, in the order of issue */
  combined?: string[] | null;
  /** 151: a forint bank line paying invoices of another currency together: their sum converted, the line's deviation */
  combined_fx?: { basis: "fulfillment" | "booking"; converted: string; deviation: string } | null;
}
/** An allocation of a line's amount to an invoice; `allocation_id` null: a confirmation from the review page (129). */
export interface ReconcileShare {
  invoice_id: string; line_id: string; line_amount: string; invoice_amount: string; allocation_id: number | null;
  workpackage_id: string | null;
}
export interface ReconcileLineMark { id: number; line_id: string; statement_id: string; category: string; note: string | null; workpackage_id: string | null }
export interface ReconcileLine extends ReconcileLineDetails {  // 144: with the facts beyond the money
  id: string; statement_id: string; account: string; statement_type: string | null; currency: string | null;
  booking_date: string | null; direction: string | null; amount: string | null; counterparty_name: string | null;
  counterparty_account: string | null; description: string | null; memo: string | null;
  /** 137: a card purchase's original amount and currency (the Erste PDF statement) */
  original_amount?: string | null; original_currency?: string | null;
  /** 142: the value day and the balance after the line, as the statement prints them (shown on the card) */
  value_date?: string | null; running_balance?: string | null;
  state: ReconcileLineState; excluded_reason: string | null; allocated: string; rest: string | null;
  mark: ReconcileLineMark | null; allocations: ReconcileShare[]; candidates: ReconcileCandidate[]; rejected: string[];
  statement_verified: boolean; file: string | null;
  other_candidates?: { invoice_id: string; party: string | null }[]; // 133: candidates among another party's invoices
  ai?: Partial<Record<ReconcileAiEngine, ReconcileAiProposal>>; // 134: the AI's stored answers about the line
  /** 135: the counterparty name without its reference numbers (null: no name), and the needs-no-invoice reasons a
   *  person gave the partner's other lines, the most frequent first (none through a payment app) */
  partner?: string | null; earlier_marks?: { category: string; lines: number }[];
  /** 140: the needs-no-invoice reason the line's own category suggests (configs/reconcile.json category_marks) */
  category_mark?: string | null;
  /** 153: it went to an account a stored statement prints but no own party holds: a transfer between own accounts? */
  own_account_unregistered?: boolean;
  /** 145: the approved statement (package and version) that locks the line; null: none */
  locked?: { workpackage_id: string; version: number } | null;
}

// --- 145: the reconciliation result (jav/reconcile_statement.py) ------------------------------------------------------
export interface ReconcileVersionMeta {
  version: number; fingerprint: string; approved_by: string; approved_at: string;
  reopened_by: string | null; reopened_at: string | null; reopen_note: string | null;
}
export interface ReconcileApproval { active: ReconcileVersionMeta | null; versions: ReconcileVersionMeta[] }
export type ReconcileInvoiceResult = "paid" | "partly_paid" | "credited" | "undecided" | "no_payment_found" | "not_covered";
export type ReconcileLineResult = "paired" | "partly_paired" | "needs_no_invoice" | "left_out" | "open";
export interface ReconcileStatementInvoice {
  id: string; number: string | null; supplier_name: string | null; supplier_tax_id: string | null; issue_date: string | null;
  fulfillment_date: string | null; due_date: string | null; amount: string | null; currency: string | null;
  payment_method: string | null; file: string | null; result: ReconcileInvoiceResult; engine_state: string | null;
  allocated: string; rest: string | null; paid_on: string | null; days_from_due: number | null; overdue_days: number | null;
  double_payment: boolean; credited_by: string | null; other_party: string | null; source: string | null;
  paid_by: { line_id: string; line_amount: string; invoice_amount: string; booking_date: string | null; account: string | null; in_scope: boolean }[];
}
export interface ReconcileStatementRow {
  id: string; account: string; currency: string | null; booking_date: string | null; value_date: string | null;
  direction: string | null; amount: string | null; counterparty_name: string | null; counterparty_account: string | null;
  memo: string | null; description: string | null; file: string | null; statement_verified: boolean;
  result: ReconcileLineResult; engine_state: string; reason: string | null; note: string | null; allocated: string; rest: string | null;
  pays: { invoice_id: string; number: string | null; supplier_name: string | null; line_amount: string; invoice_amount: string }[];
}
export interface ReconcileWarning { code: string; doc_id?: string; file?: string | null; account?: string; month?: string }
export interface ReconcileStatement {
  format: number; package: { id: string; name: string }; party: string | null; period: [string, string]; accounts: string[];
  invoices: ReconcileStatementInvoice[]; lines: ReconcileStatementRow[]; warnings: ReconcileWarning[];
  counts: { invoices: Record<string, number>; lines: Record<string, number>; open_lines: number };
}
export interface ReconcileStatementCurrent {
  statement: ReconcileStatement; fingerprint: string; blockers: ReconcileBlocker[]; warnings: ReconcileWarning[];
  approval: ReconcileApproval;
}
export interface ReconcileStatementVersion extends ReconcileVersionMeta { statement: ReconcileStatement }
/** 140: a statement of a statement package's survey or of the store, as a reference (jav/statement_package.py). */
export interface StatementRef {
  id: string; file: string | null; period_start: string | null; period_end: string | null; rank: string; in_store: boolean;
}
/** 140: a statement the surveyed files hold: its account's last four characters, month, checks and source rank, whose
 *  account it is, and what it would replace or be replaced by; `chosen` is the proposed tick. No line or balance. */
export interface StatementSurveyRow {
  id: string; institution: string; file: string; companion: string | null; title: string; account: string | null;
  currency: string | null; period_start: string | null; period_end: string | null; lines: number; checks_ok: boolean;
  balance_checked: boolean; rank: string; in_period: boolean; in_store: boolean;
  owner: "package" | "none" | "other"; owner_party: { id: string; name: string } | null;
  replaces: StatementRef[]; replaced_by: StatementRef | null; conflicts: StatementRef[]; chosen: boolean;
}
/** 140: a PDF of the surveyed files that no export uses: processed with type recognition and AI extraction. */
export interface StatementSurveyPdf { path: string; file: string; sha256: string; in_store: boolean; statement: StatementRef | null; chosen: boolean }
export interface StatementPackageSurvey {
  party: { id: string; name: string }; period_start: string; period_end: string;
  statements: StatementSurveyRow[]; pdfs: StatementSurveyPdf[]; skipped: { file: string; reason: string }[];
}
export type StatementItemState = "valid" | "replaced" | "conflict" | "pending";
/** 140: a statement package item's statement: valid, replaced, in a conflict a person decides, or pending. */
export interface StatementPackageItem {
  item_id: string; kind: string; file: string; state: StatementItemState; account?: string | null; currency?: string | null;
  period_start?: string | null; period_end?: string | null; rank?: string; work_run?: string | null;
  replaced_by?: string | null; replaces?: string[]; conflicts?: string[];
}
export interface StatementPackageView {
  scope: { workpackage_id: string; party_id: string; party: { id: string; name: string }; period_start: string; period_end: string; revision: number };
  statements: StatementPackageItem[];
}
export interface StatementPackageSources { paths: string[]; party_id: string; period_start: string; period_end: string }
/** 134: JEV's or GPT's raw answer about a statement line (jav/reconcile_ai.py); a person decides. */
export type ReconcileAiEngine = "jev" | "gpt";
export interface ReconcileAiProposal {
  pays: string | null; pays_probability: number | null; options: string[]; kind: string | null; kind_probability: number | null;
  suggested_mark: string | null; expects_invoice: boolean | null; measured: boolean; error: string | null; created_at: string;
  /** 136: the partner's line that was asked, when this line took the kind of payment over from it (no call) */
  asked_line_id?: string | null;
}
export interface ReconcileInvoice {
  id: string; doc_type: string; number: string | null; supplier_name: string | null; amount: string | null; currency: string | null;
  /** 148: an own party's outgoing invoice, and the partner it is shown by (the buyer of an outgoing invoice) */
  outgoing?: boolean; partner_name?: string | null;
  issue_date: string | null; due_date: string | null; payment_method: string | null; file: string | null; state: string | null;
  allocated: string; rest: string | null; allocations: ReconcileShare[]; candidates: ReconcileCandidate[];
  source: "approved" | "not_approved" | "no_run";
  party?: (PartyRef & { how: PartyHow }) | null; // 133: the buyer's own party; none: no party claims it
  own?: boolean; // 133: the package's party's or no party's (listed by default); false: another party's
  credited_by?: { id: string; number: string | null } | null; // 141: the credit note that cancels it
  /** 142: every fact the card shows, and the last day its statements cover it without a gap from its issue date */
  supplier_tax_id?: string | null; payment_account?: string | null; references?: string[]; buyer_name?: string | null;
  fulfillment_date?: string | null; net_total?: string | null; vat_total?: string | null; duplicate?: string | null;
  checked_until?: string | null;
}
/** 142 (jav/reconcile_overview.py): the related lines and invoices as groups, with their pairs, kind, flags and lists. */
export type ReconcileGroupKind = "proposed" | "paired" | "line_only" | "invoice_only" | "credited" | "marked" | "excluded";
export type ReconcileList = "to_decide" | "line_without_invoice" | "invoice_without_payment" | "overdue" | "late" | "double_payment"
  | "clarify" | "paired" | "marked" | "credited" | "excluded";
export type ReconcileFlag = "late" | "overdue" | "double_payment" | "several_candidates" | "amount_differs" | "statement_unverified"
  | "rest_left" | "no_due_date" | "paid_elsewhere";
export interface ReconcileGroupPair {
  line_id: string; invoice_id: string; state: "allocated" | "proposed" | "repeat";
  /** the days from the invoice's due date to the line's booking day (positive: late); null without a due date */
  days_from_due: number | null; several?: boolean; relation?: ReconcileRelation | null;
  line_amount?: string; invoice_amount?: string; allocation_id?: number | null;
}
export interface ReconcileGroup {
  id: string; kind: ReconcileGroupKind; date: string; lines: string[]; invoices: string[]; pairs: ReconcileGroupPair[];
  flags: ReconcileFlag[]; lists: ReconcileList[];
}
export interface ReconcileInvoiceFacts {
  paid_on: string | null; days_from_due: number | null; overdue_days: number | null; checked_until: string | null;
  double_payment: { line_ids: string[]; paid_by: string[] } | null;
}
export interface ReconcileOverview {
  groups: ReconcileGroup[]; invoices: Record<string, ReconcileInvoiceFacts>; counts: Record<ReconcileList | "all", number>;
}
/** Where a document's image opens: the package, run and item of its work run (none for a command-line evaluation). */
export interface ReconcileOpen { workpackage_id: string; run_id: string; item_id: string; pages: number | null }
export interface ReconcileCoverage { account: string; month: string; statements: number; verified: number }
export interface ReconcileBlocker { code: string; doc_id: string; file: string | null; kind: "statement" | "invoice" }
export interface ReconcileCounts { lines: Record<string, number>; invoices: Record<string, number>; open_lines: number; other_invoices?: number }
/** 139: a decision made on a line of a replaced statement that has no same line on the statement replacing it. */
export interface ReconcileLeftOver {
  kind: "allocation" | "mark" | "decision"; ref: string; line_id: string; statement_id: string; replaced_by: string;
  invoice_id: string | null; category: string | null; decision: string | null; workpackage_id: string | null;
  currency: string | null; booking_date: string | null; amount: string | null; direction: string | null;
  counterparty_name: string | null; file: string | null; replaced_by_file: string | null; invoice_file: string | null;
}
/** 153 (review A3): an allocation that no longer fits its line or invoice (an amount changed since it was made). */
/** 153: a pairing that no longer fits the amounts; 160 (review M-1): also one whose invoice left the pairing, and a
 *  pairing or a mark whose line is no longer on its statement (`reason`). */
export interface ReconcileUnfit {
  kind: "allocation" | "mark"; ref: string; reason: "amounts" | "invoice_left_out" | "line_gone"; line_id: string;
  invoice_id: string | null; invoice_reason: string | null; category: string | null; statement_id: string | null;
  workpackage_id: string | null; line_amount: string | null; invoice_amount: string | null; line_total: string | null;
  invoice_total: string | null; currency: string | null; booking_date: string | null; direction: string | null;
  counterparty_name: string | null; invoice_file: string | null; file: string | null;
}
export interface ReconcileWorkspace {
  workpackage_id: string; scope: ReconcileScope; lines: ReconcileLine[]; invoices: ReconcileInvoice[];
  left_over?: ReconcileLeftOver[];
  unfit?: ReconcileUnfit[];
  /** 145: what warns without blocking the approval (a statement whose balances do not check out), and the approval */
  warnings?: ReconcileBlocker[]; approval?: ReconcileApproval;
  coverage: ReconcileCoverage[]; blockers: ReconcileBlocker[]; line_marks: string[]; open: Record<string, ReconcileOpen>;
  counts: ReconcileCounts; learned_names: unknown; fx_tolerance: unknown; engine_version: string; config_hash: string;
  overview?: ReconcileOverview; // 142: the cards of the pairing page
  decision_state?: unknown; // what the decisions read (145: the result reloads when it changes)
}
/** 132: where a line stands on its statement page (box: 0–1 fractions of the page, x0 y0 x1 y1). */
/** 144: a statement line as the statement prints it (the documents' statement pane, jav/reconcile_package.py `locate`). */
export type ReconcileStatementLine = {
  id?: string; booking_date: string | null; value_date?: string | null; direction: string | null; amount: string | null;
  original_amount?: string | null; original_currency?: string | null; counterparty_name: string | null;
  counterparty_account: string | null; memo: string | null; description: string | null; running_balance?: string | null;
} & ReconcileLineDetails;
/** 144: a statement line's facts beyond the money, as a code reader keeps them (only the ones its statement prints; a
 *  card number masked to its first six and last four digits). */
export interface ReconcileLineDetails {
  bank_reference?: string; order_id?: string; end_to_end_id?: string; card_number?: string; purchase_date?: string;
  transaction_time?: string; terminal?: string; authorisation_code?: string; exchange_rate?: string; fee?: string;
}
/** 144: the statement of a line as read: its heading facts and every line in its order. */
export interface ReconcileStatementView {
  file: string | null; institution: string | null; account: string; currency: string | null; period_start: string | null;
  period_end: string | null; opening_balance: string | null; closing_balance: string | null; verified: boolean;
  lines: (ReconcileStatementLine & { id: string })[];
}
/** 144: the bank's PDF behind a statement read by code — found, missing (moved or changed since the reading), or none
 *  (a table or XML export). */
export interface ReconcileOriginal { file: string | null; state: "found" | "missing" | "export" }
export interface ReconcileLocation {
  line_id: string; statement_id: string; open: ReconcileOpen | null;
  /** 144: the page image to show: the statement's own document, the bank's PDF behind a statement read by code, none */
  image: "item" | "original" | null; pages: number | null;
  page: number | null; box: [number, number, number, number] | null;
  original: ReconcileOriginal | null; statement: ReconcileStatementView;
}
export interface ReconcileAllocationPair { invoice_doc_id: string; line_id: string; line_amount?: string; invoice_amount?: string }
/** 143 (jav/reconcile_package.py `matches`): how an invoice fits a line — proposed or listed by the engine for it, its
 *  number or reference in the line's text, tied by a signal in its payment window, or of the same amount there. */
export type ReconcileFit = "proposed" | "candidate" | "named" | "tied" | "same_amount";
/** 143: one invoice compared with the selected line in code (jav/reconcile.py `compare`), on what is left of both. */
export interface ReconcileMatch {
  invoice_id: string; fit: ReconcileFit | null; signals: ReconcileSignal[]; amount_relation: ReconcileRelation | null;
  fx: ReconcileFx | null;
  /** the invoice's amount less the line's, in the invoice's currency (null: the currencies do not meet) */
  difference: { amount: string; currency: string } | null;
  /** the line went to another account than the one the invoice names */
  account_differs: boolean; in_window: boolean; strength: number; by_due: boolean; days_after_issue: number | null;
  /** the days from the invoice's due date to the line's booking day (positive: late) */
  days_from_due: number | null;
}
/** 143: every invoice of the page against one line: the engine's proposals first, the other fitting ones by strength,
 *  then the rest by the nearest amount. */
export interface ReconcileMatches { line_id: string; matches: ReconcileMatch[] }

// --- 133: the own parties (jav/parties.py, jav/party_views.py) --------------------------------------------------------
/** How an invoice was tied to its party: its buyer's tax number, a known name variant, or a name holding one variant. */
export type PartyHow = "tax" | "name" | "similar" | "ambiguous" | null;
export interface PartyRef { id: string; name: string }
export type PartyIdentityKind = "tax" | "name" | "account";
/** A tax number, a buyer name variant or an account, with how many invoices (statements for an account) carry it. */
export interface PartyIdentity { kind: PartyIdentityKind; key: string; label: string; invoices: number }
export interface PartyAccount {
  key: string; label: string; statements: number; first: string | null; last: string | null; statement_types: string[]; currencies: string[];
  registered?: AccountDetails | null; // 138: the details a person registered (kind, bank, currencies, the days it was open)
}
/** 138: an own account or card as a person registered it; it is known even before any statement of it. */
export type AccountKind = "account" | "card";
export interface AccountDetails {
  kind: AccountKind; bank: string | null; currencies: string[]; valid_from: string | null; valid_to: string | null;
  actor?: string; updated_at?: string;
}
export interface AccountDetailsInput {
  kind: AccountKind; currencies: string[]; bank: string | null; valid_from: string | null; valid_to: string | null;
}
/** 138: a month of an account: missing / partial / unverified (balances do not check out) / unapproved / ok, or none
 *  (not expected); overlap: two statements book the same days; break: the opening balance does not continue the last. */
export type MonthState = "ok" | "unapproved" | "unverified" | "partial" | "missing" | "none";
export interface MonthCell {
  month: string; state: MonthState; statements: number; flags: ("overlap" | "break")[];
  replaced?: string[]; // 139: the statements of the month another one replaced (left out of the reconciliation)
}
export interface MonthColumn {
  key: string; currency: string; label: string; kind: AccountKind; bank: string | null; registered: boolean;
  opened: string | null; closed: string | null; statements: number; months: MonthCell[];
}
export interface MonthInvoices { month: string; total: number; approved: number; not_approved: number; no_run: number }
export interface PartyMonths {
  party: PartyRef; start: string; end: string; months: string[]; today: string; columns: MonthColumn[]; invoices: MonthInvoices[];
  summary: Record<Exclude<MonthState, "none"> | "overlap" | "break", number>;
}
export interface OwnParty {
  id: string; name: string; invoices: number; first: string | null; last: string | null; statements_first: string | null;
  statements_last: string | null; accounts: PartyAccount[]; identities: PartyIdentity[]; updated_at: string;
}
/** A new party (`party_id` null) or what an existing one gains, as the data proposes it now. */
export interface PartySuggestion { id: string; party_id: string | null; name: string; invoices: number; identities: PartyIdentity[] }
export interface PartiesOverview {
  parties: OwnParty[]; suggestions: PartySuggestion[]; unassigned: PartyIdentity[]; dismissed: PartyIdentity[]; invoices: number;
  unclaimed_invoices: number; ambiguous_invoices: number; buyer_is_supplier: number; no_buyer: number; config_hash: string;
}
const identityBody = (i: PartyIdentity) => ({ kind: i.kind, key: i.key, label: i.label });

// --- 056 U1: datasets (unified list query and download) -------------------------------------------------------
export type ColKind = "text" | "number" | "money" | "date" | "datetime" | "enum" | "bool" | "id";
export type LinkKind = "run" | "workpackage" | "next" | "reviews" | "review" | "item" | "process";
export interface DsColumn {
  key: string; label: string; kind: ColKind; hidden: boolean; labels: Record<string, string> | null; link?: LinkKind; field?: string;
  badge?: boolean; alert?: boolean; // 057: status badge; a value above 0 is highlighted
  percent?: boolean; // 062: a probability between 0 and 1, shown as a percentage
  names?: "original" | "unified"; // 082: the name column of an item list shows this name
  wrap?: "anywhere"; // 156: a name-like value (a file name, a path, an e-mail address) may break inside a word
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
  /** 153: the package list's last rows, served while newer ones are being built */
  refreshing?: boolean;
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
    const d = (data ?? {}) as { error?: string; message?: string; detail?: unknown; blockers?: Blocker[]; field?: string; kind?: string };
    const missingActor = Array.isArray(d.detail) && d.detail.some((x) => Array.isArray(x?.loc) && x.loc.includes("x-actor"));
    const message = missingActor ? t(NO_ACTOR) : d.error === "unknown_user" ? t(UNKNOWN_ACTOR)
      : d.message ?? (typeof d.detail === "string" ? d.detail : `HTTP ${res.status}`);
    throw new ApiError(res.status, d.error ?? (res.status === 422 ? "invalid" : "error"), message, d.blockers ?? [],
      { field: d.field ?? null, kind: d.kind ?? null });
  }
  return data as T;
}

const enc = encodeURIComponent;

export const api = {
  // 080: `recipes` holds only the active processing; `titles` every recipe's title (old runs, packages not yet migrated)
  recipes: () => request<{ recipes: Recipe[]; help?: RecipeHelp; titles?: Record<string, string> }>("GET", "/recipes"),
  /** 146: which bank files the system reads, and how. */
  bankFiles: () => request<BankFilesCatalogue>("GET", "/bank-files"),
  /** 146: the new work wizard's templates and the workflows (the work packages of one job, chained). */
  workflowTemplates: () => request<WorkflowTemplates>("GET", "/workflow-templates"),
  workflowEstimate: (body: { kind: WorkKind; source: WorkflowSource; party_id?: string; period_start?: string; period_end?: string;
    engine?: Engine | null }) =>
    request<WorkflowEstimate>("POST", "/workflows/estimate", body),
  workflows: (includeArchived = false) =>
    request<{ workflows: WorkflowRow[] }>("GET", `/workflows${includeArchived ? "?include_archived=true" : ""}`),
  workflowView: (id: string) => request<WorkflowView>("GET", `/workflows/${enc(id)}`),
  workflowRepeat: (id: string) => request<WorkflowDraft>("GET", `/workflows/${enc(id)}/repeat`),
  createWorkflow: (body: CreateWorkflowBody) => request<WorkflowView>("POST", "/workflows", body),
  updateWorkflow: (id: string, body: { auto?: boolean; name?: string; archived?: boolean }) =>
    request<WorkflowView>("PATCH", `/workflows/${enc(id)}`, body),
  startWorkflowStep: (id: string, step: string, budget?: WorkflowBudget) =>
    request<WorkflowView>("POST", `/workflows/${enc(id)}/steps/${enc(step)}/start`, budget ? { budget } : {}),
  linkWorkflowStep: (id: string, step: string, workpackageId: string) =>
    request<WorkflowView>("POST", `/workflows/${enc(id)}/steps/${enc(step)}/link`, { workpackage_id: workpackageId }),
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
  decideTask: (runId: string, itemId: string, index: number, decision: "accepted" | "rejected") =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/tasks/${index}/decision`, { decision }),
  /** 126: a person's decision on a suspected duplicate pair (copy, modified version, not the same invoice). */
  decideDuplicate: (runId: string, itemId: string, otherDocId: string, decision: DuplicateDecision) =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/duplicates/${enc(otherDocId)}/decision`, { decision }),
  /** 139: which of two statements of the same days stays valid (this one, the other one, or the rule of ranks). */
  chooseStatement: (runId: string, itemId: string, otherDocId: string, keep: StatementKeep) =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/statements/${enc(otherDocId)}/choice`, { keep }),
  // 131–132: the reconciliation package; every decision returns the recomputed workspace
  reconcileAccounts: () => request<{ accounts: ReconcileAccount[] }>("GET", "/reconcile/accounts"),
  /** 136: the accounts of a bank's tabular statement export (no lines or balances); a package of the chosen ones. */
  // 140: the statement package: a survey of the files for a party and a period, then the package of the ticked ones
  statementPackageSurvey: (body: StatementPackageSources) => request<StatementPackageSurvey>("POST", "/statement-packages/survey", body),
  createStatementPackage: (body: StatementPackageSources & { name: string; statements: string[]; pdfs: string[] }) =>
    request<WorkpackageView>("POST", "/statement-packages", body),
  createReconcilePackage: (body: { name: string; accounts: string[]; period_start: string; period_end: string; party_id?: string | null }) =>
    request<WorkpackageView>("POST", "/reconcile/packages", body),
  reconcileWorkspace: (wpId: string) => request<ReconcileWorkspace>("GET", `/workpackages/${enc(wpId)}/reconcile`),
  setReconcileScope: (wpId: string, body: { accounts: string[]; period_start: string; period_end: string; expected_revision: number; party_id?: string | null }) =>
    request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/scope`, body),
  reconcileRefresh: (wpId: string) => request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/refresh`, {}),
  reconcileAllocate: (wpId: string, pairs: ReconcileAllocationPair[], note?: string) =>
    request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/allocate`, { pairs, ...(note ? { note } : {}) }),
  reconcileAcceptProposed: (wpId: string) => request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/accept-proposed`, {}),
  reconcileQuickReview: (wpId: string) => request<QuickReview>("GET", `/workpackages/${enc(wpId)}/reconcile/quick-review`),
  reconcileQuickAccept: (wpId: string, group: QuickReviewGroupId, lineIds: string[]) =>
    request<{ accepted: number; review: QuickReview; workspace: ReconcileWorkspace }>("POST",
      `/workpackages/${enc(wpId)}/reconcile/quick-review/accept`, { group, line_ids: lineIds }),
  reconcileReject: (wpId: string, invoiceDocId: string, lineId: string, note: string) =>
    request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/reject`, { invoice_doc_id: invoiceDocId, line_id: lineId, note }),
  reconcileMark: (wpId: string, lineIds: string[], category: string, note?: string) =>
    request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/mark`, { line_ids: lineIds, category, ...(note ? { note } : {}) }),
  reconcileUnmark: (wpId: string, lineIds: string[]) =>
    request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/unmark`, { line_ids: lineIds }),
  reconcileRevoke: (wpId: string, kind: "allocation" | "mark" | "decision", ref: string, note?: string) =>
    request<ReconcileWorkspace>("POST", `/workpackages/${enc(wpId)}/reconcile/revoke`, { kind, ref, ...(note ? { note } : {}) }),
  reconcileLocate: (wpId: string, lineId: string) =>
    request<ReconcileLocation>("GET", `/workpackages/${enc(wpId)}/reconcile/locate?line_id=${enc(lineId)}`),
  reconcileMatches: (wpId: string, lineId: string) =>
    request<ReconcileMatches>("GET", `/workpackages/${enc(wpId)}/reconcile/matches?line_id=${enc(lineId)}`),
  // 145: the result - the statement, its approval as a version that locks its lines, reopening, accepted sources
  reconcileStatement: (wpId: string) => request<ReconcileStatementCurrent>("GET", `/workpackages/${enc(wpId)}/reconcile/statement`),
  reconcileStatementVersion: (wpId: string, version: number) =>
    request<ReconcileStatementVersion>("GET", `/workpackages/${enc(wpId)}/reconcile/statement?version=${version}`),
  reconcileAcceptSources: (wpId: string, docIds: string[]) =>
    request<ReconcileStatementCurrent>("POST", `/workpackages/${enc(wpId)}/reconcile/accept-sources`, { doc_ids: docIds }),
  reconcileApprove: (wpId: string, fingerprint: string) =>
    request<ReconcileStatementCurrent>("POST", `/workpackages/${enc(wpId)}/reconcile/approve`, { fingerprint }),
  reconcileReopen: (wpId: string, note: string) =>
    request<ReconcileStatementCurrent>("POST", `/workpackages/${enc(wpId)}/reconcile/reopen`, { note }),
  reconcileStatementXlsxUrl: (wpId: string, version?: number) =>
    `/api/workpackages/${enc(wpId)}/reconcile/statement.xlsx${version ? `?version=${version}` : ""}`,
  // 133: the own parties; every change answers with the whole overview
  parties: () => request<PartiesOverview>("GET", "/parties"),
  acceptPartySuggestions: (ids: string[], names: Record<string, string> = {}) =>
    request<PartiesOverview>("POST", "/parties/accept", { ids, names }),
  createParty: (name: string, identities: PartyIdentity[]) =>
    request<PartiesOverview>("POST", "/parties", { name, identities: identities.map(identityBody) }),
  setPartyIdentity: (identity: PartyIdentity, action: "assign" | "dismiss" | "release", partyId?: string) =>
    request<PartiesOverview>("POST", "/parties/identities", { ...identityBody(identity), action, ...(partyId ? { party_id: partyId } : {}) }),
  renameParty: (id: string, name: string) => request<PartiesOverview>("POST", `/parties/${enc(id)}/rename`, { name }),
  mergeParty: (id: string, into: string) => request<PartiesOverview>("POST", `/parties/${enc(id)}/merge`, { into }),
  deleteParty: (id: string) => request<PartiesOverview>("POST", `/parties/${enc(id)}/delete`, {}),
  // 138: accounts and cards registered with their details, and a party's data month by month
  registerPartyAccount: (id: string, number: string, details: AccountDetailsInput) =>
    request<PartiesOverview>("POST", `/parties/${enc(id)}/accounts`, { number, ...details }),
  setPartyAccount: (key: string, details: AccountDetailsInput) =>
    request<PartiesOverview>("POST", "/parties/accounts/details", { key, ...details }),
  partyMonths: (id: string, start?: string, end?: string) =>
    request<PartyMonths>("GET", `/parties/${enc(id)}/months${start && end ? `?start=${enc(start)}&end=${enc(end)}` : ""}`),
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
  supersede: (runId: string) =>
    request<{ run_id: string; superseded_by: string; reasons_closed: number; status: string }>("POST", `/runs/${enc(runId)}/supersede`, {}),
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
  /** 160-D: the application's AI engine. */
  engine: () => request<EngineSetting>("GET", "/settings/engine"),
  saveEngine: (engine: Engine) => request<EngineSetting>("PUT", "/settings/engine", { engine }),
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
  /** 144: a page of the bank's PDF behind the statement of a line read by code */
  originalPageUrl: (wpId: string, lineId: string, page: number, dpi = 144) =>
    `/api/workpackages/${enc(wpId)}/reconcile/original/pages/${page}.png?line_id=${enc(lineId)}&dpi=${dpi}`,
  words: (runId: string, itemId: string) =>
    request<{ layer_id: string; pages: SourcePage[]; words: SourceWord[] }>("GET", `/runs/${enc(runId)}/items/${enc(itemId)}/words`),
  settings: () => request<{ confidence_bands: { confident: number; check: number; gpt?: { confident: number; check: number } } }>("GET", "/settings"),
  normalize: (doc_type: string, field: string, text: string) =>
    request<{ ok: boolean; value: string | null; reasons: string[]; kind: string }>("POST", "/normalize", { doc_type, field, text }),
};
