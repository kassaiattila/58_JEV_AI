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

/** The CSS tone of a status chip. */
export function statusTone(status: WorkflowStepStatus): "ok" | "warn" | "error" | "muted" | "active" {
  if (status === "approved" || status === "nothing_new") return "ok";
  if (status === "failed" || status === "missing") return "error";
  if (status === "needs_budget" || status === "review" || status === "approve" || status === "attention") return "warn";
  if (status === "waiting") return "muted";
  return "active";
}

export const PROVIDER: Record<string, string> = { jev: "JEV", openai: "OpenAI", azure_di: "Azure" };

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
