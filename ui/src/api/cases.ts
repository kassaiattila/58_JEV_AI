// 231 (plan stage A, A6; DECISIONS 231): a process pack's case: what the owner calls a workflow is described by a
// process pack, and one running instance of it is a case. The service gives a case's page as data
// (jav/app/case_views.py): its steps and its pack's tabs, each element with what its step's capability shows.
import { enc, request } from "./client";

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

/** A person's action on a step (A7d): a failed step's retry, or one its capability offers while the step waits for it. */
export interface CaseAction { name: string; label: string }
/** One step of a case: its capability, how it starts, its state in the process core, whether it waits for a person's
 *  start (a paid step or a send) and the actions a person may take on it now. */
export interface CaseStep {
  title: string | null; uses: string; start: "auto" | "person"; state: string | null; phase: string | null;
  waiting_for: string | null; awaiting_start: boolean; note: string | null; result: unknown; actions?: CaseAction[];
}
/** One element of a tab: its registered type, the step it shows and its data. */
export interface CaseElement { type: string; step: string | null; data: unknown; [setting: string]: unknown }
export interface CaseTab { id: string; label: string; elements: CaseElement[] }
export interface CaseView {
  case: { id: string; pack: string; version: string; title: string; name: string | null; status: string };
  steps: Record<string, CaseStep>;
  tabs: CaseTab[];
  /** the case's next step, named by its elements, and the tab it is done on */
  next: { code: string; label: string; stage: string; tab: string; params?: Record<string, number> } | null;
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
export interface CaseEvent {
  at: string; kind: string; step: string | null; step_title: string | null; who: string | null;
  detail: { note?: string; timer?: string; task_kind?: string; answer?: string };
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
  startCase: (body: { pack: string; record: { workpackage_id: string; item_id: string }; name: string }) =>
    request<{ case_id: string }>("POST", "/cases", body),
  casePage: (caseId: string) => request<CaseView>("GET", `/cases/${enc(caseId)}`),
  startCaseStep: (caseId: string, stepId: string) =>
    request<CaseView>("POST", `/cases/${enc(caseId)}/steps/${enc(stepId)}/start`, {}),
  linkCasePartner: (caseId: string, role: string, partnerId: string) =>
    request<CaseView>("POST", `/cases/${enc(caseId)}/partners`, { role, partner_id: partnerId }),
  caseStepAction: (caseId: string, stepId: string, name: string, note?: string) =>
    request<CaseView>("POST", `/cases/${enc(caseId)}/steps/${enc(stepId)}/actions/${enc(name)}`, note ? { note } : {}),
};
