// The route from the part of the address bar after #, so that the selected package or run can be bookmarked and
// survives a reload. Rule (V4 lesson): the identifier in the address is the truth. If that package does not exist,
// „nem található” (not found) is shown, and another one (e.g. the first item of the list) is NOT opened silently.
//
// 057 (decision of 2026-09-28): two main parts — Work packages and Settings. The package's sections: Processing
// (process), Review (review), Result (result). The old addresses (items, to-dos, workflow, reports, data, mailbox,
// run list) lead to their new place, so bookmarks are not lost.

export type Stage = "process" | "review" | "result";
export type SettingsSection = "mailboxes" | "folders" | "recipes" | "users" | "appearance" | "language" | "system";
export type ResultTable = "emails" | "tasks" | "documents" | "datapoints" | "line_items" | "utility" | "file_names" | "native_facts";

/** 061: a confirmation page before a run is started (in the Processing section) */
export interface StartRequest { mode: "shadow" | "apply"; rerun: boolean }

export type Route =
  | { view: "workpackages"; wpId?: string; stage?: Stage; itemId?: string; table?: ResultTable; runId?: string; start?: StartRequest }
  | { view: "run"; runId: string }
  | { view: "settings"; section: SettingsSection }
  /** 061: the selected person's actions on a day („Mai munkám” (My work today)); without a day, today's */
  | { view: "activity"; day?: string }
  /** an old report or data address: leads to the Result section of the run's package (the package has to be looked up
   *  from the run) */
  | { view: "legacy-result"; runId?: string; table?: ResultTable };

export const STAGES: Stage[] = ["process", "review", "result"];
export const SECTIONS: SettingsSection[] = ["mailboxes", "folders", "recipes", "users", "appearance", "language", "system"];
export const RESULT_TABLES: ResultTable[] = ["emails", "tasks", "documents", "datapoints", "line_items", "utility", "file_names", "native_facts"];
const OLD_TAB: Record<string, Stage> = { items: "review", reviews: "review", workflow: "process" };
const OLD_DATASET: Record<string, ResultTable> = {
  documents: "documents", datapoints: "datapoints", line_items: "line_items", utility_cost: "utility", utility_sources: "utility",
};

export function parseRoute(hash: string): Route {
  const [path, search = ""] = hash.replace(/^#\/?/, "").split("?", 2);
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const params = new URLSearchParams(search);
  switch (parts[0]) {
    case "settings":
      return { view: "settings", section: SECTIONS.includes(parts[1] as SettingsSection) ? (parts[1] as SettingsSection) : "mailboxes" };
    case "mailbox":
      return { view: "settings", section: "mailboxes" };
    case "activity": {
      const day = params.get("day");
      return { view: "activity", day: day && /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : undefined };
    }
    case "runs":
      return parts[1] ? { view: "run", runId: parts[1] } : { view: "settings", section: "system" };
    case "reports":
      return { view: "legacy-result", runId: parts[1], table: "utility" };
    case "data":
      return { view: "legacy-result", runId: params.get("run_id") ?? undefined, table: OLD_DATASET[parts[1] ?? ""] };
    case "workpackages": {
      if (!parts[1]) return { view: "workpackages" };
      const raw = parts[2] ?? "";
      const stage = STAGES.includes(raw as Stage) ? (raw as Stage) : OLD_TAB[raw];
      const r: Route = { view: "workpackages", wpId: parts[1], stage };
      if (stage === "review" && parts[3]) r.itemId = parts[3];
      if (stage === "process" && parts[3] === "start") {
        r.start = { mode: params.get("mode") === "apply" ? "apply" : "shadow", rerun: params.get("rerun") === "1" };
      }
      if (stage === "result") {
        if (RESULT_TABLES.includes(parts[3] as ResultTable)) r.table = parts[3] as ResultTable;
        if (params.get("run")) r.runId = params.get("run")!;
      }
      return r;
    }
    default:
      return { view: "workpackages" };
  }
}

export function routeHash(r: Route): string {
  const e = encodeURIComponent;
  switch (r.view) {
    case "settings": return `#/settings/${r.section}`;
    case "activity": return r.day ? `#/activity?day=${r.day}` : "#/activity";
    case "run": return `#/runs/${e(r.runId)}`;
    case "legacy-result": return r.runId ? `#/reports/${e(r.runId)}` : "#/reports";
    case "workpackages": {
      if (!r.wpId) return "#/workpackages";
      if (!r.stage) return `#/workpackages/${e(r.wpId)}`;
      let h = `#/workpackages/${e(r.wpId)}/${r.stage}`;
      if (r.stage === "review" && r.itemId) h += `/${e(r.itemId)}`;
      if (r.stage === "process" && r.start) h += `/start?mode=${r.start.mode}${r.start.rerun ? "&rerun=1" : ""}`;
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

/** The address of one of the package's sections (for the links of cells and buttons). */
export const wpHash = (wpId: string, stage?: Stage, itemId?: string) => routeHash({ view: "workpackages", wpId, stage, itemId });
