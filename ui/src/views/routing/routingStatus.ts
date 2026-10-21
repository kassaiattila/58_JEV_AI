// 195 (plan G-tidy R5): an email routing package's status lines and summary, which the package list and the
// package's page show for every routing package, apart from the routing pages, which load only when one is opened
// (`ui/src/logic/registry.tsx`).
import type { WorkpackageView } from "../../api";
import { t } from "../../i18n";
import type { Stage } from "../../route";

/** The stages' status line and the package's summary (`ui/src/logic/registry.tsx`). */
export function routingStatus(view: WorkpackageView): Record<Stage, string> | null {
  const r = view.routing;
  if (!r) return null;
  return {
    process: t("{{n}} email package(s), {{m}} attachment(s)", { n: r.sources.length, m: r.counts.attachments }),
    review: r.counts.routable - r.counts.decided ? t("{{n}} to decide", { n: r.counts.routable - r.counts.decided }) : t("every document decided"),
    result: t("{{n}} routed", { n: r.counts.accepted }),
  };
}

export function routingSummary(view: WorkpackageView): string | null {
  const r = view.routing;
  return r ? t("Routing of {{n}} email package(s): {{m}} document(s) to route", { n: r.sources.length, m: r.counts.routable }) : null;
}
