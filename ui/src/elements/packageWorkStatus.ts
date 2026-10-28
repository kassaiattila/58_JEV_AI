// 231 (plan stage C, C3b3): the document processing element's tab line, from its data (a small module of its own: the
// case page's tabs read it before the element's page loads).
import type { PackageWorkView } from "../api";
import { t } from "../i18n";

/** The package's documents and where its live run stands. */
export function packageWorkLine(data: PackageWorkView | null): string | null {
  if (!data) return null;
  if (!data.package) return t("no documents");
  const live = (data.runs ?? []).filter((r) => r.mode === "apply");
  const has = (...statuses: string[]) => live.some((r) => statuses.includes(r.status));
  // U1 (the walkthrough): a live run that has ended says what it waits for, not that it is in progress
  const state = live.some((r) => r.approval) ? t("approved") : !live.length ? t("waiting for its live run")
    : has("queued", "running") ? t("live run in progress") : has("needs_review") ? t("its live run has to-dos")
      : has("done") ? t("its live run waits for approval") : t("its live run stopped");
  return `${t("{{n}} documents", { n: data.package.items })} · ${state}`;
}
