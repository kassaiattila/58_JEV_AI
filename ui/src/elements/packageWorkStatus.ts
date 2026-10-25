// 231 (plan stage C, C3b3): the document processing element's tab line, from its data (a small module of its own: the
// case page's tabs read it before the element's page loads).
import type { PackageWorkView } from "../api";
import { t } from "../i18n";

/** The package's documents and where its live run stands. */
export function packageWorkLine(data: PackageWorkView | null): string | null {
  if (!data) return null;
  if (!data.package) return t("no documents");
  const live = (data.runs ?? []).filter((r) => r.mode === "apply");
  const state = live.some((r) => r.approval) ? t("approved") : live.length ? t("live run in progress") : t("waiting for its live run");
  return `${t("{{n}} documents", { n: data.package.items })} · ${state}`;
}
