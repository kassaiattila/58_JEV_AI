// A helyi szolgáltatás (jav/api.py) kliense. Minden hívás ugyanazon a címen megy (/api), így nincs kereszt-eredet.
// Hiba esetén ApiError: a szolgáltatás hibakódja (not_found, revision_conflict, not_ready, invalid ...) és üzenete.
import { t } from "./i18n";

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
export interface Reason { id: number; reason: string; producer: string; run_id: string }
export interface Item { item_id: string; kind: string; source_path: string; sha256: string; added_revision: number; parent_item_id?: string }
export interface Assignment {
  workpackage_id: string; revision: number; recipe_id: string; recipe_version: number; recipe_hash: string;
  params: Record<string, string>; actor: string; note: string | null; created_at: string;
}
export interface Workpackage {
  id: string; name: string; source_kind: string; source_ref: string | null; revision: number; status: string;
  created_at: string; updated_at: string; items: Item[]; assignment: Assignment | null;
  owner?: string | null; // 061: a csomag felelőse
}
export interface WorkpackageRow {
  id: string; name: string; source_kind: string; source_ref: string | null; revision: number; created_at: string;
  items: number; recipe_id: string | null; last_run_id: string | null; open_reasons: number;
}
/** 057: a csomag következő lépése (a szolgáltatás egy helyen számolja; a lista és a fejléc gombja is ezt mutatja). */
export interface NextStep { code: string; label: string; stage: "process" | "review" | "result"; params?: Record<string, number> }
export interface RunRow {
  run_id: string; workpackage_id: string; workpackage_name: string; recipe_id: string; recipe_version: number; mode: "shadow" | "apply";
  status: string; approval: string | null; approved_by: string | null; actor: string; created_at: string; finished_at: string | null;
  items: number; items_done: number; open_reasons: number;
}
export interface WorkpackageView {
  workpackage: Workpackage; readiness: Readiness; titles?: Record<string, string>; next: NextStep; last_run: RunRow | null; runs: number;
  attachments_missing?: number; // 058 K5.2: levélcsomagban a még fel nem vett PDF-csatolmányok száma
}
export interface Readiness {
  workpackage_id: string; ready: boolean; blockers: Blocker[]; warnings: Blocker[]; counts: { items: number };
  budget: Record<string, string>; assignment_revision: number; input_hash: string;
}
export interface RecipeParam { allowed?: string[]; allowed_from?: string; default?: string }
export interface Recipe {
  id: string; version: number; title: string; description: string; steps: string[]; requirements: string[];
  result: string; manual_action: string; params: Record<string, RecipeParam>; max_item_usd: Record<string, Record<string, string>>;
  // 058 K5.2–K5.3: tételkeret tétel-fajtánként (levél / csatolmány) és a beállítástól függő többlet (feladatjavaslat)
  max_item_usd_by_kind?: Record<string, Record<string, Record<string, string>>>;
  param_item_usd?: { param: string; value: string; kind?: string; usd: Record<string, string> }[];
}
/** 064: az adattár-mentés állapota (store/backups/backup-status.json) és a napi mentés beállítása. */
export interface BackupRun {
  created_at: string; ok: boolean; error?: string; dir?: string;
  /** 070: a belső munkaanyag tömörített fájlja (`internal-docs.zip`) az `entries` darabszámmal */
  files?: { file: string; bytes: number; integrity: string; entries?: number }[];
  copy?: { dir: string; ok: boolean; verified: boolean; error?: string } | null;
}
/** 071 S-verzió: `commit` / `dirty` null, ha a szolgáltatás git nélkül indult. */
export interface Health {
  ok: boolean; api_version: string; service_config: string;
  version: string; commit: string | null; dirty: boolean | null; started_at: string;
}
export interface BackupInfo {
  status: BackupRun | null;
  config: { schedule?: string; keep?: number; copy_to?: string | null; with_burr?: boolean; with_docs?: boolean; max_age_hours?: number };
}
/** 063: a receptek magyarázata (`configs/recipe_help.json`): mikor való a recept, mit jelent a beállítás és az értéke. */
export interface RecipeHelp {
  recipes: Record<string, { when: string }>;
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
  recipe?: { title?: string }; // a futás recept-pillanatképe (a címe a felületen)
}
export interface Budget {
  scope: string; committed_usd: string; providers: Record<string, { limit_usd: string; committed_usd: string }>;
}
export interface RunView {
  run: Run; budget: Budget; open_reasons: Record<string, Reason[]>; earlier_open_reasons: Record<string, Reason[]>;
  titles?: Record<string, string>; // 048 T2: levél-tétel olvasható címe
  tables?: string[]; // 058: az eredmény adatot tartalmazó nézetei (üres nézet nem jelenik meg)
}
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
  duplicates: { item_id: string; file: string; doc_type: string; same_as: string; same_as_file: string }[];
}
export interface Call {
  id: number; run_id: string; step_id: string; provider: string; model_actual: string | null; status: string;
  cost_usd: string | null; max_cost_usd: string; input_tokens: number | null; error: string | null; created_at: string;
}
export interface Correction {
  run_id: string; item_id: string; revision: number; fields: Record<string, CorrectionValue>;
  sources: Record<string, number[]>; actor: string | null; note: string | null; created_at: string | null;
}
/** Javított érték: egyszerű mező, vagy tételes lista (sorok tétel-mezőkkel / egyszerű értékek) — 048. */
export type Cell = string | number | null;
export type CorrectionValue = Cell | (Record<string, Cell> | Cell)[];
export interface ListColumn { name: string; kind: string; options?: string[] }
/** A csomag egy ellenőrzése a javított (mentett) adaton; `rows`: a hibás sor(ok) 1-től számozva, listánként. */
export interface Check { name: string; ok: boolean; code: string; detail?: string | null; rows?: Record<string, number[]>; advisory?: boolean }
export type Box = [number, number, number, number];
export interface Region { page: number; bbox: Box; boxes: Box[]; word_ids: number[]; quote: string }
export interface Alternative extends Partial<Region> { value: string | null; raw?: string; p: number | null; machine?: boolean }
export type ProvStatus = "located" | "approximate" | "ambiguous" | "context_rejected" | "not_found" | "no_value" | "no_layer" | "error" | "list";
export interface Provenance extends Partial<Region> {
  status: ProvStatus; method: "pick" | "pick_line" | "search" | "manual" | "rows" | null; alternatives: Alternative[];
  confidence?: number | null; corrected?: boolean; present_p?: number | null; label?: boolean;
  multiple?: number | null; // 053: ennyi helyen szerepel az érték (a keret a legvalószínűbbön)
  rows?: Provenance[]; // 053: tételes lista — soronként a sor helye a képen
}
export interface SourcePage { page: number; width_pt: number; height_pt: number }
export interface SourceWord { id: number; page: number; line_no: number | null; text: string; x0: number; y0: number; x1: number; y1: number }
export interface Extraction {
  doc_type: string; arm: string; datapoints: Record<string, unknown>; field_conf: Record<string, number>;
  validation: { name: string; ok: boolean; code: string; detail?: string }[]; final_status: string;
  review_reasons: string[];
}
/** Levél-tétel (048 T2): a levél és a szándék-felismerés eredménye. */
export interface EmailItem {
  subject: string; sender: string | null; sender_name: string | null; to: string[]; received_at: string | null; mailbox: string | null;
  body: string; attachments: string[];
  /** 058 K5.1: a levél szövegéből mennyit látott a szándék-felismerés (kódban számolva). */
  body_coverage?: { status: "full" | "shortened" | "capped"; chars: number; own_chars: number; seen_chars: number; seen_lines: number;
    quoted_removed: boolean };
  result: { intent: string | null; intent_label: string | null; confidence: number | null; next_flow: string | null;
    attachments: { filename: string; doc_type?: string | null; status?: string | null }[]; from_this_run: boolean;
    signals: Record<string, number>; corrected?: boolean; machine_intent?: string | null } | null;
  /** 058 K5.3: feladatjavaslat a kapu után, az emberi döntéssel (null = a futás nem kért javaslatot). */
  tasks?: { status: "proposed" | "skipped" | "error"; reason?: string | null; error?: string | null; tasks: EmailTask[];
    rejected: RejectedTask[] } | null;
}
export interface EmailTask {
  index: number; action: string; title: string; due_date: string | null; assignee_hint: string | null;
  evidence: { pointer: string; quote: string }[];
  decision: { decision: "accepted" | "rejected"; actor: string; decided_at: string; done_by?: string | null; done_at?: string | null } | null;
  /** 062: hány azonos javaslat olvadt bele (egy levélen belül). */
  merged?: number;
}
/** A kódos bizonyíték-ellenőrzésen kiesett javaslat; 062 óta a tartalmával és az elbukott részével (a korábbi futásoknál csak az ok). */
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
// 065: `eligible` = a letöltendő (új) levelek, `in_period` = az időszak összes levele
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
  attachment_items?: { item_id: string; filename: string }[]; // 058 K5.2: a levél iratként futott csatolmányai
  effective: Record<string, unknown>; open_reasons: Reason[]; earlier_open_reasons: Reason[];
  provenance: Record<string, Provenance>;
  lists?: Record<string, { columns: ListColumn[] }>; checks?: Check[];
  source: { layer_id: string; text_source: string | null; pages: SourcePage[] } | null;
}

