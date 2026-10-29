// 231 (plan stage C, C1c): the file placement element's tab lines and the case's summary, from its data (the email
// packages it routes and the counts). 261: the email domain's (until then in the shared `ui/src/elements/registry.tsx`).
import type { ElementProps } from "../../elements/registry";
import { t } from "../../i18n";
import type { RoutingView } from "./api";

const placementOf = (p: ElementProps) => p.element.data as RoutingView | null;

export function placementLine(p: ElementProps): string | null {
  const r = placementOf(p);
  if (!r) return null;
  if (p.element.show === "sources") return t("{{n}} email package(s), {{m}} attachment(s)", { n: r.sources.length, m: r.counts.attachments });
  if (p.element.show === "decide") return r.counts.routable - r.counts.decided ? t("{{n}} to decide", { n: r.counts.routable - r.counts.decided }) : t("every document decided");
  return t("{{n}} routed", { n: r.counts.accepted });
}

export function placementSummary(p: ElementProps): string | null {
  const r = placementOf(p);
  return r ? t("Routing of {{n}} email package(s): {{m}} document(s) to route", { n: r.sources.length, m: r.counts.routable }) : null;
}
