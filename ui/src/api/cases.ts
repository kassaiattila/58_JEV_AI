// 231 (plan stage A, A6; DECISIONS 231): a process pack's case: what the owner calls a workflow is described by a
// process pack, and one running instance of it is a case. The service gives a case's page as data
// (jav/app/case_views.py): its steps and its pack's tabs, each element with what its step's capability shows.
import { enc, request } from "./client";
import type { Catalogue } from "./products";
import type { ApprovalState, Said } from "./types";

/** 231 (C1a): one part a record was read from (the email's text, an attachment, a document). */
export interface RecordPart { kind: string; name: string | null }
/** 231 (C1a): a record put together from an email or a document: each field with the part it came from (`sources`),
 *  its list's rows and the part the list came from. */
export interface RecordPreview {
  title: string; parts: RecordPart[]; fields: Record<string, unknown>; sources: Record<string, number>;
  items: object[]; items_from: number | null;
}
/** 231 (C1a): a process whose case an email may start (`jav/app/intake.py`). */
export interface IntakeOffer {
  pack: string; title: string; starts: "offer" | "case" | "manual"; record: { workpackage_id: string; item_id: string };
  preview: RecordPreview | null; list_field: string | null; record_type: string | null; gaps: { code: string; message: string }[]; label: string | null;
  cases: { id: string; name: string }[];
}

/** 231 (C1c): a case started from an item of the packages another case reads. */
export interface StartedCase {
  id: string; name: string; record: { workpackage_id: string; item_id: string }; pack: string | null; process: string | null;
  status: string | null;
}

/** A person's action on a step (A7d): a failed step's retry, or one its capability offers while the step waits for it. */
/** D-f2: `form`: the action takes values, which its step's own element asks for (no button of its own). */
export interface CaseAction { name: string; label: string; form?: boolean }
/** 231 (C3b3): the documents of a document processing case: a folder (with its subfolders when asked) or files. */
export interface CaseSource {
  kind: "folder" | "files" | "mailbox"; folder?: string; recursive?: boolean; files?: string[];
  /** 231 (C3d): a mailbox download's request */
  request?: import("./email").MailboxRequest;
}
/** 231 (C3b3): the package a document processing step made, its runs, and its live run's start with the estimate. */
export interface PackageWorkView {
  package: { id: string; name: string; items: number; kind: string } | null;
  runs?: { run_id: string; mode: string; status: string; approval: string | null }[];
  can_start?: boolean; estimate?: Record<string, string>; blockers?: string[];
  /** 231 (C3d): the processes whose case may read the package (`jav/app/intake.py` `package_offers`) */
  offers?: import("./processes").PackageOffer[];
}
/** One step of a case: its capability, how it starts, its state in the process core, whether it waits for a person's
 *  start (a paid step or a send), the actions a person may take on it now and (C2d) whether its capability waits for a
 *  person's decisions. */
export interface CaseStep {
  title: string | null; uses: string; start: "auto" | "person"; state: string | null; phase: string | null;
  waiting_for: string | null; awaiting_start: boolean; note: string | null; result: unknown; actions?: CaseAction[];
  by_person?: boolean;
  /** U-A8: why a stopped step stopped, in a person's words (none: its note says it) */
  reasons?: Said[];
  /** U1: what a running step's wait means, as its capability says: a person's start, the machine's work, a person */
  waits_on?: "person_start" | "work" | "person";
}
/** One element of a tab: its registered type, the step it shows and its data. */
export interface CaseElement { type: string; step: string | null; data: unknown; [setting: string]: unknown }
export interface CaseTab { id: string; label: string; elements: CaseElement[] }
export interface CaseView {
  /** U-A8: `due`, whether the worker has something to do for the case now (the page asks again while it has) */
  case: { id: string; pack: string; version: string; title: string; name: string | null; status: string; due?: boolean;
    /** 231 (U2c): the case and step a sub-case is part of (the process's title, the step's title) */
    parent?: { id: string; name: string; title: string | null; step: string; step_title: string } };
  steps: Record<string, CaseStep>;
  tabs: CaseTab[];
  /** the case's next step, named by its elements, and the tab it is done on */
  next: { code: string; label: string; stage: string; tab: string; params?: Record<string, number> } | null;
  /** 231 (U1): what may follow a closed case: another process started from its documents (the case once started) */
  follow_ups?: { pack: string; title: string; case_id: string | null }[];
}

