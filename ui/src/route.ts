// The route from the part of the address bar after #, so that the selected package or run can be bookmarked and
// survives a reload. Rule (V4 lesson): the identifier in the address is the truth. If that package does not exist,
// „nem található” (not found) is shown, and another one (e.g. the first item of the list) is NOT opened silently.
//
// 057 (decision of 2026-09-28): two main parts — Work packages and Settings. The package's sections: Processing
// (process), Review (review), Result (result). The old addresses (items, to-dos, workflow, reports, data, mailbox,
// run list) lead to their new place, so bookmarks are not lost.

import { resultTables } from "./logic/resultTables";
import { settingsSections } from "./logic/settingsSections";

/** 231 (plan stage A, A1): a page's tab is named by its id; a work package has the three below, a case the tabs its
 *  process pack describes, so the number of tabs is not fixed in the code. */
export type Stage = string;
/** 231 (C3e): a section of Settings, the shared ones and those the domains register (`logic/settingsSections.ts`). */
export type SettingsSection = string;
/** 231 (C3e): a view of a package's Result section, the shared ones and those the domains register
 *  (`logic/resultTables.ts`). */
export type ResultTable = string;

/** 061: a confirmation page before a run is started (in the Processing section) */
export interface StartRequest { mode: "shadow" | "apply"; rerun: boolean; pending?: boolean } // 160-C S3: only the pending items

export type Route =
  // 167: `add` opens the add form at the top of Processing (the package's actions menu leads there)
  | { view: "workpackages"; wpId?: string; stage?: Stage; itemId?: string; table?: ResultTable; runId?: string; start?: StartRequest; add?: boolean;
      /** 261 (B1c): the case whose step made the batch; its pages open under the case's address */
      inCase?: string }
  | { view: "run"; runId: string }
  /** 146: the workflows (the work packages of one job, chained): the list and a control view; 231 (U2c): only the
   *  earlier ones, readable (a new one is a multi-step process's case) */
  | { view: "workflows"; wfId?: string }
  /** 231 (A6): a process pack's case, on one of its tabs (the tab ids come from its pack) */
  | { view: "cases"; caseId: string; tab?: string }
  /** 231 (U0): the case list; `create`: a new case, of the process `pack` when one is chosen */
  | { view: "case-list"; create?: boolean; pack?: string; after?: string }  // 261: `after`, the case whose next period it is
  /** 231 (U3a): `item`, a process of the Processes section (its own page), and `tab`, the page's tab. 263 (E1): a
   *  section's chosen thing is its `item` (a partner, a decision; a product's list and its `tab` the chosen one), and
   *  `open` a part opened inside it (a setting of a process, a rule of a product) */
  | { view: "settings"; section: SettingsSection; item?: string; tab?: string; open?: string }
  /** 061: the selected person's actions on a day („Mai munkám” (My work today)); without a day, today's */
  | { view: "activity"; day?: string }
  /** 216: what waits for the selected person (their open human tasks and anyone's); `all`: trial runs' and
   *  measurements' to-dos too */
  | { view: "waiting"; all?: boolean }
  /** an old report or data address: leads to the Result section of the run's package (the package has to be looked up
   *  from the run) */
  | { view: "legacy-result"; runId?: string; table?: ResultTable };

/** A work package's three sections (057). */
export const STAGES: Stage[] = ["process", "review", "result"];
const OLD_TAB: Record<string, Stage> = { items: "review", reviews: "review", workflow: "process" };
const OLD_DATASET: Record<string, ResultTable> = {
  documents: "documents", datapoints: "datapoints", line_items: "line_items", utility_cost: "utility", utility_sources: "utility",
};

/** 167 (review 160 U-12): a malformed escape in the address (a cut-off "%E0%A4") is kept as it is instead of throwing,
 *  which used to take down the whole interface and the reload with it. */
function decodePart(part: string): string {
  try {
    return decodeURIComponent(part);
  } catch {
    return part;
  }
}

/** 261 (plan B, B1c; the owner's decision of 2026-10-29: the review opens under the case's address): the batches a
 *  case's step made, each with its case, as the service named them (a batch's page names its case, a document step its
 *  batch) or an address did; a link to such a batch's pages leads under its case. */
const CASE_OF_BATCH = new Map<string, string>();
export function batchOfCase(wpId: string, caseId: string): void {
  CASE_OF_BATCH.set(wpId, caseId);
}

/** A batch's address after its id (`parts[0]`): its section, item, run start, adding, result table and run. */
function batchRoute(parts: string[], params: URLSearchParams): Extract<Route, { view: "workpackages" }> {
  const raw = parts[1] ?? "";
  const stage = STAGES.includes(raw as Stage) ? (raw as Stage) : OLD_TAB[raw];
  const r: Extract<Route, { view: "workpackages" }> = { view: "workpackages", wpId: parts[0], stage };
  if (stage === "review" && parts[2]) r.itemId = parts[2];
  if (stage === "process" && parts[2] === "start") {
    r.start = { mode: params.get("mode") === "apply" ? "apply" : "shadow", rerun: params.get("rerun") === "1" };
    if (params.get("pending") === "1") r.start.pending = true;
  }
  if (stage === "process" && parts[2] === "add") r.add = true;
  if (stage === "result") {
    if (resultTables().some((x) => x.key === parts[2])) r.table = parts[2];
    if (params.get("run")) r.runId = params.get("run")!;
  }
  return r;
}