// --- 056 U1: adatkészletek (egységes lista-lekérdezés és letöltés) ---------------------------------------------
export type ColKind = "text" | "number" | "money" | "date" | "datetime" | "enum" | "bool" | "id";
export type LinkKind = "run" | "workpackage" | "next" | "reviews" | "review" | "item";
export interface DsColumn {
  key: string; label: string; kind: ColKind; hidden: boolean; labels: Record<string, string> | null; link?: LinkKind; field?: string;
  badge?: boolean; alert?: boolean; // 057: állapotjelvény; 0-nál több érték kiemelve
  percent?: boolean; // 062: 0–1 közötti valószínűség, százalékban kiírva
}
export type FilterOp = "contains" | "eq" | "neq" | "in" | "gte" | "lte" | "empty" | "notempty";
export interface DsFilter { col: string; op: FilterOp; value?: string | string[] | null }
export interface DsSort { col: string; desc?: boolean }
export interface DsQuery { q?: string; filters?: DsFilter[]; sort?: DsSort[]; offset?: number; limit?: number; keys?: string[] }
export type DsRow = Record<string, unknown> & { _key: string; _run?: string | null; _wp?: string | null };
export interface DatasetSpec {
  name: string; label: string; scope: string[]; optional_scope: string[];
  /** 062: a szolgáltatás alapsorrendje (kért rendezés nélkül ebben a sorrendben jönnek a sorok). */
  natural_sort?: DsSort[];
}
export interface DsPage {
  dataset: DatasetSpec; columns: DsColumn[]; rows: DsRow[]; total: number; matched: number; offset: number; limit: number;
  facets: Record<string, string[]>;
}
export type DsScope = Record<string, string>;
export type ExportFormat = "xlsx" | "csv" | "json";
export type ExportRows = "all" | "filtered" | "selected";
export interface DsExport { format: ExportFormat; rows: ExportRows; columns?: string[] | null; query: DsQuery }

