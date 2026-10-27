// 231 (stage D0, D0-g; the reassessment of 2026-10-26, F15, P12): the shared save behaviour of an editor, so a person's
// typed work is never lost without a word and never silently written over another person's.
//
// - `saveState`: what an editor's save line says: no change, changed (not saved yet), saving, saved, conflict (someone
//   else saved meanwhile: nothing was written) or unknown (the connection broke: whether it was saved is not known).
// - The unsaved work of an editor (`keepWork`, `workOf`, `useWork`, `updateWork`) lives in this page's memory only, by
//   what it edits: it
//   survives switching to another case and back, never reaches the browser's storage (business data is not kept on
//   the machine), and before the page is closed or reloaded with any of it the browser warns. `useHasWork` lets
//   another element of the page see it (an approval is not given while the work it approves is not saved).
// - `compare(base, mine, theirs)` and `merge(theirs, base, mine)`: after a conflict, my changes (base -> mine) beside
//   the version now saved (theirs), field by field, each marked when they changed it too; keeping mine applies only my
//   changes over theirs, so what they changed and I did not stays theirs. A list of rows with an `id` is compared row
//   by row (a row I removed, a row I added); any other value as a whole.
import { useSyncExternalStore } from "react";

export type SaveState = "clean" | "changed" | "saving" | "saved" | "conflict" | "unknown";

/** The save line's state from what the editor knows; a failure outweighs the rest until it is resolved. */
export function saveState(s: { saving: boolean; failed: "conflict" | "unknown" | null; changed: boolean; savedAt: string | null }): SaveState {
  if (s.failed) return s.failed;
  if (s.saving) return "saving";
  if (s.changed) return "changed";
  return s.savedAt ? "saved" : "clean";
}

// --- the page's memory of unsaved work ---------------------------------------------------------------------------------

const work = new Map<string, unknown>();
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

/** Keeps an editor's unsaved work under `key` (null: there is none any more). */
export function keepWork(key: string, value: unknown): void {
  if (value === null || value === undefined) {
    if (!work.delete(key)) return;
  } else work.set(key, value);
  emit();
}

export function workOf<T>(key: string): T | undefined {
  return work.get(key) as T | undefined;
}

/** Whether there is unsaved work under `key` (or anywhere on the page). */
export function hasWork(key?: string): boolean {
  return key === undefined ? work.size > 0 : work.has(key);
}

const subscribe = (cb: () => void) => { listeners.add(cb); return () => { listeners.delete(cb); }; };

export function useHasWork(key: string): boolean {
  return useSyncExternalStore(subscribe, () => work.has(key));
}

/** An editor's unsaved work, read where it lives (so a save finishing after the editor closed still settles it). */
export function useWork<T>(key: string): T | undefined {
  return useSyncExternalStore(subscribe, () => work.get(key) as T | undefined);
}

/** Changes an editor's work: `fn` gets it (or `empty`), and work that is `idle` afterwards is forgotten. */
export function updateWork<T>(key: string, empty: T, idle: (w: T) => boolean, fn: (w: T) => T): T {
  const next = fn((work.get(key) as T | undefined) ?? empty);
  keepWork(key, idle(next) ? null : next);
  return next;
}

/** For tests: forgets every editor's work. */
export function resetWork(): void {
  work.clear();
  emit();
}

if (typeof window !== "undefined") {
  window.addEventListener("beforeunload", (e) => {
    if (!work.size) return;
    e.preventDefault();
    e.returnValue = ""; // older browsers only ask because of this
  });
}

// --- my changes beside theirs ------------------------------------------------------------------------------------------

type Leaf = { path: string[]; value: unknown };
const ROW = "\u0000row";  // a row's presence, by its id

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const rows = (v: unknown): v is Record<string, unknown>[] => Array.isArray(v) && v.length > 0 && v.every((r) => isObj(r) && "id" in r);
const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

function flatten(value: unknown, path: string[] = [], out = new Map<string, Leaf>()): Map<string, Leaf> {
  if (rows(value)) {
    value.forEach((row, n) => {
      if (row.id === null || row.id === undefined) {
        out.set(JSON.stringify([...path, `+${n}`]), { path: [...path, `+${n}`], value: row });  // a row not saved yet
        return;
      }
      const at = [...path, `#${String(row.id)}`];
      out.set(JSON.stringify(at), { path: at, value: ROW });
      for (const [k, v] of Object.entries(row)) if (k !== "id") flatten(v, [...at, k], out);
    });
  } else if (isObj(value) && Object.keys(value).length) {
    for (const [k, v] of Object.entries(value)) flatten(v, [...path, k], out);
  } else {
    out.set(JSON.stringify(path), { path, value });
  }
  return out;
}

export interface Change {
  /** where: object keys, `#<id>` a row, `+<n>` a row added */
  path: string[];
  before: unknown;
  /** undefined: I removed it (a row) */
  mine: unknown;
  /** undefined: it is not there now (they removed the row) */
  theirs: unknown;
  /** they changed it too since the version I started from */
  both: boolean;
  /** D-a: the row it belongs to is not there now (they removed it): my change cannot be applied */
  gone: boolean;
}

const isRow = (path: string[]) => path[path.length - 1]?.startsWith("#") ?? false;
const isAdded = (path: string[]) => path[path.length - 1]?.startsWith("+") ?? false;

