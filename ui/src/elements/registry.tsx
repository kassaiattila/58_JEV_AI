// 231 (plan stage A, A6; DECISIONS 231): the screen elements a case's tabs are built from (configs/screen_elements.json).
// The interface renders an element by its type, with the data the service sent for it (what its step's capability
// shows); an element may also give its tab's status line and the page's summary. A special element is registered
// once, by the code of the capability it belongs to, and any process pack may use it.
import { lazy, Suspense, type ReactNode } from "react";
import type { CaseElement, CaseView, QuoteView, WorkpackageView } from "../api";
import { t } from "../i18n";
import { quoteStatus, quoteSummary } from "../views/quotes/quoteStatus";

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
const lazily = (C: (p: ElementProps) => ReactNode) =>
  (p: ElementProps) => <Suspense fallback={<p className="muted">{t("Loading…")}</p>}><C {...p} /></Suspense>;
const asPackage = (p: ElementProps) => ({ quote: (p.element.data as { quote?: QuoteView } | null)?.quote }) as unknown as WorkpackageView;
const quoteLine = (which: "process" | "review" | "result") => (p: ElementProps) => quoteStatus(asPackage(p))?.[which] ?? null;

export const ELEMENTS: Record<string, ElementSpec> = {
  record_view: { render: lazily(RecordView), status: quoteLine("process"), summary: (p) => quoteSummary(asPackage(p)) },
  match_proposal: { render: lazily(MatchProposal), status: quoteLine("review") },
  line_editor: { render: lazily(LineEditor), status: quoteLine("review") },
  approval: { render: lazily(Approval), status: quoteLine("result") },
};
