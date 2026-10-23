// 224 (plan G-process-core P3c): a version's state as a state mark (DESIGN.md §4), in one place for everything a person
// keeps in versions - the price lists and the own output templates (the service's shared versions, `jav/core/versions.py`):
// active green, a draft a neutral ring, superseded a faint ring, retired a dash.
import type { OutputTemplateState } from "../api";
import { t } from "../i18n";

const MARK: Record<OutputTemplateState, string> = { active: "s-done", draft: "s-trial", superseded: "s-held", retired: "s-removed" };

export const versionStateLabel = (s: OutputTemplateState) =>
  ({ active: t("Active"), draft: t("Draft"), superseded: t("Superseded"), retired: t("Retired") })[s];

export function VersionState({ state }: { state: OutputTemplateState }) {
  return <span className={`status ${MARK[state]}`}>{versionStateLabel(state)}</span>;
}
