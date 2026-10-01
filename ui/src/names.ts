// 082 (the owner's decision of 2026-10-01): which name the item lists show — the original file name or the unified
// (content-based) one. Per person: kept in the browser under the name in „Ki dolgozik?” (Who is working?), like the
// appearance; without storage (private window) it lasts for the session. The unified name is the default.
import { useState } from "react";
import { ACTOR_EVENT, getActor } from "./api";
import { useEvent } from "./hooks";

export type NameMode = "original" | "unified";
export const NAMES_EVENT = "jav-names";
const DEFAULT: NameMode = "unified";
const memory: Record<string, NameMode> = {};

const storageKey = () => `jav.names.${getActor() || "-"}`;

export function getNameMode(): NameMode {
  const key = storageKey();
  try {
    const saved = localStorage.getItem(key);
    return saved === "original" || saved === "unified" ? saved : DEFAULT;
  } catch {
    return memory[key] ?? DEFAULT; // no storage in a private window: the choice made in this session, if any
  }
}

export function setNameMode(mode: NameMode): void {
  const key = storageKey();
  memory[key] = mode;
  try {
    localStorage.setItem(key, mode);
  } catch {
    /* no storage in a private window: the choice lasts only for the session */
  }
  window.dispatchEvent(new Event(NAMES_EVENT));
}

/** The current choice; the view follows a switch elsewhere on the page and a change of the person working. */
export function useNameMode(): NameMode {
  const [mode, setMode] = useState(getNameMode);
  useEvent(NAMES_EVENT, () => setMode(getNameMode()));
  useEvent(ACTOR_EVENT, () => setMode(getNameMode()));
  return mode;
}
