// 145 (backlog F-reconciliation E3b; DECISIONS 131, 132, 145): the reconciliation package's Result stage - the statement
// (every invoice and line with its result), what blocks or only warns its approval, accepting a command-line source, the
// download as an Excel workbook, the approval as a version that locks the lines, reopening with a reason, and the
// earlier versions. The service computes and checks everything (jav/domains/finance/reconcile_statement.py); this page shows it.
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../../api";
import type { ReconcileStatement, ReconcileStatementCurrent, ReconcileWorkspace } from "../api";
import { ApprovalPanel, EarlierVersions } from "../../../components/ApprovalPanel";
import { BlockerList } from "../../../components/BlockerList";
import { ConfirmButton } from "../../../components/ConfirmButton";
import { Icon } from "../../../components/Icon";
import { TemplateChoice } from "../../../components/TemplateChoice";
import { errorText, useAction, useLoad } from "../../../hooks";
import { t, useLocale } from "../../../i18n";
import { blockerItems, INVOICE_RESULT, LINE_RESULT, MARK, EXCLUDED, warningText } from "./labels";
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
      {shown ? <StatementTables statement={shown} buyers={buyers(ws)} /> : approved.error ? <p className="notice error" role="alert">{approved.error.message}</p>
        : <p className="muted">{t("Loading…")}</p>}

      <EarlierVersions versions={current.approval.versions}
        action={(v) => <a href={api.reconcileStatementXlsxUrl(wpId, v.version)} download>{t("Download (Excel)")}</a>} />
    </div>
  );
}

const REASON = (code: string | null): string => (code ? MARK[code] ?? EXCLUDED[code] ?? code : "");

/** U1 (the walkthrough): an own party's outgoing invoice is shown by its buyer, as the pairing shows it (148); the
 *  statement itself keeps its supplier. */
const buyers = (ws: ReconcileWorkspace): Record<string, string> =>
  Object.fromEntries((ws.invoices ?? []).filter((i) => i.outgoing && i.partner_name).map((i) => [i.id, i.partner_name as string]));

/** The statement's two tables: the invoices with their results and payments, the lines with their results. */
function StatementTables({ statement: st, buyers: buyerOf = {} }: { statement: ReconcileStatement; buyers?: Record<string, string> }) {
  useLocale();
  const [lineFilter, setLineFilter] = useState<string>("");
  const lines = useMemo(() => st.lines.filter((ln) => !lineFilter || ln.result === lineFilter), [st.lines, lineFilter]);
  return (
    <>
      <section className="card" aria-label={t("Invoices")}>
        <h2>{t("Invoices")}</h2>
        <p className="rc-counts">
          {Object.entries(st.counts.invoices).map(([k, n]) => <span key={k} className={`rc-state s-${k}`}>{INVOICE_RESULT[k as keyof typeof INVOICE_RESULT] ?? k}: {n}</span>)}
        </p>
        <div className="dt-scroll">
          <table className="table compact">
            <thead><tr>
              <th>{t("Invoice number")}</th><th>{t("Partner")}</th><th>{t("Due date")}</th><th className="num">{t("Amount")}</th>
              <th>{t("Result")}</th><th className="num">{t("Left")}</th><th>{t("Paid on")}</th><th className="num">{t("Days late")}</th>
            </tr></thead>
            <tbody>
              {st.invoices.map((i) => (
                <tr key={i.id}>
                  <td>{i.number ?? "–"}</td>
                  <td>{buyerOf[i.id] ? <>{buyerOf[i.id]} <span className="muted small">· {t("buyer of an outgoing invoice")}</span></>
                    : i.supplier_name ?? "–"}{i.other_party ? <span className="muted small"> · {t("another party's: {{name}}", { name: i.other_party })}</span> : null}</td>
                  <td>{i.due_date ?? "–"}</td>
                  <td className="num">{show(i.amount, i.currency)}</td>
                  <td>{INVOICE_RESULT[i.result] ?? i.result}</td>
                  <td className="num">{i.result === "paid" ? "" : show(i.rest, i.currency)}</td>
                  <td>{i.paid_on ?? ""}</td>
                  <td className="num">{i.days_from_due && i.days_from_due > 0 ? i.days_from_due : i.overdue_days ? t("{{n}} overdue", { n: i.overdue_days }) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card" aria-label={t("Statement lines")}>
        <div className="card-head">
          <h2>{t("Statement lines")}</h2>
          <label className="small">{t("Show")}{" "}
            <select value={lineFilter} onChange={(e) => setLineFilter(e.target.value)}>
              <option value="">{t("every line")}</option>
              {Object.entries(st.counts.lines).map(([k, n]) => <option key={k} value={k}>{LINE_RESULT[k as keyof typeof LINE_RESULT] ?? k} ({n})</option>)}
            </select>
          </label>
        </div>
        <div className="dt-scroll">
          <table className="table compact">
            <thead><tr>
              <th>{t("Booking date")}</th><th>{t("Partner")}</th><th>{t("Remittance info")}</th><th className="num">{t("Amount")}</th>
              <th>{t("Result")}</th><th>{t("Reason or invoice")}</th>
            </tr></thead>
            <tbody>
              {lines.map((ln) => (
                <tr key={ln.id}>
                  <td>{ln.booking_date ?? "–"}</td>
                  <td>{ln.counterparty_name ?? "–"}</td>
                  <td className="small">{ln.memo ?? ln.description ?? ""}</td>
                  <td className="num">{ln.direction === "credit" ? "+" : "−"}{show(ln.amount, ln.currency)}</td>
                  <td>{LINE_RESULT[ln.result] ?? ln.result}</td>
                  <td className="small">{ln.pays.length ? ln.pays.map((p) => p.number ?? p.supplier_name ?? "").join(", ") : REASON(ln.reason)}{ln.note ? ` · ${ln.note}` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