// 231 (A7e): the data of the shared elements: a send step's handovers, a reply step's wait, the case's events and cost
export interface HandoverAttempt {
  attempt: number; status: "recorded" | "sent" | "acknowledged" | "uncertain" | "failed"; error: string | null;
  created_at: string | null; updated_at: string | null; receipt: { path?: string } | null; mode: string | null;
  file_name: string | null; to: string | null; subject: string | null; size: number | null;
}
export interface HandoverData {
  mode: "output_folder" | "outlook_draft" | "outlook_send"; message: string | null; state: string | null;
  output_folder: string | null; attempts: HandoverAttempt[];
}
export interface ReplyData {
  state: string | null; since: string | null; remind_at: string | null; reminded_at: string | null;
  follow_up: string | null; reply: "replied" | "not_needed" | null; by: string | null; at: string | null; note: string | null;
}
/** D-f4: an assessed unit of a field check, with where each fact came from (jav/app/field_check.py `view`). */
export interface AssessedUnit {
  unit_id: string; level: string; parent_id: string | null; facts: Record<string, unknown>; state: number; removed?: boolean;
  sources: Record<string, { value?: unknown; original?: string | null;
    source?: { item?: string; file?: string | null; page?: number | null; quote?: string | null } | null;
    interpretation?: { reading?: string } | null }>;
}
/** D-f4: a fact another step offered and where it went: a new unit, filled, agrees, a conflict (open: still differs), not placed. */
export interface OfferedClaim {
  claim_key: string; from_step: string; unit_key: string; fact: string; value: unknown;
  placement: "new_unit" | "filled" | "agrees" | "conflict" | "unplaced"; unit_id: string | null; open: boolean;
  /** U1: a disagreement settled by a person keeping the value shown */
  kept?: { by: string; at: string } | null;
}
export interface FieldReviewData {
  units: AssessedUnit[]; claims: OfferedClaim[]; state: number; approval: ApprovalState; catalogue: Catalogue;
  frozen: { version: number; cover_start: string; by: string; at: string } | null; conflicts: number; waits: boolean;
  /** U1: the day cover starts the freeze offers to begin with (a document's, else the last freeze's) */
  cover_start_hint?: string | null;
}
/** D-f4: the facts a step read from a case's documents, per document. */
export interface DocumentFactsData {
  state: string | null; catalogue: Catalogue | null;
  documents: { item: string; file: string; doc_type: string; claims: number; unread: { unit: string | null; fact: string; value: unknown; why: string }[]; note?: string }[];
}
/** D-f4: an outside register's question and answer. */
export interface LookupData {
  state: string | null; note: string | null; connector: string; what: string | null; asked: boolean | null; missing: string[];
  question: Record<string, unknown>; claims: { unit: string; fact: string; value: unknown }[]; catalogue: Catalogue | null;
}
/** D-f5: a rule evaluation's latest record in full, and its versions (jav/app/evaluation_steps.py). */
export interface EvaluatedUnit {
  unit_id: string; level: string; named: Record<string, unknown>; combined: Record<string, unknown>;
  rules: Record<string, { matched: number[]; outcomes: Record<string, unknown>; missing: string[] }>;
}
export interface EvaluationData {
  versions: { version: number; input_version: number; made_at: string; verdict: string | null; missing: number; blockers: number }[];
  latest: { version: number; input_version: number; verdict: string | null; modules: string[]; modules_said: boolean;
    missing: { unit_id: string; fact: string; title: string }[]; blockers: string[]; product: string; units: EvaluatedUnit[] } | null;
  catalogue: Catalogue | null;
  rules: Record<string, { title: string; kind: string; source: { document?: string; page?: number | null; clause?: string } }>;
}
export interface PremiumMoney { amount: string; currency: string }
export interface PremiumStep { name: string; factor: string; after: PremiumMoney }
export interface CalculationData {
  versions: { version: number; input_version: number; made_at: string; total: PremiumMoney | null; blockers: number }[];
  latest: {
    version: number; evaluation_version: number; tariff_ref: string; modules: string[]; total: PremiumMoney | null;
    subtotal: PremiumMoney | null; policy_minimum_applied: boolean; blockers: string[];
    /** U-A8: the blockers in a person's words (a record made before has none) */
    blockers_said?: Said[];
    lines: { unit_id: string; module: string; basis: PremiumMoney; base: PremiumMoney; steps: PremiumStep[]; amount: PremiumMoney }[];
    module_totals: Record<string, { lines: PremiumMoney; minimum_applied: boolean; total: PremiumMoney }>; total_steps: PremiumStep[];
  } | null;
  tariff?: { ref: string; title: string | null; currency: string; factors: Record<string, string | null> };
  modules?: Record<string, string>; units?: Record<string, { level: string; named: Record<string, unknown> }>; catalogue?: Catalogue;
}
/** D-f5: the wait for missing facts. */
export interface MissingInfoData {
  state: string | null; missing: { unit_id: string; fact: string; title: string }[]; closes: string | null; days: number | null;
  units?: Record<string, { level: string; named: Record<string, unknown>; label?: string }>;
  task: { status: "open" | "decided" | "expired" | "withdrawn"; due_at: string | null; opened_at: string; closed_at: string | null;
    note: string | null; outcome: string | null } | null;
}
/** D-f6: a person's decision on another step's result (jav/app/case_decisions.py). */
export interface DecisionData {
  about: string; result: Record<string, unknown> | null; basis: Record<string, number>;
  choices: { code: string; title: string; closes: string | null; allowed: boolean }[];
  second_person: { limit: string; amount: PremiumMoney; above: PremiumMoney; needed: boolean; other_than: string;
    earlier_by: string | null; earlier_by_id: string | null } | null;
  problem: string | null; approval: ApprovalState; waits: boolean;
  decided: { version: number; choice: string; title: string; note: string | null; by: string; at: string } | null;
}
/** D-f7: the document a priced document's step printed (jav/app/approved_document.py). */
export interface DocumentViewData {
  state: string | null; from_step: string | null; output: string | null; version: number | null;
  file: { name: string; sha256: string } | null;
}
/** D-f9: what holds an open case, each with the tab where it is resolved (jav/app/case_views.py). */
export interface BlockersData {
  status: string;
  items: { step: string; kind: "stopped" | "stale" | "start" | "person" | "waits" | "sub_case"; note: string | null; waiting_for: string | null;
    tab: string | null; reasons?: Said[] }[];
}
/** 231 (U2c): a step that runs a case of another process, a sub-case (jav/app/sub_cases.py): its process, the sub-case
 *  (its state and, while it is open, its own next step) and the earlier ones that closed otherwise. */
