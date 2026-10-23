// Settings and the system page: users, folders, the AI engine, the worker, backups and checks.
import type { DocumentFormat } from "../native";
import { enc, request } from "./client";

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
/** 075: the last dependency audit (`runs/deps-audit.json`), as `jav/runtime/deps_audit.py` `status()` returns it. */
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
/** 200: the pinned JEV version against the provider's moving name at its last look (`jav/ai/jev_version.py` `status()`). */
export interface JevVersionInfo {
  pinned: string; watch_alias: string; latest: string | null; checked_at: string | null;
  newer: boolean | null; stale: boolean; age_days: number | null;
}
/** 076: a paid call with an uncertain outcome, awaiting manual settlement (`jav/core/calls.py` `uncertain_list`). */
export interface UncertainCall {
  id: number; run_id: string; step_id: string; attempt: number; provider: string; model_requested: string | null;
  budget_scope: string | null; max_cost_usd: string; created_at: string; status: string;
}

export interface BackupInfo {
  status: BackupRun | null;
  config: { schedule?: string; keep?: number; copy_to?: string | null; with_burr?: boolean; with_docs?: boolean; max_age_hours?: number };
}
/** 160-D: the AI engine — JEV and GPT (the default) or GPT only, without JEV. */
export type Engine = "jev" | "gpt";
/** 160-D: the application's AI engine, the default of every new processing setting that does not name one. */
export interface EngineSetting { engine: Engine; actor: string | null; updated_at: string | null }
/** 057: watched work folder (modelled on the legacy V4 „Figyelt mappák” (Watched folders)). */
export interface WatchedFolder {
  id?: string | null; name: string; path: string; enabled: boolean; recursive: boolean; batch_mode: "folder" | "daily";
  recipe_id: string | null; params: Record<string, string>; interval_min: number;
  next_at?: string | null; last_at?: string | null; last_status?: "ok" | "error" | null;
  last_result?: { new?: number; settling?: number; workpackage?: string | null; error?: string } | null;
}


export const systemApi = {
  documentFormats: () => request<{ formats: DocumentFormat[]; native_limits: Record<string, unknown> }>("GET", "/document-formats"),
  worker: () => request<{ running: boolean; stop_requested: boolean; jobs: Record<string, number>; pdf_protection?: PdfProtection }>("GET", "/worker"),
  users: () => request<{ users: string[] }>("GET", "/settings/users"),
  saveUsers: (users: string[]) => request<{ users: string[] }>("PUT", "/settings/users", { users }),
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
  workerStop: () => request<Record<string, unknown>>("POST", "/worker/stop", {}),
  /** 071: the running service's version and the commit recorded at start-up. */
  health: () => request<Health>("GET", "/health"),
  backupStatus: () => request<BackupInfo>("GET", "/system/backup"),
  depsAudit: () => request<DepsAuditInfo>("GET", "/system/deps-audit"),
  jevVersion: () => request<JevVersionInfo>("GET", "/system/jev-version"), // 200
  uncertainCalls: () => request<{ calls: UncertainCall[] }>("GET", "/system/uncertain-calls"),
  resolveUncertainCall: (id: number, body: { cost_usd: string | null; note: string }) =>
    request<{ ok: boolean }>("POST", `/system/uncertain-calls/${id}/resolve`, body),
  backupNow: () => request<BackupRun & { dir: string; copy: BackupRun["copy"] }>("POST", "/system/backup", {}),
  settings: () => request<{ confidence_bands: { confident: number; check: number; gpt?: { confident: number; check: number } } }>("GET", "/settings"),
  normalize: (doc_type: string, field: string, text: string) =>
    request<{ ok: boolean; value: string | null; reasons: string[]; kind: string }>("POST", "/normalize", { doc_type, field, text }),
};
