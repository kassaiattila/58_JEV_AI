// Recipes and workflows (jav/service/api_workflows.py).
import { enc, request } from "./client";
import type { Assignment, NextStep } from "./types";
import type { Engine } from "./system";
import type { MailboxRequest } from "./email";

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
/** 146: the new work wizard's templates (`configs/workflows.json`); texts are English source strings. 181: a step kind
 * is any kind the service registered (`jav/app/workflow_steps.py`), so the interface names none. */
export type WorkKind = string;
export type WorkSourceKind = "folder" | "files" | "mailbox" | "package" | "none";
export interface WorkflowTemplateStep { id: string; kind: WorkKind; title?: string; after?: string[] }
export interface WorkflowTemplate { id: string; group: string; title: string; description: string; steps: WorkflowTemplateStep[] }
/** A step kind as the wizard reads it: its texts from the templates, the rest from its registration (181). */
export interface WorkflowKind {
  title: string; description: string; sources: WorkSourceKind[]; cost: string;
  /** the work package kinds an existing package of the step may have */
  package_kinds: string[];
  /** its run may call AI: a person approves its budget */
  paid: boolean;
  /** a step with its own folder, files or mailbox may have its own AI engine */
  own_engine: boolean;
  /** its folder or files may leave out the documents a live run has processed */
  only_new: boolean;
  /** its folder may include the subfolders */
  subfolders: boolean;
  /** the parts of the workflow's scope it needs */
  needs: string[];
}
export interface WorkflowTemplates {
  intro: string; groups: { id: string; title: string; description: string }[];
  kinds: Record<WorkKind, WorkflowKind>;
  templates: WorkflowTemplate[];
}
export interface WorkflowSource {
  kind: WorkSourceKind; folder?: string; recursive?: boolean; paths?: string[]; request?: MailboxRequest; workpackage_id?: string;
  /** 147: a documents step takes only the documents no live run has processed yet */
  only_new?: boolean;
}
export type WorkflowBudget = Partial<Record<"jev" | "openai" | "azure_di", string>>;
export interface WorkflowEstimate {
  items: number | null; usd: WorkflowBudget; note: string | null; statements?: number; pdfs?: number; per_item?: WorkflowBudget;
  left_out?: number;
}
/** What a person sees of a step: the stored automation state and the package's own next step. */
export type WorkflowStepStatus = "waiting" | "ready" | "starting" | "pulling" | "needs_budget" | "nothing_new" | "failed"
  | "running" | "review" | "approve" | "approved" | "pairing" | "attention" | "missing" | "stale";
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
  /** 218 (P3l): the earlier steps whose result changed since this step was approved; only on a step out of date */
  stale_of?: string[];
}
/** 181: a workflow has a party and a period only when its steps need them (or they were given). */
export interface WorkflowInfo {
  id: string; template: string; template_title: string; name: string; party_id: string | null; party: string | null;
  period_start: string | null; period_end: string | null; auto: boolean; status: "open" | "archived"; actor: string;
  created_at: string; updated_at: string;
}
export interface WorkflowView {
  workflow: WorkflowInfo; steps: WorkflowStep[]; done: number; total: number;
  next: { step: string; status: WorkflowStepStatus } | null;
  events: { step: string | null; action: string; actor: string; detail: Record<string, unknown>; created_at: string }[];
  /** 147: the workflow this one repeats for the next period, and the ones repeating it */
  repeat_of?: WorkflowBrief | null; repeated_as?: WorkflowBrief[];
}
export interface WorkflowBrief { id: string; name: string; period_start: string | null; period_end: string | null }
/** 147: a workflow for the next period, as the wizard shows it filled in (a step without a source is asked for). */
export interface WorkflowDraft {
  template: string; party_id: string | null; period_start: string | null; period_end: string | null; name: string | null; auto: boolean;
  previous: string; steps: Record<string, { source: WorkflowSource | null; budget: WorkflowBudget; engine?: Engine | null }>;
}
export interface WorkflowRow extends WorkflowInfo {
  done: number; total: number; next: { step: string; status: WorkflowStepStatus } | null;
  steps: { id: string; title: string; status: WorkflowStepStatus }[];
}
export interface WorkflowRef { id: string; name: string; step: string; step_title: string }
export interface CreateWorkflowBody {
  template: string; party_id?: string; period_start?: string; period_end?: string; name?: string; auto: boolean;
  names?: Record<string, string>; steps: Record<string, { source: WorkflowSource; budget?: WorkflowBudget; engine?: Engine | null }>;
  previous?: string;
}

export const workflowsApi = {
  // 080: `recipes` holds only the active processing; `titles` every recipe's title (old runs, packages not yet migrated)
  recipes: () => request<{ recipes: Recipe[]; help?: RecipeHelp; titles?: Record<string, string> }>("GET", "/recipes"),
  /** 146: which bank files the system reads, and how. */
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
  workflow: (id: string) =>
    request<{ assignment: Assignment | null; history: Assignment[] }>("GET", `/workpackages/${enc(id)}/workflow`),
};
