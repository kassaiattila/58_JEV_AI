// 231 (plan stage A, A7e): the status lines of the general elements of a case's page (a send step's, a reply step's,
// the cost's), small enough to load with the page; the elements themselves load when a case shows one.
import type { CaseCost, FieldReviewData, HandoverData, ReplyData } from "../api";
import { t } from "../i18n";
import { when } from "../labels";
import type { ElementProps } from "./registry";

/** D-f4: a field review's state as one mark: frozen with its version, disagreements to settle, to freeze, or waiting. */
export function fieldReviewStatus(d: FieldReviewData | null): { mark: string; text: string } | null {
  if (!d) return null;
  if (d.frozen) return { mark: "s-done", text: t("Frozen: version {{n}}", { n: d.frozen.version }) };
  if (d.conflicts) return { mark: "s-review", text: t("{{n}} to settle", { n: d.conflicts }) };
  return d.waits ? { mark: "s-review", text: t("To freeze") } : { mark: "s-waiting", text: t("Waits for the facts") };
}
export const fieldReviewLine = (d: FieldReviewData | null) => fieldReviewStatus(d)?.text ?? null;

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
