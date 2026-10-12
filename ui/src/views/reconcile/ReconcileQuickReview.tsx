// 147 (backlog F-quick-review; DECISIONS 147): the quick review of a reconciliation package. The lines a person still
// decides are shown in groups by what is known of them (a sure pair, the partner's earlier reason, the bank's category,
// salary, the AI's sure kind, the AI's suggestion to look at, an expected invoice, the rest); a group's lines are ticked
// and accepted at once. The AI counts as sure when both engines give the same kind and JEV is at least the policy's
// threshold sure of it; its other suggestions start unticked. The service re-reads the group when a person accepts it
// and takes only the lines still in it (jav/reconcile_review.py).
import { useState } from "react";
import { api, ApiError, type QuickReview, type QuickReviewGroup, type QuickReviewGroupId, type QuickReviewLine, type ReconcileWorkspace } from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { tmap } from "../../labels";
import { ENGINE, EXCLUDED, KIND, MARK, probability } from "./labels";
import { show } from "./money";

const TITLE: Record<QuickReviewGroupId, string> = tmap({
  sure_pairs: "Sure pairs", earlier: "As decided before", bank_category: "By the bank's category", salary_rule: "Salary",
  ai_sure: "Sure by AI", ai_review: "AI suggestion: look at it", expects_invoice: "An invoice is expected", rest: "To decide on the cards",
}) as Record<QuickReviewGroupId, string>;

/** How the group's suggestion is known; `{{p}}` is the AI threshold. */
const HOW: Record<QuickReviewGroupId, string> = {
  sure_pairs: "The invoice number or another sign and the exact amount tie each line to one invoice, on a statement whose balances check out.",
  earlier: "You gave this reason for the partner's other lines.",
  bank_category: "The bank's own category of the line: an ATM withdrawal is cash, an exchange or a top-up is a transfer between own accounts.",
  salary_rule: "The memo or the description says salary.",
  ai_sure: "Both AIs (JEV and GPT) read the same kind of payment, and JEV is at least {{p}} sure of it. The two models agree; that is not a checked fact.",
  ai_review: "Only one AI answered, or JEV is less than {{p}} sure: look at the lines before you accept them.",
  expects_invoice: "The AI read a kind of payment that usually has an invoice, but no invoice was found: it may be missing from the store.",
  rest: "Nothing tells what these lines are: decide them on the cards or the two lists.",
};

/** The groups whose lines start ticked: the code's rules, a person's earlier decision and the AI above the threshold. */
const TICKED: QuickReviewGroupId[] = ["sure_pairs", "earlier", "bank_category", "salary_rule", "ai_sure"];
const TONE: Record<QuickReviewGroupId, string> = {
  sure_pairs: "sure", earlier: "sure", bank_category: "sure", salary_rule: "sure", ai_sure: "sure", ai_review: "look",
  expects_invoice: "info", rest: "info",
};

function totalsText(totals: Record<string, string>): string {
  return Object.entries(totals).map(([cur, v]) => show(v, cur || null)).join(" + ");
}

