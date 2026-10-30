// 231 (plan stage A, A6; DECISIONS 231): the screen elements a case's tabs are built from (configs/screen_elements.json).
// The interface renders an element by its type, with the data the service sent for it (what its step's capability
// shows); an element may also give its tab's status line and the page's summary. A special element is registered
// once, by the code of the capability it belongs to, and any process pack may use it. 231 (C3e): the shared elements
// are listed here; a domain's capability registers its own when the interface loads (`registerElement`, from
// `ui/src/domains/<domain>/index.tsx`), and a case page finds both (`elementOf`).
import { lazy, Suspense, type ReactNode } from "react";
import type { BlockersData, CalculationData, CaseElement, CaseView, DecisionData, DocumentViewData, EvaluationData, FieldReviewData, LetterData,
  MissingInfoData, PackageWorkView, SubCaseData } from "../api";
import { t } from "../i18n";
import { moneyText } from "../labels";
import { blockersStatus, calculationStatus, costTotal, decisionStatus, documentStatus, fieldReviewLine, handoverStatus, letterStatus,
  missingStatus, replyStatus, subCaseStatus, verdictStatus } from "./caseStatus";
import { packageWorkLine } from "./packageWorkStatus";

export interface ElementProps {
  caseId: string; element: CaseElement; page: CaseView; onChanged: () => void;
  /** 261 (Q-rogzites-409): the case's page as an action answered it, taken at once instead of reloading it, so the next
   *  action is made on the state the person sees (the case page gives it) */
  onView?: (view: CaseView) => void;
}
export interface ElementSpec {
  render: (p: ElementProps) => ReactNode;
  /** the line under its tab's name (the first element of a tab that gives one) */
  status?: (p: ElementProps) => string | null;
  /** the page's summary (the first element of the page that gives one) */
  summary?: (p: ElementProps) => string | null;
  /** 261 (B1b): consecutive elements of the type on a tab shown together, each a row of one table (the case page groups
   *  them; `render` shows one alone the same way) */
  rows?: (ps: ElementProps[]) => ReactNode;
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
const SubWorkTable = lazy(() => general().then((m) => ({ default: m.SubWorkTable })));  // 231 (U2c), 261 (B1b)
// 231 (C3e): the pairing's elements are the finance domain's; 261: the file placement's the email domain's
// 231 (C3b3): the document processing step's element (its page loads only when a case shows it); its tab line is small
const PackageWork = lazy(() => import("./PackageWork").then((m) => ({ default: m.PackageWork })));
// 231 (stage D, D-f4): an assessment's data check: the field review, the facts read from the documents, a register's answer
const facts = () => import("./FactElements");
const FieldReview = lazy(() => facts().then((m) => ({ default: m.FieldReview })));
const DocumentFacts = lazy(() => facts().then((m) => ({ default: m.DocumentFacts })));
const LookupView = lazy(() => facts().then((m) => ({ default: m.LookupView })));
// 231 (stage D, D-f5): an assessment's calculation: the rules' evaluation, the missing facts, the premium
const assessment = () => import("./AssessmentElements");
const EvaluationView = lazy(() => assessment().then((m) => ({ default: m.EvaluationView })));
const CalculationView = lazy(() => assessment().then((m) => ({ default: m.CalculationView })));
const MissingInfoView = lazy(() => assessment().then((m) => ({ default: m.MissingInfoView })));
// 231 (stage D, D-f6): a person's decision on another step's result
const DecisionView = lazy(() => import("./DecisionElement").then((m) => ({ default: m.DecisionView })));
const DocumentView = lazy(() => import("./DocumentElement").then((m) => ({ default: m.DocumentView })));
const LetterView = lazy(() => import("./LetterElement").then((m) => ({ default: m.LetterView })));
const BlockersView = lazy(() => import("./BlockersElement").then((m) => ({ default: m.BlockersView })));
const ActionsView = lazy(() => import("./ActionsElement").then((m) => ({ default: m.ActionsView })));  // 261 (B1e)
const DataTableView = lazy(() => import("./DataTableElement").then((m) => ({ default: m.DataTableView })));  // 261 (B1f)
const FormView = lazy(() => import("./FormElement").then((m) => ({ default: m.FormView })));  // 261 (B1g)
/** An element whose page loads only when a case shows it (its module imported on first render). */
export const lazily = (C: (p: ElementProps) => ReactNode) =>
  (p: ElementProps) => <Suspense fallback={<p className="muted">{t("Loading…")}</p>}><C {...p} /></Suspense>;
/** 261 (B1b): elements shown as rows of one table, whose page loads only when a case shows them. */
const lazilyRows = (C: (p: { rows: ElementProps[] }) => ReactNode) =>
  (rows: ElementProps[]) => <Suspense fallback={<p className="muted">{t("Loading…")}</p>}><C rows={rows} /></Suspense>;
const subWork = lazilyRows(SubWorkTable);

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
  actions: { render: lazily(ActionsView) },  // 261 (B1e): a step's actions, each that may spend with its cost cap
  data_table: { render: lazily(DataTableView) },  // 261 (B1f): a registered dataset the case gives the scope of
  form: { render: lazily(FormView) },  // 261 (B1g): a step's action's form, as its capability describes it
  partner_link: { render: lazily(PartnerLink) },  // 231 (B1)
  started_cases: { render: lazily(StartedCases) },  // 231 (C1c)
  sub_case: { render: (p) => subWork([p]), rows: subWork,  // 231 (U2c); 261 (B1b): a multi-step case's sub-work table
    status: (p) => subCaseStatus(p.element.data as SubCaseData | null)?.text ?? null },
  package_work: { render: lazily(PackageWork), status: (p) => packageWorkLine(p.element.data as PackageWorkView | null) },  // 231 (C3b3)
  cost: { render: lazily(CostView), status: (p) => { const usd = costTotal(p); return usd === null ? null : `${moneyText(usd)} USD`; } },
  field_review: { render: lazily(FieldReview), status: (p) => fieldReviewLine(p.element.data as FieldReviewData | null) },  // D-f4
  document_facts: { render: lazily(DocumentFacts) },  // D-f4
  lookup: { render: lazily(LookupView) },  // D-f4
  evaluation: { render: lazily(EvaluationView), status: (p) => verdictStatus(p.element.data as EvaluationData | null)?.text ?? null },  // D-f5
  calculation: { render: lazily(CalculationView), status: (p) => calculationStatus(p.element.data as CalculationData | null)?.text ?? null },
  missing_info: { render: lazily(MissingInfoView), status: (p) => missingStatus(p.element.data as MissingInfoData | null)?.text ?? null },
  decision: { render: lazily(DecisionView), status: (p) => decisionStatus(p.element.data as DecisionData | null)?.text ?? null },  // D-f6
  document_view: { render: lazily(DocumentView), status: (p) => documentStatus(p.element.data as DocumentViewData | null)?.text ?? null },  // D-f7
  letter: { render: lazily(LetterView), status: (p) => letterStatus(p.element.data as LetterData | null)?.text ?? null },  // D-f8
  blockers: { render: lazily(BlockersView), status: (p) => blockersStatus(p.element.data as BlockersData | null)?.text ?? null },  // D-f9
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
