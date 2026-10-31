// 145 (backlog F-reconciliation E3b; DECISIONS 131, 132, 145): the reconciliation package's Result stage - the statement
// (every invoice and line with its result), what blocks or only warns its approval, accepting a command-line source, the
// download as an Excel workbook, the approval as a version that locks the lines, reopening with a reason, and the
// earlier versions. The service computes and checks everything (jav/domains/finance/reconcile_statement.py); this page shows it.
import { useEffect, useState } from "react";
import { api, ApiError, type DsRow } from "../../../api";
import type { ReconcileStatement, ReconcileStatementCurrent, ReconcileWorkspace } from "../api";
import { ApprovalPanel, EarlierVersions } from "../../../components/ApprovalPanel";
import { BlockerList } from "../../../components/BlockerList";
import { ConfirmButton } from "../../../components/ConfirmButton";
import { DataTable } from "../../../components/DataTable";
import { Icon } from "../../../components/Icon";
import { TemplateChoice } from "../../../components/TemplateChoice";
import { errorText, useAction, useLoad } from "../../../hooks";
import { t, useLocale } from "../../../i18n";
import { blockerItems, MARK, EXCLUDED, warningText } from "./labels";
import { show } from "./money";

export function ReconcileResult({ ws, archived, onChanged, reloadWorkspace }: {
  ws: ReconcileWorkspace; archived: boolean; onChanged: () => void; reloadWorkspace: () => void;
}) {
  useLocale();
  const wpId = ws.workpackage_id;
  // the statement follows the workspace: a decision, an approval or a reopening reloads it (the shown one stays until
  // the new one arrives)
  const key = `reconcile-statement:${wpId}:${JSON.stringify(ws.decision_state ?? null)}:${ws.blockers.length}`;
  const loaded = useLoad(key, () => api.reconcileStatement(wpId));
  const [current, setCurrent] = useState<ReconcileStatementCurrent | null>(null);
  useEffect(() => { if (loaded.data) setCurrent(loaded.data); }, [loaded.data]);
  const active = current?.approval.active ?? null;
  const approved = useLoad(active ? `reconcile-version:${wpId}:${active.version}` : null,
    () => api.reconcileStatementVersion(wpId, active!.version));
  const { busy, error, notice, run } = useAction();

  const act = (fn: () => Promise<ReconcileStatementCurrent>, done: string) => run(fn, {
    then: (next) => {
      setCurrent(next);
      reloadWorkspace(); // the locks and the next step follow the approval
      onChanged();
    },
    done,
    failed: (e) => {
      if (!(e instanceof ApiError && e.status === 409 && (e.code === "revision_conflict" || e.code === "not_ready"))) return errorText(e);
      loaded.reload();
      return e.code === "revision_conflict" ? t("The reconciliation changed since it was shown; it has been reloaded. Check it and try again.")
        : t("The reconciliation cannot be approved yet: see what blocks it.");
    },
  });

  if (!current) {
    return loaded.error ? <p className="notice error" role="alert">{loaded.error.message}</p> : <p className="muted">{t("Loading…")}</p>;
  }
  const shown: ReconcileStatement | null = active ? (approved.data?.statement ?? null) : current.statement;
  const accept = current.blockers.filter((b) => b.code === "source_no_run").map((b) => b.doc_id);
  // 227 (DECISIONS 224): only a change of content warns; a change of the rules alone is a note. An older service
  // without the comparison compares the fingerprints, as before.
  const since = current.since_approval;
  const changed = active !== null && (since ? since.content_changed : active.fingerprint !== current.fingerprint);
  const rulesOnly = active !== null && !changed && Boolean(since?.rules_changed);

  return (
    <div className="rc-stack">
      {/* 192: the approval is the shared element of a logic pack's own versions (components/ApprovalPanel.tsx) */}
      <ApprovalPanel approval={current.approval} archived={archived} busy={busy}
        tools={<>
          {/* 179: the template of the draft's download and of the approval's stored file; an approved version's file is
              stored, so it is chosen again only after a reopening */}
          {active ? null : <TemplateChoice wpId={wpId} output="reconcile_statement" />}
          <a className="secondary dl-btn small-btn" href={api.reconcileStatementXlsxUrl(wpId, active?.version)} download><Icon name="download" />
            {active ? t("Download version {{n}} (Excel)", { n: active.version }) : t("Download the draft (Excel)")}
          </a>
        </>}
        lockedText={t("The decisions on its lines are locked in every package. To change one, reopen the approval with a reason; this version stays as an earlier one.")}
        changedText={changed ? t("The data has changed since the approval (for example a document was processed again). The approved version stays as it was; reopen it to approve the current state.") : null}
        noteText={rulesOnly ? t("The reconciliation's rules or the program that applies them changed since the approval; its invoices, lines and results are the same, so the approved version holds.") : null}
        pendingText={t("Not approved yet. The approval records the summary below as an unchangeable version and locks the decisions on its lines. Open lines do not block it; the summary lists them.")}
        blockers={current.blockers.length ? <BlockerList small items={blockerItems(current.blockers)} /> : null}
        clearing={accept.length && !archived ? (
          <div className="rc-accept">
            <p className="muted small">{t("A document processed on the command line belongs to no run. You can accept its current result as a source; your name and the time are recorded.")}</p>
            <ConfirmButton className="secondary" disabled={busy}
              onConfirm={() => void act(() => api.reconcileAcceptSources(wpId, accept), t("The documents have been accepted as sources."))}>
              {t("Accept {{n}} command-line documents as sources", { n: accept.length })}
            </ConfirmButton>
          </div>
        ) : null}
        approveLabel={current.statement.counts.open_lines
          ? t("Approve the reconciliation ({{n}} open lines listed)", { n: current.statement.counts.open_lines })
          : t("Approve the reconciliation")}
        onApprove={() => void act(() => api.reconcileApprove(wpId, current.fingerprint), t("The reconciliation has been approved."))}
        onReopen={(note) => act(() => api.reconcileReopen(wpId, note), t("The approval has been reopened; the decisions can be changed again."))}
        error={error} notice={notice}>
        {current.warnings.length ? (
          <>
            <h3>{t("Warnings")}</h3>
            <ul className="plain">
              {current.warnings.map((w) => <li key={`${w.code}:${w.doc_id ?? ""}:${w.account ?? ""}:${w.month ?? ""}`} className="small warn">{warningText(w)}</li>)}
            </ul>
          </>
        ) : null}
      </ApprovalPanel>

      {/* 167 (review 160 U-11): the approved version that failed to load says so */}
      {shown ? <StatementTables wpId={wpId} version={active?.version} stamp={`${active?.version ?? "now"}:${current.fingerprint}`} />
        : approved.error ? <p className="notice error" role="alert">{approved.error.message}</p>
        : <p className="muted">{t("Loading…")}</p>}

      <EarlierVersions versions={current.approval.versions}
        action={(v) => <a href={api.reconcileStatementXlsxUrl(wpId, v.version)} download>{t("Download (Excel)")}</a>} />
    </div>
  );
}