export function ReconcileQuickReview({ wpId, readOnly, onWorkspace, onCards }: {
  wpId: string; readOnly: boolean; onWorkspace: (ws: ReconcileWorkspace) => void; onCards: () => void;
}) {
  useLocale();
  const loaded = useLoad(`quick-review:${wpId}`, () => api.reconcileQuickReview(wpId));
  const [after, setAfter] = useState<QuickReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const rv = after ?? loaded.data;

  async function accept(group: QuickReviewGroupId, lineIds: string[]) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const r = await api.reconcileQuickAccept(wpId, group, lineIds);
      setAfter(r.review);
      onWorkspace(r.workspace);
      setNotice(t("{{n}} line(s) decided.", { n: r.accepted }));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(t("The quick review changed meanwhile and has been reloaded. Check the group and try again."));
        setAfter(null);
        loaded.reload();
      } else if (e instanceof ApiError && e.code === "reconcile_locked") {
        setError(t("This line is in an approved reconciliation; reopen that approval first."));
      } else setError(t("The decision could not be saved: {{reason}}", { reason: e instanceof ApiError ? e.message : String(e) }));
    } finally {
      setBusy(false);
    }
  }

  if (loaded.error && !rv) return <p className="notice error" role="alert">{loaded.error.message}</p>;
  if (!rv) return <p className="muted">{t("Loading…")}</p>;
  const toDecide = rv.groups.reduce((n, g) => n + g.count, 0);
  const atOnce = rv.groups.filter((g) => g.action !== "none").reduce((n, g) => n + g.count, 0);
  const excluded = Object.entries(rv.excluded);
  return (
    <div className="rc-stack" aria-label={t("Quick review")}>
      <p className="small muted">{t("{{n}} line(s) to decide; {{quick}} of them are in a group you can accept at once.", { n: toDecide, quick: atOnce })}</p>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {notice ? <p className="notice ok" role="status">{notice}</p> : null}
      {!toDecide ? <p className="notice ok">{t("Every line of the package is decided.")}</p> : null}
      {rv.groups.filter((g) => g.count).map((g) => (
        <GroupCard key={`${g.id}:${g.count}:${g.lines[0]?.id ?? ""}`} group={g} threshold={rv.threshold} readOnly={readOnly}
          busy={busy} onAccept={(ids) => void accept(g.id, ids)} onCards={onCards} />
      ))}
      {excluded.length ? (
        <details>
          <summary className="small">{t("Left out by the code ({{n}})", { n: excluded.reduce((n, [, x]) => n + x.count, 0) })}</summary>
          <ul className="small">
            {excluded.map(([reason, x]) => <li key={reason}>{EXCLUDED[reason] ?? reason}: {x.count} · {totalsText(x.totals)}</li>)}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function GroupCard({ group, threshold, readOnly, busy, onAccept, onCards }: {
  group: QuickReviewGroup; threshold: number; readOnly: boolean; busy: boolean; onAccept: (lineIds: string[]) => void;
  onCards: () => void;
}) {
  useLocale();
  const [picked, setPicked] = useState<Set<string>>(() => new Set(TICKED.includes(group.id) ? group.lines.map((l) => l.id) : []));
  const chosen = group.lines.filter((l) => picked.has(l.id)).map((l) => l.id);
  const acts = group.action !== "none" && !readOnly;
  const toggle = (id: string) => setPicked((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const all = chosen.length === group.lines.length;
  return (
    <section className={`rc-box rc-qr rc-qr-${TONE[group.id]}`} aria-label={TITLE[group.id]}>
      <div className="rc-qr-head">
        <strong>{TITLE[group.id]}</strong>
        <span className="count">{group.count}</span>
        <span className="small">{totalsText(group.totals)}</span>
        <span className="spacer" />
        {acts ? (
          <ConfirmButton className="primary small-btn" disabled={busy || !chosen.length} onConfirm={() => onAccept(chosen)}>
            {t("Accept {{n}} line(s)", { n: chosen.length })}
          </ConfirmButton>
        ) : group.action === "none" ? <button type="button" className="secondary small-btn" onClick={onCards}>{t("To the cards")}</button> : null}
      </div>
      <p className="small muted">{t(HOW[group.id], { p: probability(threshold) })}</p>
      <details open={group.count <= 12}>
        <summary className="small">{t("The lines ({{n}})", { n: group.count })}</summary>
        <table className="table compact rc-qr-lines" aria-label={t("Lines of {{group}}", { group: TITLE[group.id] })}>
          <thead>
            <tr>
              {acts ? <th><input type="checkbox" checked={all} aria-label={t("All lines of {{group}}", { group: TITLE[group.id] })}
                onChange={() => setPicked(new Set(all ? [] : group.lines.map((l) => l.id)))} /></th> : null}
              <th>{t("Date")}</th><th>{t("Amount")}</th><th>{t("Counterparty")}</th><th>{t("Memo")}</th><th>{t("Suggestion")}</th>
            </tr>
          </thead>
          <tbody>
            {group.lines.map((l) => (
              <tr key={l.id}>
                {acts ? <td><input type="checkbox" checked={picked.has(l.id)} onChange={() => toggle(l.id)}
                  aria-label={t("Line of {{date}}, {{amount}}", { date: l.booking_date ?? "", amount: show(l.amount, l.currency) })} /></td> : null}
                <td className="mono">{l.booking_date ?? "–"}</td>
                <td className="mono">{show(l.amount, l.currency)}</td>
                <td>{l.counterparty_name ?? "–"}</td>
                <td className="rc-qr-memo small">{[l.memo, l.description].filter(Boolean).join(" · ") || "–"}</td>
                <td className="small"><Suggestion line={l} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}

function Suggestion({ line }: { line: QuickReviewLine }) {
  useLocale();
  const parts: string[] = [];
  if (line.category) parts.push(MARK[line.category] ?? line.category);
  for (const inv of line.invoices ?? []) parts.push(`${inv.number ?? "–"} · ${inv.supplier_name ?? "–"}`);
  if (line.earlier_lines) parts.push(t("as on {{n}} earlier line(s)", { n: line.earlier_lines }));
  for (const [engine, a] of Object.entries(line.ai ?? {})) {
    if (a) parts.push(`${ENGINE[engine] ?? engine}: ${KIND[a.kind] ?? a.kind} ${probability(a.probability)}`);
  }
  return <>{parts.join(" · ") || "–"}</>;
}
