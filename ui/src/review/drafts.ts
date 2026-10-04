// Drafts (045 K3b, modelled on V4's documentDrafts.ts): the unsaved correction per item, within the session.
// It survives switching items and going back; „Elvetés” (Discard) clears it, a successful save clears what it sent (090:
// a change made while the save was under way stays). The base (the
// revision of the saved correction) is stored too: if a newer revision has appeared on the server in the meantime,
// the UI reports a conflict and does not blindly save over it.
// 048: the draft of a line-item list is the whole list (rows, text per cell; for a simple list, the `*` column).
import { useSyncExternalStore } from "react";
import type { Citation } from "../native";

export interface Draft {
  baseRevision: number;
  values: Record<string, string>; // field -> typed / chosen value
  sources: Record<string, number[]>; // field -> the words selected on the image
  lists?: Record<string, ListRow[]>; // line-item list -> the edited rows (the whole list)
  baseResultVersion?: string;
  nativeValues?: Record<string, string | null>;
  nativeSources?: Record<string, Citation[]>;
  nativeCitationEdits?: Record<string, { element: string; quote: string }>;
}

export type ListRow = Record<string, string>;

/** Whether the draft has an unsaved change (a field or a line-item list). */
export const isDirty = (d: Draft | undefined) => Boolean(d && (Object.keys(d.values).length || Object.keys(d.lists ?? {}).length
  || Object.keys(d.nativeValues ?? {}).length || Object.keys(d.nativeSources ?? {}).length || Object.keys(d.nativeCitationEdits ?? {}).length));

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

/** 090 (audit N06): after a successful save, only what was sent (`sent`, the working copy the save was built from)
 *  leaves the working copy: a field, its selection on the image or a line-item list changed while the save was under
 *  way stays, rebased on the saved revision, so nothing typed is lost without being sent or discarded. */
export function settleDraft(key: string, sent: Draft | undefined, baseRevision: number): void {
  const d = store.get(key);
  if (!d) return;
  const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  const values = { ...d.values };
  const sources = { ...d.sources };
  const lists = { ...(d.lists ?? {}) };
  for (const f of Object.keys(values)) {
    if (sent && f in sent.values && sent.values[f] === values[f] && same(sent.sources[f], sources[f])) {
      delete values[f];
      delete sources[f];
    }
  }
  for (const f of Object.keys(lists)) if (sent?.lists && f in sent.lists && same(sent.lists[f], lists[f])) delete lists[f];
  const next: Draft = { ...d, baseRevision, values, sources, lists };
  if (isDirty(next)) store.set(key, next);
  else store.delete(key);
  emit();
}

export function clearDraft(key: string): void {
  store.delete(key);
  emit();
}

/** A native draft stays attached to the exact publication it was written against. */
export function setNativeField(key: string, revision: number, version: string, field: string, value: string | null): void {
  const d = store.get(key) ?? { baseRevision: revision, baseResultVersion: version, values: {}, sources: {} };
  store.set(key, { ...d, nativeValues: { ...d.nativeValues, [field]: value }, nativeSources: { ...d.nativeSources, [field]: [] } });
  emit();
}

export function setNativeSources(key: string, revision: number, version: string, field: string, citations: Citation[]): void {
  const d = store.get(key) ?? { baseRevision: revision, baseResultVersion: version, values: {}, sources: {} };
  store.set(key, { ...d, nativeSources: { ...d.nativeSources, [field]: citations } });
  emit();
}

/** Unchecked citation text also survives item switches and reloads; it is never sent as a verified citation. */
export function setNativeCitationEdit(key: string, revision: number, version: string, field: string, edit: { element: string; quote: string } | null): void {
  const d = store.get(key) ?? { baseRevision: revision, baseResultVersion: version, values: {}, sources: {} };
  const nativeCitationEdits = { ...d.nativeCitationEdits };
  if (edit) nativeCitationEdits[field] = edit; else delete nativeCitationEdits[field];
  const next = { ...d, nativeCitationEdits };
  if (isDirty(next)) store.set(key, next); else store.delete(key);
  emit();
}

export function settleNativeDraft(key: string, sent: Draft | undefined, revision: number, version: string): void {
  const d = store.get(key);
  if (!d || d.baseResultVersion !== version) return;
  const nativeValues = { ...d.nativeValues };
  const nativeSources = { ...d.nativeSources };
  const fields = new Set([...Object.keys(nativeValues), ...Object.keys(nativeSources)]);
  for (const f of fields) {
    // Presence matters: null, empty text and an absent override are different states.
    const snapshot = (x: Draft | undefined) => JSON.stringify([Object.hasOwn(x?.nativeValues ?? {}, f), x?.nativeValues?.[f],
      Object.hasOwn(x?.nativeSources ?? {}, f), x?.nativeSources?.[f]]);
    if (sent && snapshot(sent) === snapshot(d)) { delete nativeValues[f]; delete nativeSources[f]; }
  }
  const next = { ...d, baseRevision: revision, nativeValues, nativeSources };
  if (isDirty(next)) store.set(key, next); else store.delete(key);
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
