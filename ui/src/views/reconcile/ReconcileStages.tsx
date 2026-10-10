// 132 (backlog F-reconciliation E2): the stages of a reconciliation package — Preparation · Pairing · Result. The
// package's workspace (its lines, invoices, coverage and blockers) is loaded once here; every decision returns the
// recomputed workspace, which replaces it (no periodic reloading of the whole page, the legacy weakness).
import { useEffect, useState } from "react";
import { api, ApiError, type ReconcileWorkspace, type WorkpackageView } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { go, type Stage } from "../../route";
import { AccountChecklist } from "./ReconcileCreate";
import { ReconcilePairing } from "./ReconcilePairing";
import { blockerText, INVOICE_STATE, LINE_STATE } from "./labels";
import "./reconcile.css";

export function ReconcileStages({ view, stage, onChanged }: { view: WorkpackageView; stage: Stage; onChanged: () => void }) {
  useLocale();
  const wpId = view.workpackage.id;
  const loaded = useLoad(`reconcile:${wpId}`, () => api.reconcileWorkspace(wpId));
  const [ws, setWs] = useState<ReconcileWorkspace | null>(null);
  useEffect(() => { if (loaded.data) setWs(loaded.data); }, [loaded.data]);
  const update = (next: ReconcileWorkspace) => { setWs(next); onChanged(); };
  const readOnly = view.workpackage.status === "archived";

  if (!ws) {
    return loaded.error ? <p className="notice error" role="alert">{loaded.error.message}</p> : <p className="muted">{t("Loading…")}</p>;
  }
  if (stage === "process") return <ReconcilePrepare ws={ws} readOnly={readOnly} onWorkspace={update} reload={loaded.reload} />;
  if (stage === "review") return <ReconcilePairing ws={ws} readOnly={readOnly} onWorkspace={update} reload={loaded.reload} />;
  return <ReconcileSummary ws={ws} />;
}

function Counts({ counts, labels }: { counts: Record<string, number>; labels: Record<string, string> }) {
  const entries = Object.entries(counts).filter(([, n]) => n > 0);
  if (!entries.length) return <span className="muted small">{t("none")}</span>;
  return (
    <span className="rc-counts">
      {entries.map(([k, n]) => <span key={k} className={`rc-state s-${k}`}>{labels[k] ?? k}: {n}</span>)}
    </span>
  );
}

interface StageProps { ws: ReconcileWorkspace; readOnly: boolean; onWorkspace: (ws: ReconcileWorkspace) => void; reload: () => void }

/** Preparation: the scope (accounts and period), how far the statements cover it, what blocks the approval, and the
 *  recomputation with the missing exchange rates. */
