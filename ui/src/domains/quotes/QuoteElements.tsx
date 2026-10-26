// 231 (plan stage A, A6; DECISIONS 231): the quote's capabilities' screen elements on a case's page. Each renders the
// part of the quote package's page it stands for, from the quote view its data carries (jav/domains/quotes/capabilities.py
// `_quote_view`), so a case of the IT quote's process pack looks as the quote package did. Asking for the proposal or the
// letter starts the case's step (a person's start), which asks for it.
import { api } from "../../api";
import type { QuoteView } from "./api";
import type { ElementProps } from "../../elements/registry";
import { t } from "../../i18n";
import { ProposalPanel, RequestPanel } from "./Quote";
import { QuoteApprovalStage, QuoteCompose } from "./QuoteEditor";

const quoteOf = (p: ElementProps) => (p.element.data as { quote?: QuoteView } | null)?.quote ?? null;
const composing = (q: QuoteView) => Boolean(q.draft.draft || q.draft.approval.active);
const loading = <p className="muted">{t("Loading…")}</p>;

export function RecordView(p: ElementProps) {
  const q = quoteOf(p);
  return q ? <RequestPanel view={q} /> : loading;
}

/** Until the quote has a draft, its proposal; then the line editor stands in its place, as on the package's page. */
export function MatchProposal(p: ElementProps) {
  const q = quoteOf(p);
  if (!q) return loading;
  if (composing(q)) return null;
  const step = p.element.step;
  return <ProposalPanel wpId={p.caseId} view={q} onChanged={p.onChanged}
    askStep={step ? () => api.startCaseStep(p.caseId, step) : undefined} />;
}

export function LineEditor(p: ElementProps) {
  const q = quoteOf(p);
  if (!q) return loading;
  return composing(q) ? <QuoteCompose wpId={p.caseId} view={q} onChanged={p.onChanged} /> : null;
}

export function Approval(p: ElementProps) {
  const q = quoteOf(p);
  if (!q) return loading;
  const letter = typeof p.element.letter_step === "string" ? p.element.letter_step : null;
  return <QuoteApprovalStage wpId={p.caseId} view={q} archived={p.page.case.status === "archived"} onChanged={p.onChanged}
    askLetter={letter ? () => api.startCaseStep(p.caseId, letter) : undefined} />;
}
