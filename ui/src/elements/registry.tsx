// 231 (plan stage A, A6; DECISIONS 231): the screen elements a case's tabs are built from (configs/screen_elements.json).
// The interface renders an element by its type, with the data the service sent for it (what its step's capability
// shows); an element may also give its tab's status line and the page's summary. A special element is registered
// once, by the code of the capability it belongs to, and any process pack may use it.
import { lazy, Suspense, type ReactNode } from "react";
import type { CaseElement, CaseView, QuoteView } from "../api";
import { t } from "../i18n";
import { moneyText } from "../labels";
import { quoteStatus, quoteSummary } from "../views/quotes/quoteStatus";
import { costTotal, handoverStatus, replyStatus } from "./caseStatus";

export interface ElementProps { caseId: string; element: CaseElement; page: CaseView; onChanged: () => void }
export interface ElementSpec {
  render: (p: ElementProps) => ReactNode;
  /** the line under its tab's name (the first element of a tab that gives one) */
  status?: (p: ElementProps) => string | null;
  /** the page's summary (the first element of the page that gives one) */
  summary?: (p: ElementProps) => string | null;
}

// the quote's capabilities' elements: their pages load only when a case shows one; their status lines and summary are
// the quote package's (quoteStatus.ts), from the quote view their data carries
const quote = () => import("../views/quotes/QuoteElements");
const RecordView = lazy(() => quote().then((m) => ({ default: m.RecordView })));
const MatchProposal = lazy(() => quote().then((m) => ({ default: m.MatchProposal })));
const LineEditor = lazy(() => quote().then((m) => ({ default: m.LineEditor })));
const Approval = lazy(() => quote().then((m) => ({ default: m.Approval })));
// 231 (A7e): the general elements any pack may show: a send step's handovers, a reply step's wait, the case's events and
// cost; their status lines come with them (a small module, loaded with the page)
const general = () => import("./CaseElements");
const HandoverView = lazy(() => general().then((m) => ({ default: m.HandoverView })));
const ReplyWait = lazy(() => general().then((m) => ({ default: m.ReplyWait })));
const Timeline = lazy(() => general().then((m) => ({ default: m.Timeline })));
const CostView = lazy(() => general().then((m) => ({ default: m.CostView })));
const lazily = (C: (p: ElementProps) => ReactNode) =>
  (p: ElementProps) => <Suspense fallback={<p className="muted">{t("Loading…")}</p>}><C {...p} /></Suspense>;
const quoteOf = (p: ElementProps) => (p.element.data as { quote?: QuoteView } | null)?.quote;
const quoteLine = (which: "process" | "review" | "result") => (p: ElementProps) => quoteStatus(quoteOf(p))?.[which] ?? null;

export const ELEMENTS: Record<string, ElementSpec> = {
  record_view: { render: lazily(RecordView), status: quoteLine("process"), summary: (p) => quoteSummary(quoteOf(p)) },
  match_proposal: { render: lazily(MatchProposal), status: quoteLine("review") },
  line_editor: { render: lazily(LineEditor), status: quoteLine("review") },
  approval: { render: lazily(Approval), status: quoteLine("result") },
  handover_view: { render: lazily(HandoverView), status: (p) => handoverStatus(p)?.text ?? null },
  reply_wait: { render: lazily(ReplyWait), status: (p) => replyStatus(p)?.text ?? null },
  timeline: { render: lazily(Timeline) },
  cost: { render: lazily(CostView), status: (p) => { const usd = costTotal(p); return usd === null ? null : `${moneyText(usd)} USD`; } },
};