export function ReconcilePrepare({ ws, readOnly, onWorkspace, reload }: StageProps) {
  useLocale();
  const accounts = useLoad("reconcile-accounts", api.reconcileAccounts);
  const parties = useLoad("parties", api.parties);
  const [partyId, setPartyId] = useState<string>(ws.scope.party_id ?? "");
  const [chosen, setChosen] = useState<string[]>(ws.scope.accounts);
  const [start, setStart] = useState(ws.scope.period_start);
  const [end, setEnd] = useState(ws.scope.period_end);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const dirty = chosen.slice().sort().join("|") !== ws.scope.accounts.slice().sort().join("|")
    || start !== ws.scope.period_start || end !== ws.scope.period_end || partyId !== (ws.scope.party_id ?? "");
  const months = [...new Set(ws.coverage.map((c) => c.month))];
  const byKey = new Map((accounts.data?.accounts ?? []).map((a) => [a.key, a]));

  async function act(fn: () => Promise<ReconcileWorkspace>, done?: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      onWorkspace(await fn());
      if (done) setNotice(done);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(t("Someone changed the scope meanwhile; it has been reloaded."));
        reload();
      } else setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rc-stack">
      <section className="card" aria-label={t("Scope")}>
        <div className="card-head">
          <h2>{t("Scope")}</h2>
          <button type="button" className="primary" onClick={() => go({ view: "workpackages", wpId: ws.workpackage_id, stage: "review" })}>
            {t("Go to pairing")} →
          </button>
        </div>
        <p className="muted small">{t("The pairing works on the corrected values of documents already processed. Changing the scope keeps every decision made so far: they belong to the pairs, not to the package.")}</p>
        <label className="block rc-party-pick">{t("Own party")}
          <select value={partyId} disabled={readOnly} onChange={(e) => setPartyId(e.target.value)}>
            {!ws.scope.party_id ? <option value="">{t("None: every invoice is the package's")}</option> : null}
            {(parties.data?.parties ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        {accounts.data ? <AccountChecklist accounts={accounts.data.accounts} chosen={chosen} onChange={setChosen} partyId={partyId || null} /> : <p className="muted">{t("Loading…")}</p>}
        <div className="rc-period">
          <label className="block">{t("Period from")}<input type="date" value={start} disabled={readOnly} onChange={(e) => setStart(e.target.value)} /></label>
          <label className="block">{t("to")}<input type="date" value={end} disabled={readOnly} onChange={(e) => setEnd(e.target.value)} /></label>
          {readOnly ? null : (
            <button type="button" className="secondary" disabled={!dirty || busy || !chosen.length || !start || !end || start > end}
              onClick={() => void act(() => api.setReconcileScope(ws.workpackage_id, { accounts: chosen, period_start: start, period_end: end, expected_revision: ws.scope.revision, party_id: partyId || null }), t("The scope has been saved."))}>
              {t("Save the scope")}
            </button>
          )}
        </div>
        {error ? <p className="notice error" role="alert">{error}</p> : null}
        {notice ? <p className="small ok" role="status">{notice}</p> : null}
      </section>

      <section className="card" aria-label={t("Coverage")}>
        <div className="card-head">
          <h2>{t("Coverage")}</h2>
          {readOnly ? null : (
            <button type="button" className="secondary" disabled={busy}
              onClick={() => void act(() => api.reconcileRefresh(ws.workpackage_id), t("Recomputed; the missing exchange rates were fetched."))}
              title={t("Only dates and currency codes leave the machine (MNB official exchange rates).")}>
              {t("Recompute")}
            </button>
          )}
        </div>
        <p className="muted small">{t("Statements per account and month: a tick means the statement's balances check out.")}</p>
        <div className="dt-scroll">
          <table className="table compact rc-cov">
            <thead><tr><th>{t("Account or card")}</th>{months.map((m) => <th key={m}>{m}</th>)}</tr></thead>
            <tbody>
              {ws.scope.accounts.map((key) => (
                <tr key={key}>
                  <th scope="row" className="mono">{byKey.get(key)?.account ?? key}</th>
                  {months.map((m) => {
                    const c = ws.coverage.find((x) => x.account === key && x.month === m);
                    const cls = !c?.statements ? "none" : c.verified === c.statements ? "ok" : "warn";
                    const text = !c?.statements ? "–" : c.verified === c.statements ? `✓ ${c.statements}` : `! ${c.verified}/${c.statements}`;
                    const title = !c?.statements ? t("No statement for this month") : c.verified === c.statements
                      ? t("{{n}} statements, balances check out", { n: c.statements }) : t("{{n}} of {{total}} statements check out", { n: c.verified, total: c.statements });
                    return <td key={m} className={cls} title={title}>{text}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card" aria-label={t("What blocks the approval")}>
        <h2>{t("What blocks the approval")}</h2>
        {ws.blockers.length ? (
          <>
            <p className="muted small">{t("Pairing can start now; the reconciliation can only be approved once every source document comes from an approved run.")}</p>
            <ul className="plain">
              {ws.blockers.map((b) => <li key={`${b.code}:${b.doc_id}`} className="blocker small">{blockerText(b)}</li>)}
            </ul>
          </>
        ) : <p className="small ok">{t("Nothing: every source document comes from an approved run.")}</p>}
      </section>

      <section className="card" aria-label={t("Where the pairing stands")}>
        <h2>{t("Where the pairing stands")}</h2>
        <div className="rc-kv">
          <span className="muted small">{t("Statement lines")}</span><Counts counts={ws.counts.lines} labels={LINE_STATE} />
          <span className="muted small">{t("Invoices")}</span><Counts counts={ws.counts.invoices} labels={INVOICE_STATE} />
        </div>
      </section>
    </div>
  );
}

/** Result: where the reconciliation stands (the statement, its download and the approval come with the next step). */
export function ReconcileSummary({ ws }: { ws: ReconcileWorkspace }) {
  useLocale();
  return (
    <div className="rc-stack">
      <section className="card" aria-label={t("Where the pairing stands")}>
        <h2>{t("Where the pairing stands")}</h2>
        <div className="rc-kv">
          <span className="muted small">{t("Statement lines")}</span><Counts counts={ws.counts.lines} labels={LINE_STATE} />
          <span className="muted small">{t("Invoices")}</span><Counts counts={ws.counts.invoices} labels={INVOICE_STATE} />
        </div>
        <p className="muted small">{t("The reconciliation statement, its download and its approval will be shown here.")}</p>
      </section>
    </div>
  );
}
