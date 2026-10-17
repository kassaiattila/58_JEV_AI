// 146: the words of the workflows' screens: a step's status, what the chain is waiting for, a step's source.
import type { WorkflowBudget, WorkflowStep, WorkflowStepStatus } from "../../api";
import { t } from "../../i18n";
import { tmap } from "../../labels";

export const STEP_STATUS: Record<WorkflowStepStatus, string> = tmap({
  waiting: "waits for its earlier steps", ready: "ready to start", starting: "starting…",
  pulling: "downloading the emails…", needs_budget: "waits for a budget", nothing_new: "nothing new: done",
  failed: "did not start", running: "running", review: "to-dos in its package", approve: "awaiting approval",
  approved: "approved", pairing: "pairing in its package", attention: "needs a person in its package",
  missing: "its package is missing",
}) as Record<WorkflowStepStatus, string>;

/** 157: a step's state mark (`.status .s-<mark>`): done green, a person's turn orange (a budget, to-dos, an approval,
 * pairing), failed red, running blue, starting a blue ring; ready and waiting are neutral. Never the action colour. */
export function stepMark(status: WorkflowStepStatus): "done" | "review" | "failed" | "running" | "queued" | "waiting" | "startable" {
  if (status === "approved" || status === "nothing_new") return "done";
  if (status === "failed" || status === "missing") return "failed";
  if (["needs_budget", "review", "approve", "attention", "pairing"].includes(status)) return "review";
  if (status === "running" || status === "pulling") return "running";
  if (status === "starting") return "queued";
  if (status === "waiting") return "waiting";
  return "startable";
}

export const PROVIDER: Record<string, string> = { jev: "JEV", openai: "OpenAI", azure_di: "Azure" };

/** 157: what a step's run may spend at most: the sum of its services' budgets. */
export function budgetSum(budget: WorkflowBudget | undefined): number {
  return Object.values(budget ?? {}).reduce((s, v) => s + (Number(v) || 0), 0);
}

/** 167 (review 160 U-8): an amount in USD rounded up to the cent, as text. The float noise of 0.07 × 100
 *  (7.000000000000001) used to round it up to 0.08; the micro-cents are rounded off first. */
export function centsUp(value: string | number): string {
  return (Math.ceil(Math.round(Number(value) * 1e6) / 1e4) / 100).toFixed(2);
}

/** 167 (review 160 U-9): a new estimate's proposal over a step's budget. A value the person typed in this form stays; a
 *  value from an earlier estimate (or from the repeated workflow) is replaced, so a re-estimate does raise it. */
export function mergeProposal(current: WorkflowBudget, proposed: WorkflowBudget, typed: Record<string, boolean>): WorkflowBudget {
  const out: WorkflowBudget = { ...current };
  for (const [p, v] of Object.entries(proposed)) if (!typed[p]) out[p as keyof WorkflowBudget] = v;
  return out;
}

export function budgetText(budget: WorkflowBudget | undefined): string {
  const parts = Object.entries(budget ?? {}).filter(([, v]) => v && Number(v) > 0).map(([p, v]) => `${PROVIDER[p] ?? p} ${v} USD`);
  return parts.length ? parts.join(" + ") : t("free only");
}

/** 147: a step's note from the service; the notes with numbers are translated by their pattern. */
const NOTES: [RegExp, string][] = [
  [/^no new documents: (\d+) already processed$/, "no new documents: {{a}} already processed by a live run"],
  [/^no new statement: (\d+) statement\(s\) and (\d+) PDF\(s\) are in the store or outside the period$/,
    "no new statement: {{a}} statement(s) and {{b}} PDF(s) are in the store or outside the period"],
];

export function stepNote(note: string): string {
  for (const [pattern, text] of NOTES) {
    const m = pattern.exec(note);
    if (m) return t(text, { a: m[1], b: m[2] ?? "" });
  }
  return t(note);
}

/** A step's source in a few words (147: and whether only the new documents are taken). */
export function sourceText(step: Pick<WorkflowStep, "source">): string {
  const s = step.source;
  const text = sourceWords(s);
  return s.only_new ? `${text} · ${t("only the documents no live run has processed yet")}` : text;
}

function sourceWords(s: WorkflowStep["source"]): string {
  switch (s.kind) {
    case "folder": return s.recursive ? t("folder {{folder}} with its subfolders", { folder: s.folder ?? "" }) : t("folder {{folder}}", { folder: s.folder ?? "" });
    case "files": return t("{{n}} given file(s), the first: {{first}}", { n: s.count ?? 0, first: s.first ?? "" });
    case "mailbox": return t("mailbox {{accounts}}", { accounts: (s.accounts ?? []).join(", ") });
    case "package": return t("an existing work package");
    default: return t("no files: made from the earlier steps");
  }
}
