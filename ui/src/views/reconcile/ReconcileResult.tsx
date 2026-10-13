// 145 (backlog F-reconciliation E3b; DECISIONS 131, 132, 145): the reconciliation package's Result stage - the statement
// (every invoice and line with its result), what blocks or only warns its approval, accepting a command-line source, the
// download as an Excel workbook, the approval as a version that locks the lines, reopening with a reason, and the
// earlier versions. The service computes and checks everything (jav/reconcile_statement.py); this page shows it.
import { useEffect, useMemo, useState } from "react";
import {
  api, ApiError, type ReconcileStatement, type ReconcileStatementCurrent, type ReconcileVersionMeta, type ReconcileWorkspace,
} from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { Icon } from "../../components/Icon";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";
import { INVOICE_RESULT, LINE_RESULT, MARK, EXCLUDED, warningText } from "./labels";
import { BlockerList } from "./BlockerList";
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [note, setNote] = useState("");

  async function act(fn: () => Promise<ReconcileStatementCurrent>, done: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setCurrent(await fn());
      setNotice(done);
      setNote("");
      reloadWorkspace(); // the locks and the next step follow the approval
      onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.code === "revision_conflict") {
        setError(t("The reconciliation changed since it was shown; it has been reloaded. Check it and try again."));
        loaded.reload();
      } else if (e instanceof ApiError && e.status === 409 && e.code === "not_ready") {
        setError(t("The reconciliation cannot be approved yet: see what blocks it."));
        loaded.reload();
      } else setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!current) {
    return loaded.error ? <p className="notice error" role="alert">{loaded.error.message}</p> : <p className="muted">{t("Loading…")}</p>;
  }
  const shown: ReconcileStatement | null = active ? (approved.data?.statement ?? null) : current.statement;
  const accept = current.blockers.filter((b) => b.code === "source_no_run").map((b) => b.doc_id);
  const changed = active !== null && active.fingerprint !== current.fingerprint;
  const earlier = current.approval.versions.filter((v) => v.reopened_at);

  return (
    <div className="rc-stack">
      <section className="card" aria-label={t("Approval")}>
        <div className="card-head">
          <h2>{t("Approval")}</h2>
          <a className="secondary dl-btn small-btn" href={api.reconcileStatementXlsxUrl(wpId, active?.version)} download><Icon name="download" />
            {active ? t("Download version {{n}} (Excel)", { n: active.version }) : t("Download the draft (Excel)")}
          </a>
        </div>
        {active ? (
          <>
            <p className="notice ok-box">
              {t("Approved: version {{n}}, by {{who}}, {{when}}.", { n: active.version, who: active.approved_by, when: when(active.approved_at) })}
            </p>
            <p className="muted small">{t("The decisions on its lines are locked in every package. To change one, reopen the approval with a reason; this version stays as an earlier one.")}</p>
            {changed ? <p className="notice warn small" role="status">{t("The data has changed since the approval (for example a document was processed again). The approved version stays as it was; reopen it to approve the current state.")}</p> : null}
            {archived ? null : (
              <div className="rc-reopen">
                <label className="block">{t("Reason for reopening")}
                  <input type="text" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
                </label>
                <ConfirmButton className="secondary" disabled={busy || !note.trim()}
                  onConfirm={() => void act(() => api.reconcileReopen(wpId, note.trim()), t("The approval has been reopened; the decisions can be changed again."))}>
                  {t("Reopen")}
                </ConfirmButton>
              </div>
            )}
          </>
        ) : (
          <>
            <p className="muted small">{t("Not approved yet. The approval records the summary below as an unchangeable version and locks the decisions on its lines. Open lines do not block it; the summary lists them.")}</p>
            {current.blockers.length ? (
              <>
                <h3>{t("What blocks the approval")}</h3>
                <BlockerList blockers={current.blockers} />
                {accept.length && !archived ? (
                  <div className="rc-accept">
                    <p className="muted small">{t("A document processed on the command line belongs to no run. You can accept its current result as a source; your name and the time are recorded.")}</p>
                    <ConfirmButton className="secondary" disabled={busy}
                      onConfirm={() => void act(() => api.reconcileAcceptSources(wpId, accept), t("The documents have been accepted as sources."))}>
                      {t("Accept {{n}} command-line documents as sources", { n: accept.length })}
                    </ConfirmButton>
                  </div>
                ) : null}
              </>
            ) : <p className="small ok">{t("Nothing blocks the approval.")}</p>}
            {archived ? null : (
              <ConfirmButton className="primary" disabled={busy || current.blockers.length > 0}
                onConfirm={() => void act(() => api.reconcileApprove(wpId, current.fingerprint), t("The reconciliation has been approved."))}>
                {current.statement.counts.open_lines
                  ? t("Approve the reconciliation ({{n}} open lines listed)", { n: current.statement.counts.open_lines })
                  : t("Approve the reconciliation")}
              </ConfirmButton>
            )}
          </>
        )}
        {current.warnings.length ? (
          <>
            <h3>{t("Warnings")}</h3>
            <ul className="plain">
              {current.warnings.map((w) => <li key={`${w.code}:${w.doc_id ?? ""}:${w.account ?? ""}:${w.month ?? ""}`} className="small warn">{warningText(w)}</li>)}
            </ul>
          </>
        ) : null}
        {error ? <p className="notice error" role="alert">{error}</p> : null}
        {notice ? <p className="small ok" role="status">{notice}</p> : null}
      </section>

      {shown ? <StatementTables statement={shown} /> : <p className="muted">{t("Loading…")}</p>}

      {earlier.length ? <EarlierVersions wpId={wpId} versions={earlier} /> : null}
    </div>
  );
}

const REASON = (code: string | null): string => (code ? MARK[code] ?? EXCLUDED[code] ?? code : "");

/** The statement's two tables: the invoices with their results and payments, the lines with their results. */
function StatementTables({ statement: st }: { statement: ReconcileStatement }) {
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
              <th>{t("Invoice number")}</th><th>{t("Supplier")}</th><th>{t("Due date")}</th><th className="num">{t("Amount")}</th>
              <th>{t("Result")}</th><th className="num">{t("Left")}</th><th>{t("Paid on")}</th><th className="num">{t("Days late")}</th>
            </tr></thead>
            <tbody>
              {st.invoices.map((i) => (
                <tr key={i.id}>
                  <td>{i.number ?? "–"}</td>
                  <td>{i.supplier_name ?? "–"}{i.other_party ? <span className="muted small"> · {t("another party's: {{name}}", { name: i.other_party })}</span> : null}</td>
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

/** The reopened versions, each downloadable as it was approved. */
function EarlierVersions({ wpId, versions }: { wpId: string; versions: ReconcileVersionMeta[] }) {
  useLocale();
  return (
    <section className="card" aria-label={t("Earlier versions")}>
      <h2>{t("Earlier versions")}</h2>
      <ul className="plain">
        {versions.map((v) => (
          <li key={v.version} className="small">
            {t("Version {{n}}: approved by {{who}}, {{when}}; reopened by {{by}}, {{at}}: {{note}}",
              { n: v.version, who: v.approved_by, when: when(v.approved_at), by: v.reopened_by ?? "", at: when(v.reopened_at), note: v.reopen_note ?? "" })}
            {" "}<a href={api.reconcileStatementXlsxUrl(wpId, v.version)} download>{t("Download (Excel)")}</a>
          </li>
        ))}
      </ul>
    </section>
  );
}
