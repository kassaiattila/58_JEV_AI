// The shared records: work packages, their items and runs, the review, results and releases.
import type { WorkflowRef } from "./workflows";
import type { Engine } from "./system";
import type { DuplicatePair, ReconcileApproval, ReconcileCounts, ReconcileCoverage, ReconcileScope, StatementPackageView, StatementRelation } from "./finance";
import type { QuoteEmailPart, QuoteView } from "./quotes";
import type { EmailItem, MailboxRequest, RoutingView } from "./email";

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
  scope?: "pending" | null; // 160-C S3: a run over only the package's pending items
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
  /** 160-C S3: the open live runs (finished, not approved, not repeated by a later one), oldest first */
  open_runs?: RunRow[];
  /** 168: how many items are in each state (approved, live, trial, running, failed, pending) and how many were removed */
  item_counts?: Partial<Record<"approved" | "live" | "trial" | "running" | "failed" | "pending" | "removed", number>>;
  /** 181: the package's scope (its party, period and role), when it has one */
  scope?: PackageScope;
  /** 181: a released package's release state and latest version (the stage bar's result) */
  release?: { state: PackageReleaseState; version: number };
  /** 181: an email routing package's attachments, proposals and decisions */
  routing?: RoutingView;
  /** 181: an email package offers the routing of its attachments (and names the routing packages that route it) */
  routing_offer?: { attachments: number; routings: { id: string; name: string }[] };
  /** 183: a mailbox package: the request of the download that made it (null if no recorded download did) */
  mailbox_request?: MailboxRequest | null;
  /** 191: a quote package's request, where it came from, the active price lists and its gaps */
  quote?: QuoteView;
}
/** 181: what a work package belongs to and collects, and where that comes from: `own` (a person gave it), `logic_pack`
 *  (a statement package's own) or `workflow` (its workflow step's). */
export interface PackageScope {
  party_id: string | null; party: string | null; period_start: string | null; period_end: string | null; role: string | null;
  role_title: string | null; from: string; set_by?: string; set_at?: string;
}
/** 181: a package role: what a package collects (incoming invoices, outgoing invoices, bank statements). */
export interface PackageRole { name: string; title: string; package_kinds: string[] }
/** 171/172 (plan 170 L1): the package's current result (each item from the run whose result counts now) and its
 *  release. `mark` is what Approve and release names; `blockers` say why it cannot be given now. */
export type PackageReleaseState = "not_released" | "released" | "partly_released" | "changed_since_release";
export interface PackageResultItem {
  item_id: string; kind: string | null; file: string; tier: "trial" | "live" | "approved" | null; run_id: string | null;
  final_status: string | null; released: boolean;
}
export interface PackageBlocker { code: "run_not_ready" | "own_approval" | "nothing_to_release"; run_id?: string; status?: string; open_reasons?: number }
/** 178: `template` and `template_version` name the template that made a workbook (null: before 178, the built-in). */
export interface PackageVersionFile { name: string; media: string; rows: number; sha256: string; template?: string | null; template_version?: string | null }
export interface PackageVersion {
  version: number; mark: string; items: [string, string][]; runs: string[]; released_by: string; released_at: string;
  /** DECISIONS 171: recorded afterwards for a package approved before v1.20.0 */
  backfilled_at: string | null; files: PackageVersionFile[];
}
export interface PackageResult {
  workpackage_id: string; items: PackageResultItem[]; mark: string; open_live_runs: string[]; removed_items: number;
  blockers: PackageBlocker[]; state: PackageReleaseState; versions: PackageVersion[];
  /** 172: the result views with data (as a run's `tables`) */
  tables: string[];
}
/** 080: what a run of the package will do (the pre-start overview): documents by their path known in advance (S / G /
 *  type not known yet), emails, emails with a task proposal, whether Azure may be used and earlier JEV answers reused. */
