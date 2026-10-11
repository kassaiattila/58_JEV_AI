// 144 (DECISIONS 144): a statement line's facts in one place — the card (ReconcileCards.tsx), the finder's pinned line
// (ReconcileFinder.tsx) and the documents' statement pane (DocumentPair.tsx) show the same labelled fields, so a person
// sees the memo, the partner, its account and the days wherever they pair. The owner asked for every meaningful fact of
// the transfer by hand too; the statement's file name stays with the documents (DECISIONS 144), not among the facts.
import type { ReactNode } from "react";
import type { ReconcileInvoice, ReconcileLine, ReconcileStatementLine } from "../../api";
import { t, useLocale } from "../../i18n";
import { ENGINE, EXCLUDED, KIND, LINE_STATE, MARK, probability } from "./labels";
import { display, parseCanonical, show } from "./money";
import { expectsInvoice, kinds } from "./partners";

/** The line's amount with its sign: a credit is positive, a debit negative (null: no amount). */
export function signedAmount(line: { amount: string | null; direction: string | null }): bigint | null {
  const v = parseCanonical(line.amount);
  return v === null ? null : line.direction === "credit" ? v : -v;
}

export function Fact({ label, children }: { label: string; children: ReactNode }) {
  return <><dt>{label}</dt><dd>{children}</dd></>;
}

/** The bank's facts of a line, as the statement prints them (a fragment of a `<dl>`). `currency`: the statement's. */
export function TransactionFacts({ line: l, currency, account }: {
  line: ReconcileStatementLine; currency: string | null; account?: string | null;
}) {
  useLocale();
  return (
    <>
      <Fact label={t("Booking day")}>{l.booking_date ?? "–"}</Fact>
      {l.value_date && l.value_date !== l.booking_date ? <Fact label={t("Value day")}>{l.value_date}</Fact> : null}
      {l.original_amount && l.original_currency ? <Fact label={t("Original amount")}>{show(l.original_amount, l.original_currency)}</Fact> : null}
      <Fact label={t("Counterparty")}>{l.counterparty_name || "–"}</Fact>
      {l.counterparty_account ? <Fact label={t("Counterparty's account")}>{l.counterparty_account}</Fact> : null}
      {l.memo ? <Fact label={t("Memo")}>{l.memo}</Fact> : null}
      {l.description ? <Fact label={t("Description")}>{l.description}</Fact> : null}
      {l.running_balance ? <Fact label={t("Balance after")}>{show(l.running_balance, currency)}</Fact> : null}
      {account ? <Fact label={t("Account or card")}>{account}</Fact> : null}
    </>
  );
}

/** A line of the package on a card: its amount and state, then every fact and the decisions made on it. */
export function LineFacts({ line: l, repeat, invoices }: { line: ReconcileLine; repeat: boolean; invoices: Map<string, ReconcileInvoice> }) {
  useLocale();
  const amount = signedAmount(l);
  const partly = parseCanonical(l.allocated) !== 0n && l.state !== "allocated";
  const ks = kinds(l);
  return (
    <div className={`rc-facts${repeat ? " repeat" : ""}`}>
      <div className="rc-facts-head">
        <span className={`rc-amount${amount !== null && amount > 0n ? " credit" : ""}`}>{display(amount, l.currency)}</span>
        <span className={`rc-state s-${l.state}`}>{LINE_STATE[l.state] ?? l.state}</span>
        {repeat ? <span className="rc-sig warn">{t("may repeat the payment")}</span> : null}
        {expectsInvoice(l) ? <span className="rc-sig warn">{t("invoice expected")}</span> : null}
        {l.statement_verified ? null : <span className="rc-sig warn">{t("statement balances do not check out")}</span>}
      </div>
      <dl>
        {partly ? <Fact label={t("Left to pair")}>{show(l.rest, l.currency)}</Fact> : null}
        <TransactionFacts line={l} currency={l.currency} account={l.account} />
        {ks.length ? <Fact label={t("Kind (AI)")}>{ks.map((k) => `${ENGINE[k.engine]}: ${KIND[k.kind] ?? k.kind} ${probability(k.probability)}`).join(" · ")}</Fact> : null}
        {l.mark ? <Fact label={t("Needs no invoice")}>{MARK[l.mark.category] ?? l.mark.category}{l.mark.note ? ` — ${l.mark.note}` : ""}</Fact> : null}
        {l.excluded_reason ? <Fact label={t("Left out")}>{EXCLUDED[l.excluded_reason] ?? l.excluded_reason}</Fact> : null}
        {l.rejected.length ? <Fact label={t("Not this one")}>{l.rejected.map((id) => invoices.get(id)?.number ?? id.slice(0, 12)).join(", ")}</Fact> : null}
      </dl>
    </div>
  );
}
