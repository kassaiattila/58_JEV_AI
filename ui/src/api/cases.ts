// 231 (plan stage A, A6; DECISIONS 231): a process pack's case: what the owner calls a workflow is described by a
// process pack, and one running instance of it is a case. The service gives a case's page as data
// (jav/app/case_views.py): its steps and its pack's tabs, each element with what its step's capability shows.
import { enc, request } from "./client";

/** One step of a case: its capability, how it starts, its state in the process core and whether it waits for a
 *  person's start (a paid step). */
export interface CaseStep {
  title: string | null; uses: string; start: "auto" | "person"; state: string | null; phase: string | null;
  waiting_for: string | null; awaiting_start: boolean; note: string | null; result: unknown;
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

export const casesApi = {
  startCase: (body: { pack: string; record: { workpackage_id: string; item_id: string }; name: string }) =>
    request<{ case_id: string }>("POST", "/cases", body),
  casePage: (caseId: string) => request<CaseView>("GET", `/cases/${enc(caseId)}`),
  startCaseStep: (caseId: string, stepId: string) =>
    request<CaseView>("POST", `/cases/${enc(caseId)}/steps/${enc(stepId)}/start`, {}),
};