function myChanges(base: unknown, mine: unknown): Leaf[] {
  const a = flatten(base), b = flatten(mine);
  const removed = new Set([...a.values()].filter((l) => l.value === ROW && !b.has(JSON.stringify(l.path))).map((l) => JSON.stringify(l.path)));
  const under = (path: string[]) => [...removed].some((r) => { const p = JSON.parse(r) as string[]; return p.length < path.length && p.every((s, i) => path[i] === s); });
  // a list of rows emptied (or filled from empty) is its rows removed (or added), not a new value of the whole list
  const rowsAt = (m: Map<string, Leaf>, path: string[]) => [...m.values()].some((l) =>
    l.path.length === path.length + 1 && path.every((s, i) => l.path[i] === s) && /^[#+]/.test(l.path[path.length]));
  const emptyList = (l: Leaf | undefined) => Array.isArray(l?.value) && (l.value as unknown[]).length === 0;
  const out: Leaf[] = [];
  for (const key of new Set([...a.keys(), ...b.keys()])) {
    const path = (a.get(key) ?? b.get(key))!.path;
    if ((emptyList(a.get(key)) && rowsAt(b, path)) || (emptyList(b.get(key)) && rowsAt(a, path))) continue;
    if (!same(a.get(key)?.value, b.get(key)?.value) && !under(path)) out.push({ path, value: b.get(key)?.value });
  }
  return out;
}

/** My changes since `base`, each beside the value saved now (`theirs`). */
/** The row of `rows` (not in `base` at that place) that holds what an added row holds: a row I added that a save of
 *  mine, whose outcome I did not know, has added already (the service gave it an id). */
function addedThere(rowsNow: unknown, base: Map<string, Leaf>, parent: string[], row: unknown, taken: Set<unknown>): unknown {
  if (!Array.isArray(rowsNow) || !isObj(row)) return undefined;
  const { id: _id, ...wanted } = row;
  return rowsNow.find((r) => isObj(r) && !taken.has(r) && !base.has(JSON.stringify([...parent, `#${String(r.id)}`]))
    && same(Object.fromEntries(Object.entries(r).filter(([k]) => k !== "id")), wanted));
}

function at(value: unknown, path: string[]): unknown {
  let node = value;
  for (const seg of path) {
    node = seg.startsWith("#") && Array.isArray(node) ? node.find((r) => isObj(r) && `#${String(r.id)}` === seg)
      : isObj(node) ? node[seg] : undefined;
    if (node === undefined) return undefined;
  }
  return node;
}

export function compare(base: unknown, mine: unknown, theirs: unknown): Change[] {
  const a = flatten(base), c = flatten(theirs);
  const taken = new Set<unknown>();
  return myChanges(base, mine).map(({ path, value }) => {
    const key = JSON.stringify(path);
    const before = a.get(key)?.value;
    if (isAdded(path)) {
      const there = addedThere(at(theirs, path.slice(0, -1)), a, path.slice(0, -1), value, taken);
      if (there !== undefined) taken.add(there);
      return { path, before, mine: value, theirs: there, both: false, gone: false };
    }
    const now = c.get(key)?.value;
    const gone = path.some((s, i) => s.startsWith("#") && !c.has(JSON.stringify(path.slice(0, i + 1))));
    // D-a: a row I removed that they changed meanwhile: removing it would drop their change
    const changedUnder = isRow(path) && value === undefined && [...a.values(), ...c.values()].some((l) =>
      l.path.length > path.length && path.every((s, i) => l.path[i] === s)
      && !same(a.get(JSON.stringify(l.path))?.value, c.get(JSON.stringify(l.path))?.value));
    return { path, before, mine: value === ROW ? true : value, theirs: gone ? undefined : now === ROW ? true : now,
             both: gone || changedUnder || !same(now, before), gone: gone && !isRow(path) };
  });
}

/** `theirs` with my changes since `base` in place: a field I changed takes my value, a row I removed goes, a row I added
 *  is added (unless a save of mine added it already); a field of a row they removed is left out. */
export function merge<T>(theirs: T, base: T, mine: T): T {
  const out = structuredClone(theirs) as unknown;
  const a = flatten(base);
  const taken = new Set<unknown>();
  for (const { path, value } of myChanges(base, mine)) {
    let node: unknown = out;
    let ok = true;
    for (const seg of path.slice(0, -1)) {
      node = seg.startsWith("#") && Array.isArray(node) ? node.find((r) => isObj(r) && `#${String(r.id)}` === seg)
        : isObj(node) ? node[seg] : undefined;
      if (node === undefined) { ok = false; break; }
    }
    const last = path[path.length - 1];
    if (!ok) continue;
    if (isRow(path)) {
      if (value === undefined && Array.isArray(node)) {
        const i = node.findIndex((r) => isObj(r) && `#${String(r.id)}` === last);
        if (i >= 0) node.splice(i, 1);
      }
    } else if (isAdded(path)) {
      const there = addedThere(node, a, path.slice(0, -1), value, taken);  // added already by a save of mine
      if (there !== undefined) taken.add(there);
      else if (Array.isArray(node)) node.push(structuredClone(value));
    } else if (isObj(node)) {
      if (value === undefined) delete node[last]; else node[last] = structuredClone(value);
    }
  }
  return out as T;
}
