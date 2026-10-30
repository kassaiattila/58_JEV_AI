// 261 (plan B, B1e): a person's action on a case's step, shared by the elements that offer one (the shared actions,
// the field review's, the form's): the step's action endpoint, the page after it taken at once, a stale page reloaded.
import { useState } from "react";
import { api, ApiError } from "../api";
import { errorText } from "../hooks";
import { t } from "../i18n";
import type { ElementProps } from "./registry";

/** A step's action, with values or a note, then the page again. 261 (Q-rogzites-409): the action's answer is the page
 *  after it, taken at once (a unit saved, then the facts frozen right after, is frozen on the saved state, not on the
 *  page's earlier one); a page made stale by someone else meanwhile is reloaded and says so. */
export function useStepAction(p: ElementProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (name: string, values?: Record<string, unknown>, note?: string) => {
    if (!p.element.step) return false;
    setBusy(true);
    setError(null);
    try {
      const view = note === undefined && values === undefined ? await api.caseStepAction(p.caseId, p.element.step, name)
        : await api.caseStepAction(p.caseId, p.element.step, name, note, values);
      if (p.onView) p.onView(view);
      else p.onChanged();
      return true;
    } catch (e) {
      const stale = e instanceof ApiError && e.status === 409 && e.code === "revision_conflict";
      if (stale) p.onChanged();
      setError(stale ? t("The case changed since it was shown; it has been reloaded. Check it and try again.") : errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}