/** A letöltés fájlneve a fejlécből: a pontos (UTF-8, RFC 5987) név, ennek híján az ASCII-tartalék (066: ékezetes név). */
export function filenameFromDisposition(disp: string): string {
  const exact = /filename\*=UTF-8''([^;]+)/i.exec(disp)?.[1];
  if (exact) {
    try { return decodeURIComponent(exact); } catch { /* hibás kódolás: a tartalék név */ }
  }
  return /filename="([^"]+)"/.exec(disp)?.[1] ?? "letoltes";
}

/** Letöltés lekéréssel → fájl (a régi projekt `downloadExport` mintája): POST-os kérés és a szerző-fejléc is működik. */
async function downloadPost(path: string, body: unknown): Promise<{ filename: string; rows: number }> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "offline", t("A helyi szolgáltatás nem érhető el. Fut a scripts\\dev.ps1 start?"));
  }
  if (!res.ok) {
    let d: { error?: string; message?: string } = {};
    try { d = await res.json(); } catch { /* nem JSON hibaválasz */ }
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

/** 057: figyelt munkamappa (a régi V4 „Figyelt mappák” mintájára). */
export interface WatchedFolder {
  id?: string | null; name: string; path: string; enabled: boolean; recursive: boolean; batch_mode: "folder" | "daily";
  recipe_id: string | null; params: Record<string, string>; interval_min: number;
  next_at?: string | null; last_at?: string | null; last_status?: "ok" | "error" | null;
  last_result?: { new?: number; settling?: number; workpackage?: string | null; error?: string } | null;
}

const ACTOR_KEY = "jav.actor";
/** Emberi döntésnél (javítás, jóváhagyás, teendő zárása) a szolgáltatás megköveteli a szerző nevét. A magyar szöveg a
 *  fordítási kulcs: megjelenítéskor `t(NO_ACTOR)`. */
export const NO_ACTOR = "add meg a neved fent a „Ki dolgozik?” mezőben (a javítás és a jóváhagyás szerzőhöz kötött)";

export function getActor(): string {
  try {
    return localStorage.getItem(ACTOR_KEY) ?? memoryActor;
  } catch {
    return memoryActor;
  }
}

/** 061: a „Ki dolgozik?” és a névlista változásáról a nézetek eseményből értesülnek (`useActor`, `useEvent`). */
export const ACTOR_EVENT = "jav-actor";
export const USERS_EVENT = "jav-users";
/** 061: a szolgáltatás elutasította a nevet, mert nincs a Felhasználók listáján. Megjelenítéskor `t(UNKNOWN_ACTOR)`. */
export const UNKNOWN_ACTOR = "a „Ki dolgozik?” mezőben válaszd ki a neved a Felhasználók listájából";

let memoryActor = ""; // ha a böngésző nem enged tárolást (privát ablak), a név a munkamenetig él

// 066 Á21: a név a lapok közös tárolójában van, a kérés mindig az ottanit küldi. Ha egy másik lapon átállítják, ennek a
// lapnak a kijelzése is frissül, így a lap azt a nevet mutatja, amelyikkel a műveletei mennek.
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
    /* privát ablakban a tárolás tilos lehet; a név ekkor csak a munkamenetig él */
  }
  window.dispatchEvent(new Event(ACTOR_EVENT));
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const actor = getActor();
  if (actor) headers["X-Actor"] = encodeURIComponent(actor); // a szolgáltatás dekódolja (ékezet a fejlécben)
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
  recipes: () => request<{ recipes: Recipe[]; help?: RecipeHelp }>("GET", "/recipes"),
  workpackages: () => request<{ workpackages: WorkpackageRow[] }>("GET", "/workpackages"),
  workpackage: (id: string) => request<WorkpackageView>("GET", `/workpackages/${enc(id)}`),
  createFromFolder: (folder: string, name?: string) =>
    request<{ workpackage: Workpackage; readiness: Readiness }>("POST", "/workpackages", { folder, ...(name ? { name } : {}) }),
  createFromFiles: (paths: string[], name: string) =>
    request<{ workpackage: Workpackage; readiness: Readiness }>("POST", "/workpackages", { paths, name }),
  // 058: elrejtés (a futások és az eredmények megmaradnak), visszahozás, átnevezés; törlés csak futás nélküli csomagon
  decideTask: (runId: string, itemId: string, index: number, decision: "accepted" | "rejected") =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/tasks/${index}/decision`, { decision }),
  /** 062: az elfogadott feladat kézzel elvégezve (vagy vissza). */
  markTaskDone: (runId: string, itemId: string, index: number, done: boolean) =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/tasks/${index}/done`, { done }),
  addAttachments: (id: string, expected_revision: number) =>
    request<WorkpackageView>("POST", `/workpackages/${enc(id)}/attachments`, { expected_revision }),
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
  run: (runId: string) => request<RunView>("GET", `/runs/${enc(runId)}`),
  journal: (runId: string) => request<{ calls: Call[]; budget: Budget }>("GET", `/runs/${enc(runId)}/journal`),
  cancel: (runId: string) => request<{ status: string }>("POST", `/runs/${enc(runId)}/cancel`, {}),
  approve: (runId: string) => request<RunView>("POST", `/runs/${enc(runId)}/approve`, {}),
  item: (runId: string, itemId: string) => request<ItemResult>("GET", `/runs/${enc(runId)}/items/${enc(itemId)}`),
  saveCorrection: (runId: string, itemId: string, body: { fields: Record<string, CorrectionValue>; expected_revision: number; note?: string;
    sources?: Record<string, number[]> }) =>
    request<ItemResult>("POST", `/runs/${enc(runId)}/items/${enc(itemId)}/correction`, body),
  resolveReason: (reasonId: number, note?: string) =>
    request<{ status: string }>("POST", `/review-reasons/${reasonId}/resolve`, note ? { note } : {}),
  worker: () => request<{ running: boolean; stop_requested: boolean; jobs: Record<string, number> }>("GET", "/worker"),
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
  workerStop: () => request<Record<string, unknown>>("POST", "/worker/stop", {}),
  /** 071: a futó szolgáltatás verziója és az induláskor rögzített commit. */
  health: () => request<Health>("GET", "/health"),
  backupStatus: () => request<BackupInfo>("GET", "/system/backup"),
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
  settings: () => request<{ confidence_bands: { confident: number; check: number } }>("GET", "/settings"),
  normalize: (doc_type: string, field: string, text: string) =>
    request<{ ok: boolean; value: string | null; reasons: string[]; kind: string }>("POST", "/normalize", { doc_type, field, text }),
};