export interface SubCaseData {
  state: string | null; pack: string | null; process: string | null;
  case: { id: string; name: string; status: string | null; outcome: string | null;
    next: { code: string; label: string; stage: string; tab: string; params?: Record<string, number> } | null } | null;
  earlier: { case_id: string; outcome: string }[];
}
/** D-f8: a letter that goes with a printed document (jav/app/letters.py). */
export interface LetterData {
  frame: string;
  document: { step: string; version: number; output: string; name: string; sha256: string } | null;
  draft: { to: string | null; subject: string; body: string } | null;
  problem: string | null; basis: Record<string, number>; approval: ApprovalState; waits: boolean;
  accepted: { version: number; to: string | null; subject: string; body: string; by: string; at: string;
    document: { name: string; sha256: string }; file: { name: string; sha256: string } | null } | null;
  limits: { subject_chars: number; body_chars: number };
}
export interface CaseEvent {
  at: string; kind: string; step: string | null; step_title: string | null; who: string | null;
  detail: { note?: string; timer?: string; task_kind?: string; answer?: string; kept?: CaseKept;
    /** U1: a stopped step's reasons in a person's words, shown instead of its note */
    reasons?: Said[] };
}
/** D0-e: the versions a case keeps from its start to its end (`jav/app/process_runtime.py` `kept_of`): its resources
 *  naming a versioned thing (a price list, a template) and the rule files its steps read. */
export interface CaseKept {
  resources: { key: string; label: string; name: string; version: number | null }[];
  rules: { file: string; version: string | null }[];
}
/** 231 (B1): a partner the case is about: linked, or proposed from its record with the partner it seems to be. */
export interface CasePartnerBrief { partner_id: string; name: string; tax_number: string | null; email: string | null; roles: string[]; retired: boolean; version: number }
export interface CasePartnerLink {
  role: string; role_label: string; partner: CasePartnerBrief | null;
  proposal: { name: string; tax_number?: string; email?: string; phone?: string; address?: string } | null;
  match: CasePartnerBrief | null;
}
export interface CostLine { step: string; step_title: string; provider: string; calls: number; reused: number; cost_usd: string; open_usd: string }
export interface CaseCost { lines: CostLine[]; total_usd: string }

export const casesApi = {
  // 231 C1c: the packages it reads; C2d: its own party and period
  startCase: (body: { pack: string; record?: { workpackage_id: string; item_id: string }; sources?: string[]; name: string;
    party_id?: string; period_start?: string; period_end?: string; source?: CaseSource }) =>
    request<{ case_id: string }>("POST", "/cases", body),
  casePage: (caseId: string) => request<CaseView>("GET", `/cases/${enc(caseId)}`),
  /** 231 (U1): a case of the process that follows the closed case, started from its documents */
  caseFollowUp: (caseId: string, pack: string) => request<{ case_id: string }>("POST", `/cases/${enc(caseId)}/follow-ups`, { pack }),
  // D-f7: the document a step printed and stored with its version (a link, not a request)
  caseStepFileUrl: (caseId: string, stepId: string) => `/api/cases/${enc(caseId)}/steps/${enc(stepId)}/file`,
  startCaseStep: (caseId: string, stepId: string) =>
    request<CaseView>("POST", `/cases/${enc(caseId)}/steps/${enc(stepId)}/start`, {}),
  linkCasePartner: (caseId: string, role: string, partnerId: string) =>
    request<CaseView>("POST", `/cases/${enc(caseId)}/partners`, { role, partner_id: partnerId }),
  caseStepAction: (caseId: string, stepId: string, name: string, note?: string, values?: Record<string, unknown>) =>
    request<CaseView>("POST", `/cases/${enc(caseId)}/steps/${enc(stepId)}/actions/${enc(name)}`,
      { ...(note ? { note } : {}), ...(values ? { values } : {}) }),
  /** D0-d: the approval's state of a case's approving step, and a person's return of its result with a reason */
  caseApproval: (caseId: string, stepId: string) =>
    request<ApprovalState>("GET", `/cases/${enc(caseId)}/steps/${enc(stepId)}/approval`),
  returnCaseStep: (caseId: string, stepId: string, reason: string) =>
    request<ApprovalState>("POST", `/cases/${enc(caseId)}/steps/${enc(stepId)}/approval/return`, { reason }),
};
