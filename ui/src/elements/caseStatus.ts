// 231 (plan stage A, A7e): the status lines of the general elements of a case's page (a send step's, a reply step's,
// the cost's), small enough to load with the page; the elements themselves load when a case shows one.
import type { CalculationData, CaseCost, DecisionData, DocumentViewData, EvaluationData, FieldReviewData, HandoverData, LetterData,
  MissingInfoData, ReplyData } from "../api";
import { t } from "../i18n";
import { numText, tmap, when } from "../labels";
import type { ElementProps } from "./registry";

/** D-f4: a field review's state as one mark: frozen with its version, disagreements to settle, to freeze, or waiting. */
export function fieldReviewStatus(d: FieldReviewData | null): { mark: string; text: string } | null {
  if (!d) return null;
  if (d.frozen) return { mark: "s-done", text: t("Frozen: version {{n}}", { n: d.frozen.version }) };
  if (d.conflicts) return { mark: "s-review", text: t("{{n}} to settle", { n: d.conflicts }) };
  return d.waits ? { mark: "s-review", text: t("To freeze") } : { mark: "s-waiting", text: t("Waits for the facts") };
}
export const fieldReviewLine = (d: FieldReviewData | null) => fieldReviewStatus(d)?.text ?? null;

/** D-f5: a rule evaluation's verdict as one mark: allowed, to refer, refused, not known, or blocked. */
export const VERDICT = tmap({ allow: "Allowed", refer: "To refer: a person decides", refuse: "Refused", unknown: "Not known: facts are missing" });
const VERDICT_MARK: Record<string, string> = { allow: "s-done", refer: "s-review", refuse: "s-failed", unknown: "s-warn" };
export function verdictStatus(d: EvaluationData | null): { mark: string; text: string } | null {
  if (!d?.latest) return null;
  if (d.latest.blockers.length) return { mark: "s-failed", text: t("Blocked") };
  const v = d.latest.verdict;
  return v ? { mark: VERDICT_MARK[v] ?? "s-waiting", text: VERDICT[v] ?? v } : { mark: "s-waiting", text: t("No verdict") };
}

/** D-f6: a decision's state as one mark: decided with its choice, out of date, returned, to decide, or waiting. */
export function decisionStatus(d: DecisionData | null): { mark: string; text: string } | null {
  if (!d) return null;
  if (d.decided) return { mark: "s-done", text: t(d.decided.title) };
  if (d.approval.state === "outdated") return { mark: "s-warn", text: t("Out of date") };
  if (d.approval.state === "returned") return { mark: "s-review", text: t("Returned") };
  return d.waits ? { mark: "s-review", text: t("To decide") } : { mark: "s-waiting", text: t("Waits for what it decides on") };
}

/** D-f7: a printed document's state as one mark: the version it printed, not printed, or waiting for its version. */
export function documentStatus(d: DocumentViewData | null): { mark: string; text: string } | null {
  if (!d) return null;
  if (d.file) return { mark: "s-done", text: t("Version {{n}}", { n: d.version ?? "–" }) };
  if (d.state === "failed") return { mark: "s-failed", text: t("Not printed") };
  return { mark: "s-waiting", text: t("Waits for the approval") };
}

/** D-f8: a letter's state as one mark: accepted, out of date, returned, to accept, or waiting for its document. */
export function letterStatus(d: LetterData | null): { mark: string; text: string } | null {
  if (!d) return null;
  if (d.accepted) return { mark: "s-done", text: t("Accepted") };
  if (d.approval.state === "outdated") return { mark: "s-warn", text: t("Out of date") };
  if (d.approval.state === "returned") return { mark: "s-review", text: t("Returned") };
  return d.waits ? { mark: "s-review", text: t("To accept") } : { mark: "s-waiting", text: t("Waits for the document") };
}

/** D-f5: a premium's state as one mark: its total, or blocked. */
export function calculationStatus(d: CalculationData | null): { mark: string; text: string } | null {
  if (!d?.latest) return null;
  if (d.latest.blockers.length || !d.latest.total) return { mark: "s-failed", text: t("Blocked") };
  return { mark: "s-done", text: `${numText(d.latest.total.amount, 2)} ${d.latest.total.currency}` };
}

/** D-f5: the wait for missing facts as one mark. */
export function missingStatus(d: MissingInfoData | null): { mark: string; text: string } | null {
  if (!d) return null;
  const task = d.task;
  if (task?.status === "open") return { mark: "s-review", text: t("{{n}} missing", { n: d.missing.length }) };
  if (task?.status === "expired") return { mark: "s-failed", text: t("The deadline passed") };
  if (task?.status === "decided") return { mark: "s-failed", text: t("They will not come") };
  if (d.state === "done") return { mark: "s-done", text: task ? t("They arrived") : t("Nothing is missing") };
  return { mark: "s-waiting", text: t("Waits for the rules") };
}

/** The send step's state as one mark: ready to send, sent, failed, unknown, or waiting for the steps before it. */
export function handoverStatus(p: ElementProps): { mark: string; text: string } | null {
  const d = p.element.data as HandoverData | null;
  const step = p.element.step ? p.page.steps[p.element.step] : undefined;
  if (!d || !step) return null;
  const last = d.attempts[d.attempts.length - 1];
  if (step.state === "failed") return { mark: "s-failed", text: t("The send failed") };
  if (step.awaiting_start) return { mark: "s-startable", text: t("Ready to send") };
  if (last?.status === "uncertain") return { mark: "s-warn", text: t("Arrival unknown") };
  if (step.state === "done") return { mark: "s-done", text: t("Sent {{when}}", { when: when(last?.updated_at) }) };
  if (step.state === "running") return { mark: "s-running", text: t("Being sent") };
  return { mark: "s-waiting", text: t("Waits for the steps before it") };
}

/** The reply step's state as one mark: waiting (since when), a follow-up to do, the reply recorded. */
export function replyStatus(p: ElementProps): { mark: string; text: string } | null {
  const d = p.element.data as ReplyData | null;
  if (!d) return null;
  if (d.reply === "replied") return { mark: "s-done", text: t("A reply arrived") };
  if (d.reply === "not_needed") return { mark: "s-done", text: t("No reply is needed") };
  if (d.follow_up === "open") return { mark: "s-review", text: t("Follow up the reply") };
  if (d.state === "running") return { mark: "s-waiting", text: t("Waiting since {{when}}", { when: when(d.since) }) };
  return { mark: "s-waiting", text: t("Waits for the send") };
}

export const costTotal = (p: ElementProps) => (p.element.data as CaseCost | null)?.total_usd ?? null;
