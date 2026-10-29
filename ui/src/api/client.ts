// The connection to the local service (jav/service/api.py): one address (/api), so no cross-origin request; on error an
// `ApiError` with the service's error code and message. The person working, sent with every request.
import { t } from "../i18n";
import type { Blocker, Said } from "./types";
import type { OutputTemplateCheck } from "./outputs";

/** 231 (C3e): the check a refused upload names every problem with (`ApiError.check`), by its kind; a domain adds its
 *  own by declaration merging (the quotes domain: a price list's). */
export interface UploadChecks { output_template: OutputTemplateCheck }
export type UploadCheck = UploadChecks[keyof UploadChecks];

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public blockers: Blocker[] = [],
    /** 153: the field a correction's value could not be read in, and its kind (money, number or date); 231 (B1): the
     *  identifier of the existing thing a conflict names (`other_id`); stage D (D-c6): every problem of a version that
     *  could not be made active (`manifest_refused`) */
    public detail: { field?: string | null; kind?: string | null; other?: string | null; problems?: Said[] | null } = {},
    /** 179: a refused output template's check (`template_refused`), naming every problem; 191: or a refused price
     *  list's (`price_list_refused`) */
    public check: UploadCheck | null = null,
  ) {
    super(message);
  }
}

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
export async function downloadPost(path: string, body: unknown): Promise<{ filename: string; rows: number }> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "offline", t("The local service is not reachable. Is scripts\\dev.ps1 start running?"));
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

const ACTOR_KEY = "jav.actor";
/** For a human decision (correction, approval, closing a to-do) the service requires the author's name. The Hungarian
 *  text is the translation key: displayed as `t(NO_ACTOR)`. */
export const NO_ACTOR = "enter your name in the “Who is working?” field at the top (corrections and approvals are tied to an author)";

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
export const UNKNOWN_ACTOR = "select your name from the Users list in the “Who is working?” field";

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

export const READ_TIMEOUT_MS = 60_000;

/** The fields of a validation error (the last part of each location), without repeats. */
function refusedFields(detail: unknown[]): string {
  const names = detail.map((x) => {
    const loc = (x as { loc?: unknown[] } | null)?.loc;
    return Array.isArray(loc) && loc.length ? String(loc[loc.length - 1]) : "";
  }).filter(Boolean);
  return [...new Set(names)].join(", ") || "?";
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const actor = getActor();
  if (actor) headers["X-Actor"] = encodeURIComponent(actor); // the service decodes it (accents in the header)
  if (body !== undefined) headers["Content-Type"] = "application/json";
  // 167 (review 160 U-14): a read that never answers used to stop a view's refresh for good (a poll waits for the
  // request in flight); a read gives up after a minute. A change is not cut off: it may take long (a folder picker).
  const abort = method === "GET" ? new AbortController() : null;
  const timer = abort ? setTimeout(() => abort.abort(), READ_TIMEOUT_MS) : undefined;
  let res: Response;
  let text: string;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: abort?.signal });
    text = await res.text();
  } catch {
    if (abort?.signal.aborted) throw new ApiError(0, "timeout", t("The local service did not answer within a minute; the view will try again."));
    throw new ApiError(0, "offline", t("The local service is not reachable. Is scripts\\dev.ps1 start running?"));
  } finally {
    clearTimeout(timer);
  }
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const d = (data ?? {}) as { error?: string; message?: string; detail?: unknown; blockers?: Blocker[]; field?: string; kind?: string;
      template?: string; params?: Record<string, string>; check?: UploadCheck; other_id?: string; problems?: Said[] };
    const missingActor = Array.isArray(d.detail) && d.detail.some((x) => Array.isArray(x?.loc) && x.loc.includes("x-actor"));
    // 167 (review 160 U-1): a message the service wrote as a template is translated like the interface's own labels
    const message = missingActor ? t(NO_ACTOR) : d.error === "unknown_user" ? t(UNKNOWN_ACTOR)
      : typeof d.template === "string" ? t(d.template, d.params ?? {})
      // 153 (review E) / 167: a refused request body (the service's validation) names the fields, not a bare "HTTP 422"
      : Array.isArray(d.detail) ? t("The service refused a value: {{fields}}", { fields: refusedFields(d.detail) })
      : d.message ?? (typeof d.detail === "string" ? d.detail : `HTTP ${res.status}`);
    throw new ApiError(res.status, d.error ?? (res.status === 422 ? "invalid" : "error"), message, d.blockers ?? [],
      { field: d.field ?? null, kind: d.kind ?? null, other: d.other_id ?? null, problems: d.problems ?? null }, d.check ?? null);
  }
  return data as T;
}

export const enc = encodeURIComponent;

