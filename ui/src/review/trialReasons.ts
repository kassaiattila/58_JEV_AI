// 150 (the owner's decision of 2026-10-12): the to-dos left on a document by trial runs. A trial run cannot be
// approved, so they never close by themselves; on the review page they are hidden by default and a switch shows them.
// Per person, like the name mode (`names.ts`): kept in the browser under the name of the person working; without
// storage (private window) it lasts for the session.
import { useState } from "react";
import { ACTOR_EVENT, getActor, type Reason } from "../api";
import { useEvent } from "../hooks";

export const TRIAL_REASONS_EVENT = "jav-trial-reasons";
const memory: Record<string, boolean> = {};

const storageKey = () => `jav.trial-reasons.${getActor() || "-"}`;

export function getShowTrialReasons(): boolean {
  const key = storageKey();
  try {
    return localStorage.getItem(key) === "show";
  } catch {
    return memory[key] ?? false; // no storage in a private window: the choice made in this session, if any
  }
}

export function setShowTrialReasons(show: boolean): void {
  const key = storageKey();
  memory[key] = show;
  try {
    localStorage.setItem(key, show ? "show" : "hide");
  } catch {
    /* no storage in a private window: the choice lasts only for the session */
  }
  window.dispatchEvent(new Event(TRIAL_REASONS_EVENT));
}

/** The current choice; the view follows a switch elsewhere on the page and a change of the person working. */
export function useShowTrialReasons(): boolean {
  const [show, setShow] = useState(getShowTrialReasons);
  useEvent(TRIAL_REASONS_EVENT, () => setShow(getShowTrialReasons()));
  useEvent(ACTOR_EVENT, () => setShow(getShowTrialReasons()));
  return show;
}

/** The earlier to-dos to show: those left by trial runs only when the switch is on. */
export function visibleEarlier(reasons: Reason[], showTrial: boolean): Reason[] {
  return showTrial ? reasons : reasons.filter((r) => !r.trial);
}