export interface RunPlan {
  documents: number; emails: number; attachments: number; paths: { S: number; G: number; unknown: number };
  tasks_emails: number; text_emails?: number; azure: boolean; jev_reuse: boolean;  // 190: text_emails
  text_tables?: number;  // 192: the emails' table attachments read as a part of a quote request (only while any)
  arm?: string; // 082: the chosen path (with S, a document on the G path has a type without a JEV path)
  jev?: boolean; // 086: false = processing without JEV (GPT recognises the type, every document on the G path)
  statement_tables?: number; // 136: statements from a bank's table export, read by code (free)
}
export interface Readiness {
  workpackage_id: string; ready: boolean; blockers: Blocker[]; warnings: Blocker[]; counts: { items: number };
  budget: Record<string, string>; assignment_revision: number; input_hash: string;
  plan?: RunPlan; // 080
  assignment_default?: boolean; // 080: no saved settings yet; the default ones apply and are saved at start
  /** 160-C S3: per mode, the run over only the pending items (when a run of that mode finished some items) */
  supplement?: Partial<Record<"shadow" | "apply", Supplement>>;
}
/** 160-C S3: the run over only the package's pending items: their count, own blockers, budget, plan and input. */
export interface Supplement {
  items: number; ready: boolean; blockers: Blocker[]; warnings: Blocker[]; budget: Record<string, string>; plan: RunPlan;
  input_hash: string;
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
  supersede?: SupersedeInfo | null; // 151: a later live run repeated this one; it can be superseded (200: a trial run too)
  superseded?: { by: string; actor: string; at: string; reasons_closed: number } | null; // 151: who superseded it
  engine?: Engine | null; // 160-D: the AI engine the run ran with (absent from an older service)
  removed_items?: string[]; // 160-C (decision 163 D7): items removed from the package, left out of the release
  rule_changes?: RuleChanges; // 218: only when some items were processed with other rules or code than the run started with
}
/** 218: what changed during a run (a release meanwhile): how many items, the rule files with their versions, and whether
 *  the program changed too; shown at the run's approval, nothing stops (the owner's decision of 2026-10-23). */
export interface RuleChanges {
  items: number; snapshots: number; code_changed: boolean;
  files: { path: string; before: string | null; after: string | null }[];
}
/** 151: the later live run that repeated this one, its own open to-dos that would close, and the human work done on it. */
export interface SupersedeInfo { by: string; open_reasons: number; resolved_reasons: number; corrected_items: number }
/** 152: an older live run of a package that a person can supersede, with the offer of its own page. 200: an older trial
 *  run with open to-dos too; `mode` says which (absent from an older service: a live run). */
export interface SupersedableRun extends SupersedeInfo { run_id: string; created_at: string; mode?: "apply" | "shadow" }
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
export interface ItemName { unified: string | null; state: "ready" | "review" | "pending" | "none"; check: string | null; run_id: string | null; reasons?: string[] }
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
export interface ItemResult {
  run_id: string; item_id: string; kind?: "document" | "email" | "statement_table"; email?: EmailItem; page_count?: number | null; extraction: Extraction | null; correction: Correction;
  attachment_items?: { item_id: string; filename: string }[]; // 058 K5.2: the email's attachments that ran as documents
  /** 192: what other domains add to this kind's item (`jav/app/item_kinds.py` item parts), by name */
  parts?: { quote_request?: QuoteEmailPart };
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
/** 192: a logic pack's own approved version (`jav/app/package_release.py` `own_approval`; the reconciliation and the quote) */
export interface OwnVersion {
  version: number; fingerprint: string; approved_by: string; approved_at: string;
  reopened_by: string | null; reopened_at: string | null; reopen_note: string | null;
}
export interface OwnApproval { active: OwnVersion | null; versions: OwnVersion[] }
/** 140: a statement of a statement package's survey or of the store, as a reference (jav/domains/finance/statement_package.py). */
export interface StatementRef {
  id: string; file: string | null; period_start: string | null; period_end: string | null; rank: string; in_store: boolean;
}
/** 160-C S2: what adding documents to a package did; `processed_elsewhere`: names a live run of another package processed. */
export interface AddSummary {
  added: number; already: number; restored: number; processed_elsewhere: string[];
  left_out?: number; // 168: what the person unticked in the preview
}
/** 168: where the documents to add come from: given files, or a folder (with `recursive`, its subfolders too). */
export type ItemSources = { paths: string[] } | { folder: string; recursive: boolean };
/** 168: one file of the preview before adding, by content: new, already in the package, removed (restored only when
 *  ticked) or repeated in the selection; `elsewhere` = processed in a live run of another package. */
export interface PreviewFile {
  path: string; name: string; folder: string; item_id: string; state: "new" | "already" | "removed" | "repeated"; elsewhere: boolean;
}
export interface ItemPreview {
  files: PreviewFile[]; counts: Record<"new" | "already" | "removed" | "repeated" | "elsewhere", number>; folder: string | null;
  others: { count: number; names: string[] };
}
export type FilterOp = "contains" | "eq" | "neq" | "in" | "gte" | "lte" | "empty" | "notempty";