const REASON = (code: string | null): string => (code ? MARK[code] ?? EXCLUDED[code] ?? code : "");

/** 263 (plan E, F3; the owner's decision of 2026-10-30: every list the one list): the statement's two tables - the
 *  invoices with their results and payments, the lines with their results - are the one list (search, sort, filters,
 *  grouped by their result at first), read by the service from the statement as it stands now or from its approved
 *  `version`; an own party's outgoing invoice is shown by its buyer (148). */
function StatementTables({ wpId, version, stamp }: { wpId: string; version?: number; stamp: string }) {
  useLocale();
  const scope = { workpackage_id: wpId, ...(version ? { version: String(version) } : {}) };
  const money = (row: DsRow, key: string, sign = "") => (row[key] == null ? "" : `${sign}${show(String(row[key]), String(row.currency ?? ""))}`);
  return (
    <>
      <section className="card wide" aria-label={t("Invoices")}>
        <h2>{t("Invoices")}</h2>
        <DataTable key={`inv:${stamp}`} dataset="reconcile_statement_invoices" scope={scope} label={t("Invoices")}
          persist={`rc-invoices:${wpId}`} defaultGroup="result" storageId="rc-invoices"
          cell={(col, row) => {
            if (col.key === "amount" || col.key === "rest") return money(row, col.key);
            if (col.key === "counterparty" && row.buyer) return <>{String(row.counterparty ?? "–")} <span className="muted small">· {t("buyer of an outgoing invoice")}</span></>;
            if (col.key === "counterparty" && row.other_party) return <>{String(row.counterparty ?? "–")} <span className="muted small"> · {t("another party's: {{name}}", { name: String(row.other_party) })}</span></>;
            if (col.key === "days_late" && !row.days_late && row.overdue_days) return t("{{n}} overdue", { n: Number(row.overdue_days) });
            return undefined;
          }} />
      </section>
      <section className="card wide" aria-label={t("Statement lines")}>
        <h2>{t("Statement lines")}</h2>
        <DataTable key={`lines:${stamp}`} dataset="reconcile_statement_lines" scope={scope} label={t("Statement lines")}
          persist={`rc-lines:${wpId}`} defaultGroup="result" storageId="rc-lines"
          cell={(col, row) => {
            if (col.key === "amount") return money(row, "amount", row.direction === "credit" ? "+" : "−");
            if (col.key === "pays" && !row.pays) return `${REASON(row.reason as string | null)}${row.note ? ` · ${String(row.note)}` : ""}` || "–";
            return undefined;
          }} />
      </section>
    </>
  );
}