export function parseRoute(hash: string): Route {
  const [path, search = ""] = hash.replace(/^#\/?/, "").split("?", 2);
  const parts = path.split("/").filter(Boolean).map(decodePart);
  const params = new URLSearchParams(search);
  switch (parts[0]) {
    case "settings": {  // 231 (C3e): a section the domains registered too; an unknown one opens the first
      if (parts[1] === "tariffs") return { view: "settings", section: "products", item: "tariffs" };  // U3c: a product's list
      const keys = settingsSections().map((s) => s.key);
      const section = keys.includes(parts[1]) ? parts[1] : keys[0];
      const open = section === parts[1] && parts[2] ? params.get("open") : null;
      return { view: "settings", section, ...(section === parts[1] && parts[2] ? { item: parts[2] } : {}),
        ...(section === parts[1] && parts[2] && parts[3] ? { tab: parts[3] } : {}), ...(open ? { open } : {}) };
    }
    case "activity": {
      const day = params.get("day");
      return { view: "activity", day: day && /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : undefined };
    }
    case "waiting":
      return params.get("all") === "1" ? { view: "waiting", all: true } : { view: "waiting" };
    case "runs":
      return parts[1] ? { view: "run", runId: parts[1] } : { view: "settings", section: "system" };
    case "cases":  // 231 (A6)
      if (parts[1] === "new") {  // U0; 261: a case's next period (`?after=<case>`)
        const after = params.get("after");
        return parts[2] ? { view: "case-list", create: true, pack: parts[2], ...(after ? { after } : {}) } : { view: "case-list", create: true };
      }
      if (parts[1] && parts[2] === "batches" && parts[3]) {  // 261 (B1c): a case's step's batch, under the case
        batchOfCase(parts[3], parts[1]);
        return { ...batchRoute(parts.slice(3), params), inCase: parts[1] };
      }
      return parts[1] ? { view: "cases", caseId: parts[1], tab: parts[2] || undefined } : { view: "case-list" };  // A7e
    case "workflows":
      // 231 (U2c): a new workflow is a case of a multi-step process; the repeat's address shows the earlier workflow
      if (parts[1] === "new") return { view: "case-list", create: true };
      return parts[1] ? { view: "workflows", wfId: parts[1] } : { view: "workflows" };
    case "reports":
      return { view: "legacy-result", runId: parts[1], table: "utility" };
    case "data":
      return { view: "legacy-result", runId: params.get("run_id") ?? undefined, table: OLD_DATASET[parts[1] ?? ""] };
    case "workpackages":
      return parts[1] ? batchRoute(parts.slice(1), params) : { view: "workpackages" };
    default: {  // 231 (U2a): an unknown address opens the one work list, the cases
      // 261: an older address of a settings section (the mailboxes' `#/mailbox`, 057) opens that section
      const aliased = settingsSections().find((s) => parts[0] && s.aliases?.includes(parts[0]));
      return aliased ? { view: "settings", section: aliased.key } : { view: "case-list" };
    }
  }
}

export function routeHash(r: Route): string {
  const e = encodeURIComponent;
  switch (r.view) {
    case "settings": return `#/settings/${r.section}${r.item ? `/${e(r.item)}${r.tab ? `/${e(r.tab)}` : ""}${r.open ? `?open=${e(r.open)}` : ""}` : ""}`;
    case "activity": return r.day ? `#/activity?day=${r.day}` : "#/activity";
    case "waiting": return r.all ? "#/waiting?all=1" : "#/waiting";
    case "run": return `#/runs/${e(r.runId)}`;
    case "cases": return r.tab ? `#/cases/${e(r.caseId)}/${e(r.tab)}` : `#/cases/${e(r.caseId)}`;
    case "case-list": return r.create ? (r.pack ? `#/cases/new/${e(r.pack)}${r.after ? `?after=${e(r.after)}` : ""}` : "#/cases/new") : "#/cases";
    case "workflows": return r.wfId ? `#/workflows/${e(r.wfId)}` : "#/workflows";
    case "legacy-result": return r.runId ? `#/reports/${e(r.runId)}` : "#/reports";
    case "workpackages": {
      if (!r.wpId) return "#/workpackages";
      // 261 (B1c): a case's step's batch under its case
      const owner = r.inCase ?? CASE_OF_BATCH.get(r.wpId);
      const base = owner ? `#/cases/${e(owner)}/batches/${e(r.wpId)}` : `#/workpackages/${e(r.wpId)}`;
      if (!r.stage) return base;
      let h = `${base}/${r.stage}`;
      if (r.stage === "review" && r.itemId) h += `/${e(r.itemId)}`;
      if (r.stage === "process" && r.start) h += `/start?mode=${r.start.mode}${r.start.rerun ? "&rerun=1" : ""}${r.start.pending ? "&pending=1" : ""}`;
      else if (r.stage === "process" && r.add) h += "/add";
      if (r.stage === "result") {
        if (r.table) h += `/${r.table}`;
        if (r.runId) h += `?run=${e(r.runId)}`;
      }
      return h;
    }
  }
}

export function go(r: Route): void {
  window.location.hash = routeHash(r);
}

/** 263 (E1): the address of a section of Settings, its chosen thing and what is opened inside it. */
export const settingsHash = (section: SettingsSection, item?: string | null, tab?: string | null, open?: string | null) =>
  routeHash({ view: "settings", section, ...(item ? { item } : {}), ...(item && tab ? { tab } : {}), ...(item && open ? { open } : {}) });

/** The address of one of the package's sections (for the links of cells and buttons). */
export const wpHash = (wpId: string, stage?: Stage, itemId?: string) => routeHash({ view: "workpackages", wpId, stage, itemId });
