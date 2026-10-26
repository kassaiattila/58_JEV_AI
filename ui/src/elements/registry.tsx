// 231 (plan stage A, A6; DECISIONS 231): the screen elements a case's tabs are built from (configs/screen_elements.json).
// The interface renders an element by its type, with the data the service sent for it (what its step's capability
// shows); an element may also give its tab's status line and the page's summary. A special element is registered
// once, by the code of the capability it belongs to, and any process pack may use it. 231 (C3e): the shared elements
// are listed here; a domain's capability registers its own when the interface loads (`registerElement`, from
// `ui/src/domains/<domain>/index.tsx`), and a case page finds both (`elementOf`).
import { lazy, Suspense, type ReactNode } from "react";
import type { CaseElement, CaseView, PackageWorkView, RoutingView } from "../api";
import { t } from "../i18n";
import { moneyText } from "../labels";
import { costTotal, handoverStatus, replyStatus } from "./caseStatus";
import { packageWorkLine } from "./packageWorkStatus";

export interface ElementProps { caseId: string; element: CaseElement; page: CaseView; onChanged: () => void }
export interface ElementSpec {
  render: (p: ElementProps) => ReactNode;
  /** the line under its tab's name (the first element of a tab that gives one) */
  status?: (p: ElementProps) => string | null;
  /** the page's summary (the first element of the page that gives one) */
  summary?: (p: ElementProps) => string | null;
}

// 231 (A7e): the general elements any pack may show: a send step's handovers, a reply step's wait, the case's events and
// cost; their status lines come with them (a small module, loaded with the page)
const general = () => import("./CaseElements");
const HandoverView = lazy(() => general().then((m) => ({ default: m.HandoverView })));
const ReplyWait = lazy(() => general().then((m) => ({ default: m.ReplyWait })));
const Timeline = lazy(() => general().then((m) => ({ default: m.Timeline })));
const CostView = lazy(() => general().then((m) => ({ default: m.CostView })));
const PartnerLink = lazy(() => general().then((m) => ({ default: m.PartnerLink })));
const GeneralApproval = lazy(() => general().then((m) => ({ default: m.GeneralApproval })));
const StartedCases = lazy(() => general().then((m) => ({ default: m.StartedCases })));
// 231 (C1c): the file placement capability's element (its page loads only when a case shows it); (C3e) the pairing's
// are the finance domain's
const FilePlacement = lazy(() => import("./FilePlacement").then((m) => ({ default: m.FilePlacement })));
// 231 (C3b3): the document processing step's element (its page loads only when a case shows it); its tab line is small
const PackageWork = lazy(() => import("./PackageWork").then((m) => ({ default: m.PackageWork })));
/** An element whose page loads only when a case shows it (its module imported on first render). */
export const lazily = (C: (p: ElementProps) => ReactNode) =>
  (p: ElementProps) => <Suspense fallback={<p className="muted">{t("Loading…")}</p>}><C {...p} /></Suspense>;
const placementOf = (p: ElementProps) => p.element.data as RoutingView | null;
const placementLine = (p: ElementProps) => {
  const r = placementOf(p);
  if (!r) return null;
  if (p.element.show === "sources") return t("{{n}} email package(s), {{m}} attachment(s)", { n: r.sources.length, m: r.counts.attachments });
  if (p.element.show === "decide") return r.counts.routable - r.counts.decided ? t("{{n}} to decide", { n: r.counts.routable - r.counts.decided }) : t("every document decided");
  return t("{{n}} routed", { n: r.counts.accepted });
};
const placementSummaryOf = (p: ElementProps) => {
  const r = placementOf(p);
  return r ? t("Routing of {{n}} email package(s): {{m}} document(s) to route", { n: r.sources.length, m: r.counts.routable }) : null;
};

/** D0-d: the capability (by name) of the step an element shows, from the case's page */
const capabilityOf = (p: ElementProps) => (p.element.step ? p.page.steps[p.element.step]?.uses?.split("@")[0] ?? "" : "");
const BODIES = new Map<string, ElementSpec>();

/** D0-d: a domain's own approval of its capability's step (the quote's lines and Word document), shown by the shared
 *  approval element in place of the general one. */
export function registerApprovalBody(capability: string, spec: ElementSpec): void {
  BODIES.set(capability, spec);
}

const approvalBodyOf = (p: ElementProps) => BODIES.get(capabilityOf(p));

export const ELEMENTS: Record<string, ElementSpec> = {
  // D0-d: the approval of any step that approves a version of its own; its domain's own approval where it shows one
  approval: {
    render: (p) => { const body = approvalBodyOf(p); return body ? body.render(p) : lazily(GeneralApproval)(p); },
    status: (p) => approvalBodyOf(p)?.status?.(p) ?? null,
  },
  handover_view: { render: lazily(HandoverView), status: (p) => handoverStatus(p)?.text ?? null },
  reply_wait: { render: lazily(ReplyWait), status: (p) => replyStatus(p)?.text ?? null },
  timeline: { render: lazily(Timeline) },
  partner_link: { render: lazily(PartnerLink) },  // 231 (B1)
  started_cases: { render: lazily(StartedCases) },  // 231 (C1c)
  file_placement: { render: lazily(FilePlacement), status: placementLine, summary: placementSummaryOf },  // 231 (C1c)
  package_work: { render: lazily(PackageWork), status: (p) => packageWorkLine(p.element.data as PackageWorkView | null) },  // 231 (C3b3)
  cost: { render: lazily(CostView), status: (p) => { const usd = costTotal(p); return usd === null ? null : `${moneyText(usd)} USD`; } },
};

const OWN = new Map<string, ElementSpec>();

/** Registers a domain's capability's element by its type (a second registration replaces the first). */
export function registerElement(type: string, spec: ElementSpec): void {
  OWN.set(type, spec);
}

/** The element of a type: a shared one, or one a domain registered (undefined: none). */
export function elementOf(type: string): ElementSpec | undefined {
  return Object.prototype.hasOwnProperty.call(ELEMENTS, type) ? ELEMENTS[type] : OWN.get(type);
}
