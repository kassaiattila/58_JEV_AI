// 132 (backlog F-reconciliation E2): the stages of a reconciliation package — Preparation · Pairing · Result. The
// package's workspace (its lines, invoices, coverage and blockers) is loaded once here; every decision returns the
// recomputed workspace, which replaces it (no periodic reloading of the whole page, the legacy weakness).
import { useEffect, useState } from "react";
import { api, ApiError, type ReconcileLeftOver, type ReconcileUnfit, type ReconcileWorkspace, type WorkpackageView } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { go, type Stage } from "../../route";
import { AccountChecklist } from "./ReconcileCreate";
import { ReconcileCards } from "./ReconcileCards";
import { ReconcileInputs } from "./ReconcileInputs";
import { ReconcilePairing } from "./ReconcilePairing";
import { ReconcileQuickReview } from "./ReconcileQuickReview";
import { ReconcileResult } from "./ReconcileResult";
import { EXCLUDED, INVOICE_STATE, LINE_STATE, MARK, warningText } from "./labels";
import { BlockerList } from "./BlockerList";
import { show } from "./money";
import "./reconcile.css";

export function ReconcileStages({ view, stage, onChanged }: { view: WorkpackageView; stage: Stage; onChanged: () => void }) {
  useLocale();
  const wpId = view.workpackage.id;
  const loaded = useLoad(`reconcile:${wpId}`, () => api.reconcileWorkspace(wpId));
  const [ws, setWs] = useState<ReconcileWorkspace | null>(null);
  useEffect(() => { if (loaded.data) setWs(loaded.data); }, [loaded.data]);
  const update = (next: ReconcileWorkspace) => { setWs(next); onChanged(); };
  // 142: the pairing opens on the cards; the two lists are for pairing by hand, with the line a card sent there
  const [manual, setManual] = useState<{ line: string | null } | null>(null);
  // 147: the pairing opens on the quick review (the groups accepted at once); the cards and the two lists stay
  const [mode, setMode] = useState<"quick" | "cards">("quick");
  const archived = view.workpackage.status === "archived";
  // 145: an approved package takes no decision until its approval is reopened (the Result stage)
  const approved = ws?.approval?.active ?? null;
  const readOnly = archived || approved !== null;

  if (!ws) {
    return loaded.error ? <p className="notice error" role="alert">{loaded.error.message}</p> : <p className="muted">{t("Loading…")}</p>;
  }
  if (stage === "result") {
    return <ReconcileResult ws={ws} archived={archived} onChanged={onChanged} reloadWorkspace={loaded.reload} />;
  }
  const banner = approved ? (
    <p className="notice ok-box" role="status">
      {t("Approved: version {{n}}, by {{who}}. The decisions are locked; reopen the approval in the Result stage to change them.", { n: approved.version, who: approved.approved_by })}
    </p>
  ) : null;
  if (stage === "process") return <>{banner}<ReconcilePrepare ws={ws} readOnly={readOnly} onWorkspace={update} reload={loaded.reload} /></>;
  return (
    <>
      {banner}
      {ws.overview && !manual ? (
        <div className="segmented-tabs rc-modes" role="tablist" aria-label={t("Pairing views")}>
          <button type="button" role="tab" className="seg" aria-selected={mode === "quick"} onClick={() => setMode("quick")}>{t("Quick review")}</button>
          <button type="button" role="tab" className="seg" aria-selected={mode === "cards"} onClick={() => setMode("cards")}>{t("Cards")}</button>
        </div>
      ) : null}
      {manual || !ws.overview ? ( // a service without the overview keeps the two lists
        <ReconcilePairing key={manual?.line ?? "lists"} ws={ws} readOnly={readOnly} onWorkspace={update} reload={loaded.reload}
          initialLine={manual?.line ?? null} onCards={ws.overview ? () => setManual(null) : undefined} />
      ) : mode === "quick" ? (
        <ReconcileQuickReview wpId={wpId} readOnly={readOnly} onWorkspace={update} onCards={() => setMode("cards")} />
      ) : <ReconcileCards ws={ws} readOnly={readOnly} onWorkspace={update} reload={loaded.reload} onManual={(line) => setManual({ line })} />}
      {/* 169 (DECISIONS 169): the same item list as in Preparation, as every package has it in Review (168) */}
      <details className="details mt">
        <summary>{t("The package's items: add, open, leave out")}</summary>
        <ReconcileInputs ws={ws} readOnly={readOnly} onWorkspace={update} />
      </details>
    </>
  );
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
          <button type="button" className="secondary" onClick={() => go({ view: "workpackages", wpId: ws.workpackage_id, stage: "review" })}>{/* 156: the header holds the solid next step */}
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
        {/* 167 (review 160 U-11): a failed load says so instead of "Loading…" for ever */}
        {parties.error ? <p className="notice error small" role="alert">{parties.error.message}</p> : null}
        {accounts.error ? <p className="notice error" role="alert">{accounts.error.message}</p>
          : accounts.data ? <AccountChecklist accounts={accounts.data.accounts} chosen={chosen} onChange={setChosen} partyId={partyId || null} />
          : <p className="muted">{t("Loading…")}</p>}
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

      {/* 169 (DECISIONS 169): what the pairing takes — every package lists its items (168) */}
      <ReconcileInputs ws={ws} readOnly={readOnly} onWorkspace={onWorkspace} />

      <LeftOver ws={ws} readOnly={readOnly} busy={busy}
        onRevoke={(r) => void act(() => api.reconcileRevoke(ws.workpackage_id, r.kind, r.ref), t("The decision has been revoked."))} />
      <Unfit ws={ws} readOnly={readOnly} busy={busy}
        onRevoke={(r) => void act(() => api.reconcileRevoke(ws.workpackage_id, r.kind, r.ref), t("The decision has been revoked."))} />

      <section className="card" aria-label={t("What blocks the approval")}>
        <h2>{t("What blocks the approval")}</h2>
        {ws.blockers.length ? (
          <>
            <p className="muted small">{t("Pairing can start now; the reconciliation can only be approved once every source document comes from an approved run.")}</p>
            <BlockerList blockers={ws.blockers} />
          </>
        ) : <p className="small ok">{t("Nothing: every source document comes from an approved run.")}</p>}
        {ws.warnings?.length ? (
          <>
            <h3>{t("Warnings")}</h3>
            <ul className="plain">
              {ws.warnings.map((w) => <li key={`${w.code}:${w.doc_id}`} className="small warn">{warningText(w)}</li>)}
            </ul>
          </>
        ) : null}
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

/** 153 (review A3): the pairings that no longer fit the amounts of their line or invoice (a correction or a new
 *  reading changed an amount since); 160 (review M-1): also a pairing whose invoice left the pairing, and a pairing or a
 *  mark whose line is no longer on its statement. They count nowhere and block the approval until revoked here. */
export function Unfit({ ws, readOnly, busy, onRevoke }: {
  ws: ReconcileWorkspace; readOnly: boolean; busy: boolean; onRevoke: (r: ReconcileUnfit) => void;
}) {
  useLocale();
  const rows = ws.unfit ?? [];
  if (!rows.length) return null;
  const line = (r: ReconcileUnfit) => r.reason === "line_gone"
    ? t("no longer on {{file}}", { file: r.file ?? r.statement_id?.slice(0, 12) ?? "–" })
    : `${r.booking_date ?? "–"} · ${r.counterparty_name ?? "–"}`;
  const decision = (r: ReconcileUnfit) => r.kind === "mark"
    ? t("needs no invoice ({{reason}})", { reason: MARK[r.category ?? ""] ?? r.category ?? "" })
    : t("paid: {{invoice}}", { invoice: r.invoice_file ?? r.invoice_id?.slice(0, 12) ?? "" });
  const why = (r: ReconcileUnfit) => r.reason === "line_gone" ? t("the line was changed or read again")
    : r.reason === "invoice_left_out" ? t("the invoice left the pairing: {{why}}", { why: EXCLUDED[r.invoice_reason ?? ""] ?? r.invoice_reason ?? "–" })
      : t("an amount changed");
  return (
    <section className="card" aria-label={t("Decisions that no longer count")}>
      <h2>{t("Decisions that no longer count")}</h2>
      <p className="muted small">{t("These pairings and marks count nowhere: an amount changed since they were made, the invoice no longer takes part in the pairing, or the line was changed or read again. Revoke each one, then decide on the line again.")}</p>
      <table className="table compact">
        <thead><tr><th>{t("Line")}</th><th>{t("Decision")}</th><th>{t("Reason")}</th><th className="num">{t("Paired amount")}</th><th className="num">{t("Amounts now")}</th><th /></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.kind}:${r.ref}`}>
              <td>{line(r)}</td>
              <td>{decision(r)}</td>
              <td>{why(r)}</td>
              <td className="num">{r.kind === "mark" ? "–" : show(r.line_amount, r.currency)}</td>
              <td className="num">{r.reason === "amounts" ? t("line {{line}} · invoice {{invoice}}", { line: show(r.line_total, r.currency), invoice: show(r.invoice_total) }) : "–"}</td>
              <td>{readOnly ? null : <button type="button" className="secondary small-btn" disabled={busy} onClick={() => onRevoke(r)}>{t("Revoke")}</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** 139 (DECISIONS 139): the decisions made on a line of a replaced statement that has no same line on the valid
 *  statement; each can be revoked here and made again on the valid statement's lines. */
function LeftOver({ ws, readOnly, busy, onRevoke }: {
  ws: ReconcileWorkspace; readOnly: boolean; busy: boolean; onRevoke: (r: ReconcileLeftOver) => void;
}) {
  useLocale();
  const rows = ws.left_over ?? [];
  if (!rows.length) return null;
  const what = (r: ReconcileLeftOver) => r.kind === "mark" ? t("needs no invoice ({{reason}})", { reason: MARK[r.category ?? ""] ?? r.category ?? "" })
    : r.kind === "allocation" ? t("paid: {{invoice}}", { invoice: r.invoice_file ?? r.invoice_id?.slice(0, 12) ?? "" })
      : t("a decision on the pair with {{invoice}}", { invoice: r.invoice_file ?? r.invoice_id?.slice(0, 12) ?? "" });
  return (
    <section className="card" aria-label={t("Decisions not carried over")}>
      <h2>{t("Decisions not carried over")}</h2>
      <p className="muted small">{t("A better statement replaced one of these accounts' statements, but these lines have no same line on it. Revoke each decision, then make it again on the valid statement's lines.")}</p>
      <table className="table compact">
        <thead><tr><th>{t("Line")}</th><th>{t("Decision")}</th><th>{t("Replaced statement")}</th><th>{t("Valid statement")}</th><th /></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.kind}:${r.ref}`}>
              <td>{r.booking_date} · {r.counterparty_name ?? "–"} · {r.direction === "credit" ? "+" : "−"}{r.amount} {r.currency}</td>
              <td>{what(r)}</td>
              <td>{r.file ?? r.statement_id.slice(0, 12)}</td>
              <td>{r.replaced_by_file ?? r.replaced_by.slice(0, 12)}</td>
              <td>{readOnly ? null : <button type="button" className="secondary small-btn" disabled={busy} onClick={() => onRevoke(r)}>{t("Revoke")}</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
