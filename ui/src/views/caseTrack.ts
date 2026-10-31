// 263 (plan E, E2; the owner's decisions of 2026-10-30: one case, one track): what a case's page shows as its track,
// left to right. A pack's tab is an item; a tab of sub-case rows (a multi-step case's sub-work) gives an item for each of
// its steps beside an overview item that keeps the rest; a tab that holds only the log (the timeline and the cost) is
// the log, which stands apart at the track's right end and has no number. A step that runs another process's case
// shows that case's work under its item (`CasePage` `StepWork`); a tab that is only a step's document batch shows the
// batch's stages (`BatchStages`).
import type { CaseElement, CaseTab, CaseView } from "../api";

export interface TrackItem {
  /** the address's word: the tab's id, or the step's id for a sub-case's step */
  id: string;
  kind: "tab" | "step";
  /** an English source label (a pack's tab or step title) */
  label: string;
  elements: CaseElement[];
  /** the step a step item runs */
  step?: string;
  /** its number on the track (an overview beside steps has none) */
  n?: number;
}

const LOG_TYPES = new Set(["timeline", "cost"]);
export const isLog = (tab: CaseTab) => tab.elements.length > 0 && tab.elements.every((e) => LOG_TYPES.has(e.type));

/** The case's track items in order, and its log (the elements of every log tab, under the first one's id). */
export function caseTrack(view: CaseView): { items: TrackItem[]; log: TrackItem | null } {
  const items: TrackItem[] = [];
  const logs = view.tabs.filter(isLog);
  const log: TrackItem | null = logs.length
    ? { id: logs[0].id, kind: "tab", label: logs[0].label, elements: logs.flatMap((x) => x.elements) } : null;
  for (const tab of view.tabs) {
    if (isLog(tab)) continue;
    const subs = tab.elements.filter((e) => e.type === "sub_case" && e.step);
    if (!subs.length) {
      items.push({ id: tab.id, kind: "tab", label: tab.label, elements: tab.elements });
      continue;
    }
    items.push({ id: tab.id, kind: "tab", label: tab.label, elements: tab.elements });  // the overview keeps the sub-work table
    for (const e of subs) {
      const step = view.steps[e.step!];
      items.push({ id: e.step!, kind: "step", label: step?.title ?? e.step!, elements: [e], step: e.step! });
    }
  }
  const steps = items.some((x) => x.kind === "step");
  let n = 0;
  return { items: items.map((x) => (steps && x.kind === "tab" ? x : { ...x, n: ++n })), log };
}

/** The document batch of a step's `package_work` element (null: another element, or no batch yet). */
export function packageOf(e: CaseElement): string | null {
  if (e.type !== "package_work") return null;
  return (e.data as { package?: { id: string } | null } | null)?.package?.id ?? null;
}

/** The document batch a tab shows when it is only a step's batch (its `package_work`): the batch's id, else null. */
export function batchOf(elements: CaseElement[]): string | null {
  return elements.length === 1 ? packageOf(elements[0]) : null;
}

/** The item a case opens on: the item of its first step not done (its last item when every step is done). */
export function defaultItem(view: CaseView, items: TrackItem[]): TrackItem | undefined {
  const open = Object.entries(view.steps).find(([, s]) => s.state !== "done");
  if (open) {
    const own = items.find((x) => x.kind === "step" && x.step === open[0]);
    if (own) return own;
    const holding = items.find((x) => x.elements.some((e) => e.step === open[0]));
    if (holding) return holding;
  }
  return items[items.length - 1];
}
