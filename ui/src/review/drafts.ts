// Drafts (045 K3b, modelled on V4's documentDrafts.ts): the unsaved correction per item, within the session.
// It survives switching items and going back; a successful save or „Elvetés” (Discard) clears it. The base (the
// revision of the saved correction) is stored too: if a newer revision has appeared on the server in the meantime,
// the UI reports a conflict and does not blindly save over it.
// 048: the draft of a line-item list is the whole list (rows, text per cell; for a simple list, the `*` column).
import { useSyncExternalStore } from "react";

export interface Draft {
  baseRevision: number;
  values: Record<string, string>; // field -> typed / chosen value
  sources: Record<string, number[]>; // field -> the words selected on the image
  lists?: Record<string, ListRow[]>; // line-item list -> the edited rows (the whole list)
}

export type ListRow = Record<string, string>;

/** Whether the draft has an unsaved change (a field or a line-item list). */
export const isDirty = (d: Draft | undefined) => Boolean(d && (Object.keys(d.values).length || Object.keys(d.lists ?? {}).length));

const store = new Map<string, Draft>();
const listeners = new Set<() => void>();

// 066 Á20: the draft is also kept in the tab's own storage (sessionStorage), so it survives a reload; before the tab is
// closed or reloaded with an unsaved correction, the browser warns. Other tabs cannot see it (the storage is per tab).
const STORAGE_KEY = "jav.drafts";

function persist(): void {
  try {
    if (store.size) sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...store]));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage may be forbidden in a private window; the draft then lives only in memory */
  }
}

/** Loads the stored drafts (at start-up; with corrupt data, the store is left empty). */
export function hydrateDrafts(): void {
  store.clear();
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    const entries = raw ? (JSON.parse(raw) as [string, Draft][]) : [];
    if (Array.isArray(entries)) for (const [k, d] of entries) if (typeof k === "string" && d && typeof d === "object") store.set(k, d);
  } catch {
    store.clear();
  }
  listeners.forEach((l) => l());
}

/** Whether any item has an unsaved correction. */
export const anyDirty = () => [...store.values()].some(isDirty);

const emit = () => {
  persist();
  listeners.forEach((l) => l());
};

if (typeof window !== "undefined") {
  hydrateDrafts();
  window.addEventListener("beforeunload", (e) => {
    if (!anyDirty()) return;
    e.preventDefault();
    e.returnValue = ""; // older browsers only ask for confirmation because of this
  });
}

export const draftKey = (runId: string, itemId: string) => `${runId}:${itemId}`;

export function getDraft(key: string): Draft | undefined {
  return store.get(key);
}

export function setField(key: string, baseRevision: number, field: string, value: string, sources?: number[] | null): void {
  const d = store.get(key) ?? { baseRevision, values: {}, sources: {} };
  const next: Draft = { ...d, values: { ...d.values, [field]: value }, sources: { ...d.sources } };
  if (sources && sources.length) next.sources[field] = sources;
  else if (sources === null || sources === undefined) delete next.sources[field];
  store.set(key, next);
  emit();
}

export function setList(key: string, baseRevision: number, field: string, rows: ListRow[]): void {
  const d = store.get(key) ?? { baseRevision, values: {}, sources: {} };
  store.set(key, { ...d, lists: { ...(d.lists ?? {}), [field]: rows } });
  emit();
}

export function revertField(key: string, field: string): void {
  const d = store.get(key);
  if (!d) return;
  const values = { ...d.values };
  const sources = { ...d.sources };
  const lists = { ...(d.lists ?? {}) };
  delete values[field];
  delete sources[field];
  delete lists[field];
  const next = { ...d, values, sources, lists };
  if (isDirty(next)) store.set(key, next);
  else store.delete(key);
  emit();
}

/** After a conflict: the draft is rebased on the new server revision (the typed values stay). */
export function rebaseDraft(key: string, baseRevision: number): void {
  const d = store.get(key);
  if (!d) return;
  store.set(key, { ...d, baseRevision });
  emit();
}

export function clearDraft(key: string): void {
  store.delete(key);
  emit();
}

export function useDraft(key: string): Draft | undefined {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => store.get(key),
  );
}

/** For tests: empties the store. */
export function resetDrafts(): void {
  store.clear();
  emit();
}
