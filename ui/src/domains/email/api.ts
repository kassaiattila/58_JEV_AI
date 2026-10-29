// The email domain: mailboxes and their schedules, the email routing and the task proposals. 261 (the consolidation
// round, DECISIONS 261): in the domain's folder (until then `ui/src/api/email.ts`), as the finance's and the quotes'
// since 231 C3e; the domain adds its calls to the shared client when the interface loads (`./index.tsx`), and their
// types and its parts of the shared records by declaration merging (below), so the shared code imports none.
import { enc, request } from "../../api/client";
import type { ItemResult, WorkpackageView } from "../../api/types";

/** 181: what keeps an attachment from being routed by itself (183: `no_data` new; an incoming invoice in a sent email
 * is a note instead). */
export type RoutingBlocker = "no_result" | "no_data" | "unknown_party" | "unclear_direction" | "internal" | "not_own" | "no_day"
  | "suspicious";
/** 183: what a person should know about a proposal: an incoming invoice in a sent email (a forwarded one). */
export type RoutingNote = "sent_incoming";
export interface RoutingEmail { item_id: string; subject: string | null; sender: string | null; received_at: string | null; folder: string | null }
export interface RoutingNewPackage { name: string; party: string; party_id: string; period_start: string; period_end: string; role: string }
/** 181: one attachment of a routing package: its email, its result, where it belongs, the proposal and the decision. */
export interface RoutingItem {
  item_id: string; file: string; package: string; email: RoutingEmail | null; doc_type: string | null; tier: string | null;
  placement: { routable: boolean; role: string | null; role_title: string | null; party_id: string | null; party: string | null;
    day: string | null; problem: RoutingBlocker | null; note?: RoutingNote | null };
  proposal: { target: { id: string; name: string } | null; others: { id: string; name: string }[]; new: RoutingNewPackage | null } | null;
  decision: { decision: "accepted" | "rejected"; target: string | null; target_name?: string | null; made: number; actor: string;
    decided_at: string } | null;
  /** whether the package it was accepted into still holds it */
  held?: boolean | null;
  /** 187: the decision's state, sent back with a change (`jav/core/decisions.py`). */
  decision_state?: number;
}
export interface RoutingView {
  sources: { id: string; name: string | null }[]; items: RoutingItem[];
  counts: { attachments: number; routable: number; decided: number; blocked: number; clear: number; accepted: number };
}
/** Email item (048 T2): the email and the result of intent recognition. */
export interface EmailItem {
  subject: string; sender: string | null; sender_name: string | null; to: string[]; received_at: string | null; mailbox: string | null;
  body: string; attachments: string[];
  /** 058 K5.1: how much of the email text intent recognition saw (computed in code). */
  body_coverage?: { status: "full" | "shortened" | "capped"; chars: number; own_chars: number; seen_chars: number; seen_lines: number;
    quoted_removed: boolean };
  result: { intent: string | null; intent_label: string | null; confidence: number | null; next_flow: string | null;
    next_flow_reads_text?: boolean; // 192: the next step reads the email's own text too
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
  /** 187: the decision's state, sent back with a change (`jav/core/decisions.py`). */
  decision_state?: number;
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

export const emailApi = {
  decideTask: (runId: string, itemId: string, index: number, decision: "accepted" | "rejected", expectedState?: number) =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/tasks/${index}/decision`,
      { decision, ...(expectedState !== undefined ? { expected_state: expectedState } : {}) }),
  /** 062: the accepted task marked as done by hand (or unmarked). */
  markTaskDone: (runId: string, itemId: string, index: number, done: boolean, expectedState?: number) =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/tasks/${index}/done`,
      { done, ...(expectedState !== undefined ? { expected_state: expectedState } : {}) }),
  /** 058 K5.2: the emails' PDF attachments go into the package as documents. */
  addAttachments: (id: string, expected_revision: number) =>
    request<WorkpackageView>("POST", `/workpackages/${enc(id)}/attachments`, { expected_revision }),
  /** `titles`: the roles' titles in the interface's language, for the names of the packages the routing makes */
  /** 187: `states`, each attachment's `decision_state` as the page read it (a change on a stale page is a 409). */
  routingAccept: (wpId: string, items: string[], target?: string, titles?: Record<string, string>, states?: Record<string, number>) =>
    request<RoutingView>("POST", `/workpackages/${enc(wpId)}/routing/accept`,
      { items, ...(target ? { target } : {}), ...(titles ? { titles } : {}), ...(states ? { expected_states: states } : {}) }),
  routingAcceptClear: (wpId: string, titles?: Record<string, string>) =>
    request<RoutingView>("POST", `/workpackages/${enc(wpId)}/routing/accept-clear`, titles ? { titles } : {}),
  routingReject: (wpId: string, items: string[], states?: Record<string, number>) =>
    request<RoutingView>("POST", `/workpackages/${enc(wpId)}/routing/reject`, { items, ...(states ? { expected_states: states } : {}) }),
  routingUndo: (wpId: string, item: string, state?: number) =>
    request<RoutingView>("POST", `/workpackages/${enc(wpId)}/routing/undo`, { item, ...(state !== undefined ? { expected_state: state } : {}) }),
  mailbox: () => request<{ schedules: MailboxSchedule[]; pulls: MailboxPull[]; bridge_available: boolean; accounts?: string[];
    defaults: { interval_min: number; lookback_days: number } }>("GET", "/mailbox"),
  mailboxCount: (req: MailboxRequest) => request<MailboxCount>("POST", "/mailbox/count", req),
  mailboxPull: (req: MailboxRequest) => request<MailboxPull>("POST", "/mailbox/pulls", req),
  createSchedule: (req: MailboxRequest, interval_min: number) =>
    request<MailboxSchedule>("POST", "/mailbox/schedules", { request: req, interval_min }),
  updateSchedule: (id: string, body: { enabled?: boolean; interval_min?: number }) =>
    request<MailboxSchedule>("PATCH", `/mailbox/schedules/${enc(id)}`, body),
  deleteSchedule: (id: string) => request<{ deleted: string }>("POST", `/mailbox/schedules/${enc(id)}/delete`, {}),
};

type EmailCalls = typeof emailApi;
declare module "../../api" {
  interface DomainCalls extends EmailCalls {}
}
declare module "../../api/types" {
  interface WorkpackageView {
    /** 058 K5.2: in an email package, the number of PDF attachments not yet added */
    attachments_missing?: number;
    /** 181: an email routing package's attachments, proposals and decisions */
    routing?: RoutingView;
    /** 183: a mailbox package: the request of the download that made it (null if no recorded download did) */
    mailbox_request?: MailboxRequest | null;
  }
  interface ItemResult {
    /** 048 T2: an email item's email and its intent */
    email?: EmailItem;
    /** 058 K5.2: the email's attachments that ran as documents */
    attachment_items?: { item_id: string; filename: string }[];
  }
}
declare module "../../api/workflows" {
  interface WorkflowSource {
    /** a mailbox step's download */
    request?: MailboxRequest;
  }
}
declare module "../../api/cases" {
  interface CaseSource {
    /** 231 (C3d): a mailbox download's request */
    request?: MailboxRequest;
  }
}
