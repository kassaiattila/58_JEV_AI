// Munkapéldányok (045 K3b, a V4 documentDrafts.ts mintája): a mentetlen javítás tételenként, a munkameneten belül.
// Tételváltáskor és visszalépéskor megmarad; sikeres mentés vagy „Elvetés” törli. Az alap (a mentett javítás
// verziója) is benne van: ha közben a szerveren újabb verzió lett, a felület ütközést jelez, és nem ment rá vakon.
// 048: a tételes lista munkapéldánya a teljes lista (sorok, cellánként szöveg; egyszerű listánál a `*` oszlop).
import { useSyncExternalStore } from "react";

export interface Draft {
  baseRevision: number;
  values: Record<string, string>; // mező -> beírt / kiválasztott érték
  sources: Record<string, number[]>; // mező -> a képen kijelölt szavak
  lists?: Record<string, ListRow[]>; // tételes lista -> a szerkesztett sorok (a teljes lista)
}

export type ListRow = Record<string, string>;

/** Van-e mentetlen módosítás a munkapéldányban (mező vagy tételes lista). */
export const isDirty = (d: Draft | undefined) => Boolean(d && (Object.keys(d.values).length || Object.keys(d.lists ?? {}).length));

const store = new Map<string, Draft>();
const listeners = new Set<() => void>();

// 066 Á20: a munkapéldány a lap saját tárolójában (sessionStorage) is megvan, így egy újratöltést túlél; a lap bezárása
// vagy újratöltése előtt mentetlen javításnál a böngésző figyelmeztet. Más lap nem látja (a tároló laponkénti).
const STORAGE_KEY = "jav.drafts";

function persist(): void {
  try {
    if (store.size) sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...store]));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* privát ablakban a tárolás tilos lehet; a munkapéldány ekkor csak a memóriában él */
  }
}

/** A tárolt munkapéldányok betöltése (induláskor; sérült adatnál üres tár). */
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

/** Van-e bármelyik tételen mentetlen javítás. */
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
    e.returnValue = ""; // a régebbi böngészők ettől kérdeznek rá
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

/** Ütközés után: a munkapéldány az új szerververzióra épül (a beírt értékek maradnak). */
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

/** Tesztekhez: a tár ürítése. */
export function resetDrafts(): void {
  store.clear();
  emit();
}
