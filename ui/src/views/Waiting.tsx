// 216 (plan G-process-core P2e): "Waiting for me" — what waits for the person chosen in "Who is working?": their open
// human tasks and anyone's (a task the owner's rule gave to nobody), each with where it is done. By default only live
// work (a live run's to-dos and every approval); the switch shows the to-dos of trial runs and measurements too (the
// owner's decisions of 2026-10-23). The rows come from the `waiting` dataset (jav/app/waiting.py).
import type { ReactNode } from "react";
import type { DsColumn, DsRow } from "../api";
import { DataTable, linkOf } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { useActor } from "../hooks";
import { t, useLocale } from "../i18n";
import { reasonText } from "../labels";
import { go } from "../route";

/** The task's "what" cell: a to-do names its item (the table shows it as it is, linked); every other kind's text is the
 *  interface's own, translated and linked to where the task is done. */
export function waitingWhat(col: DsColumn, row: DsRow): ReactNode {
  if (row.kind === "review" || typeof row.what !== "string" || !row.what) return undefined;
  const href = linkOf(col, row);
  return href ? <a href={href}>{t(row.what)}</a> : t(row.what);
}

export function Waiting({ all }: { all: boolean }) {
  useLocale();
  const actor = useActor();
  const title = t("Waiting for me");
  if (!actor) {
    return <PageHeader title={title} summary={t("Choose your name in the “Who is working?” field above; here you see what waits for you.")} />;
  }
  return (
    <>
      <PageHeader title={title}
        summary={t("What waits for {{name}}: the to-dos to check, the runs and reconciliations to approve, the budgets to decide, and the ones no one is assigned to.", { name: actor })} />
      {/* 263 (F3): the list keeps its state; its filter stands in its toolbar */}
      <DataTable dataset="waiting" scope={all ? { actor, all: "true" } : { actor }} label={title} storageId="waiting" persist="waiting"
        toolbar={
          <label className="check small">
            <input type="checkbox" checked={all} onChange={(e) => go({ view: "waiting", all: e.target.checked || undefined })} />
            {t("Trial runs and measurements too")}
          </label>
        }
        emptyText={all ? t("Nothing waits for you.") : t("No live work waits for you.")}
        cell={(col, row) => (col.key === "what" ? waitingWhat(col, row)
          : col.key === "reason" && typeof row.reason === "string" ? reasonText(row.reason) : undefined)} />
    </>
  );
}
