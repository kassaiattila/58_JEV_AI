// 129 (backlog F-reconciliation K2): a proposed payment on the review page. The code found a statement line and an
// incoming invoice with the same currency and amount and at least one shared detail (jav/reconcile.py); the line and
// the invoice stand side by side with the details that tie them, and a person decides: this line paid it, or not this
// one (with a reason). The decision belongs to the pair and closes its to-dos; it can be changed until the run is
// approved. The pattern is the duplicate invoice panel (DuplicatePanel.tsx).
// 130: a forint card line and an invoice of another currency are compared through the MNB rate of the issue date; the
// panel shows the converted amount, the rate and the line's deviation from it, or that no rate is stored yet.
import { useRef, useState } from "react";
import { api, ApiError, type ItemResult, type ReconcileDecision, type ReconcilePair, type ReconcileSignal } from "../api";
import { getLocale, t, useLocale } from "../i18n";
import { tmap } from "../labels";

const SIGNAL: Record<ReconcileSignal, string> = tmap({
  invoice_number: "invoice number in the memo",
  supplier_account: "the supplier's account number",
  supplier_name: "the supplier's name",
});

const DECIDED: Record<ReconcileDecision, string> = tmap({
  paid_by: "Decided: this line paid the invoice",
  not_this: "Decided: not this pair",
});

function money(amount: string | null, currency: string | null): string {
  if (!amount) return "–";
  const text = getLocale() === "hu-HU" ? amount.replace(".", ",") : amount;
  return currency ? `${text} ${currency}` : text;
}

/** A deviation fraction ("0.0270") as a signed percentage ("+2,7%"). */
function percent(fraction: string): string {
  const value = Number(fraction) * 100;
  const text = `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
  return getLocale() === "hu-HU" ? text.replace(".", ",") : text;
}

function shown(v: string | null | undefined): string {
  return v ? v : "–";
}

function otherLink(p: ReconcilePair): string | null {
  return p.other_workpackage_id && p.other_item_id
    ? `#/workpackages/${encodeURIComponent(p.other_workpackage_id)}/review/${encodeURIComponent(p.other_item_id)}` : null;
}

function pairKey(p: ReconcilePair): string {
  return `${p.invoice_doc_id}|${p.line_id}`;
}

interface Props {
  result: ItemResult;
  readOnly: boolean;
  onDecided: () => void;
}

export function ReconcilePanel({ result, readOnly, onDecided }: Props) {
  useLocale();
  const [pending, setPending] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<string | null>(null); // the pair whose reason is being written
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false); // one request at a time (as the to-do's "resolved" button)
  const pairs = result.reconcile ?? [];
  if (!pairs.length) return null;

  async function decide(p: ReconcilePair, decision: ReconcileDecision, reason?: string): Promise<void> {
    if (busy.current) return;
    busy.current = true;
    setPending(pairKey(p));
    setError(null);
    try {
      await api.decideReconcile(result.run_id, result.item_id, p.invoice_doc_id, p.line_id, decision, reason);
      setRejecting(null);
      setNote("");
    } catch (e) {
      setError(t("The decision could not be saved: {{reason}}", { reason: e instanceof ApiError ? e.message : String(e) }));
    } finally {
      busy.current = false;
      setPending(null);
      onDecided();
    }
  }

  return (
    <section className="duplicates reconcile" aria-label={t("Possible payments")}>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {pairs.map((p) => {
        const key = pairKey(p);
        const link = otherLink(p);
        const inv = p.invoice;
        const line = p.line;
        return (
          <div key={key} className={`duplicate-pair${p.decision ? " decided" : ""}`}>
            <p className="duplicate-title">
              <strong>{p.side === "invoice" ? t("A statement line may have paid this invoice") : t("This statement line may have paid an invoice")}</strong>
            </p>
            <p className="small">
              {t("Matched by:")} {[...(p.amount_relation === "equal" ? [t("the same amount")] : []),
                ...(p.amount_relation === "fx_within" ? [t("the converted amount")] : []), ...p.signals.map((s) => SIGNAL[s])].join(", ")}
            </p>
            {p.amount_relation === "no_rate" ? (
              <p className="small warn-text">{t("No MNB exchange rate is stored for the invoice's issue date yet, so the amounts could not be compared")}</p>
            ) : null}
            {p.source_review_required ? (
              <p className="small warn-text">{t("The statement's balances do not check out; look at the line on the statement before deciding")}</p>
            ) : null}
            {link || p.other_file ? (
              <p className="small">
                {t("Other document:")}{" "}
                {link ? <a href={link} target="_blank" rel="noreferrer">{p.other_file ?? p.other_doc_id?.slice(0, 12)}</a>
                  : <span>{p.other_file}</span>}
              </p>
            ) : null}
            <table className="duplicate-table">
              <thead>
                <tr><th>{t("Field")}</th><th>{t("Statement line")}</th><th>{t("Invoice")}</th></tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">{t("Date")}</th>
                  <td>{shown(line?.booking_date)}</td>
                  <td>{shown(inv?.issue_date)}{inv?.due_date ? ` (${t("due {{date}}", { date: inv.due_date })})` : ""}</td>
                </tr>
                <tr className={p.amount_relation === "different" || p.amount_relation === "fx_outside" ? "differs" : undefined}>
                  <th scope="row">{t("Amount")}</th>
                  <td>{money(line?.amount ?? null, line?.currency ?? null)}</td>
                  <td>{money(inv?.amount ?? null, inv?.currency ?? null)}</td>
                </tr>
                {p.fx ? (
                  <tr className={p.amount_relation === "fx_outside" ? "differs" : undefined}>
                    <th scope="row">{t("Converted at the MNB rate")}</th>
                    <td>{t("{{pct}} from the converted amount", { pct: percent(p.fx.deviation) })}</td>
                    <td>
                      {money(p.fx.converted, line?.currency ?? null)}{" "}
                      ({t("{{rate}} HUF per {{currency}}, {{day}}", { rate: money(p.fx.rate, null), currency: inv?.currency ?? "", day: p.fx.rate_day })})
                    </td>
                  </tr>
                ) : null}
                <tr>
                  <th scope="row">{t("Supplier or counterparty")}</th>
                  <td>{shown(line?.counterparty_name)}{line?.counterparty_account ? ` · ${line.counterparty_account}` : ""}</td>
                  <td>{shown(inv?.supplier)}</td>
                </tr>
                <tr>
                  <th scope="row">{t("Memo or invoice number")}</th>
                  <td>{shown(line?.memo ?? line?.description)}</td>
                  <td>{shown(inv?.number)}</td>
                </tr>
                <tr>
                  <th scope="row">{t("File")}</th>
                  <td>{shown(line?.file)}</td>
                  <td>{shown(inv?.file)}</td>
                </tr>
              </tbody>
            </table>
            {p.decision ? (
              <p className="small ok">
                {DECIDED[p.decision]}{p.note ? ` — ${p.note}` : ""}{p.decided_by ? ` (${p.decided_by})` : ""}
              </p>
            ) : null}
            {readOnly ? null : (
              <div className="duplicate-actions" role="group" aria-label={t("Decision on the pair")}>
                <button type="button" className={p.decision === "paid_by" ? "primary small-btn" : "secondary small-btn"}
                  aria-pressed={p.decision === "paid_by"} disabled={pending !== null} onClick={() => void decide(p, "paid_by")}>
                  {t("This line paid it")}
                </button>
                <button type="button" className={p.decision === "not_this" ? "primary small-btn" : "secondary small-btn"}
                  aria-pressed={p.decision === "not_this"} disabled={pending !== null}
                  onClick={() => { setRejecting(rejecting === key ? null : key); setNote(""); }}>
                  {t("Not this one")}
                </button>
              </div>
            )}
            {!readOnly && rejecting === key ? (
              <form className="duplicate-actions" onSubmit={(e) => { e.preventDefault(); if (note.trim()) void decide(p, "not_this", note.trim()); }}>
                <label className="small">
                  {t("Why not this one?")}{" "}
                  <input type="text" value={note} maxLength={2000} autoFocus onChange={(e) => setNote(e.target.value)} />
                </label>
                <button type="submit" className="primary small-btn" disabled={!note.trim() || pending !== null}>{t("Save the rejection")}</button>
              </form>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}
