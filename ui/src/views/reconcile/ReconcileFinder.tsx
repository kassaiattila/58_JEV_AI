// 143 (DECISIONS 143): the finder — the right pane of the pairing page's two lists. The owner found the invoice list
// beside a selected statement line hard to read: nothing said which invoice is the line's payment and why. The
// selected line stands pinned at the top with a bar of how much the ticked invoices cover; below it the invoices in
// three groups (finder.ts): the fitting ones, the rest by amount only, and the bound or settled ones (closed). Every row
// says in a column whether the name, the invoice number and the account match the line, how the amount differs and
// how the line was booked against the invoice's due date.
import { useState } from "react";
import type { ReconcileInvoice, ReconcileLine } from "../../api";
import { t, useLocale } from "../../i18n";
import { criteria, daysFromDue, type Binding, type FinderEntry, type FinderSections, type Verdict } from "./finder";
import { dueText, ENGINE, fxText, INVOICE_STATE, KIND, MARK, probability, relationText, SIGNAL } from "./labels";
import { display, parseCanonical, show, sum } from "./money";
import { rest } from "./pairing";
import { TransactionFacts } from "./LineFacts";
import { expectsInvoice, kinds } from "./partners";

const FIRST = 30; // the invoices shown at first by amount only; more on request

const signed = (line: ReconcileLine): bigint | null => {
  const v = parseCanonical(line.amount);
  return v === null ? null : line.direction === "credit" ? v : -v;
};
const lineTitle = (l: ReconcileLine) => l.counterparty_name || l.description || l.memo || "–";
const invoiceTitle = (i: ReconcileInvoice) => [i.partner_name ?? i.supplier_name, i.number].filter(Boolean).join(" · ") || i.file || "–";

/** The selected line pinned above the invoices: what is searched for, how much the ticked invoices cover, and the
 *  decisions already made on it (each can be undone). */
export function FinderHead({ line, lines, invoices, invoiceById, readOnly, busy, onRevoke }: {
  line: ReconcileLine; lines: ReconcileLine[]; invoices: ReconcileInvoice[]; invoiceById: Map<string, ReconcileInvoice>;
  readOnly: boolean; busy: boolean; onRevoke: (kind: "allocation" | "mark" | "decision", ref: string) => void;
}) {
  useLocale();
  const name = (id: string) => { const inv = invoiceById.get(id); return inv ? invoiceTitle(inv) : id.slice(0, 12); };
  const several = lines.length > 1;
  return (
    <div className="rc-finder-head" aria-label={t("The selected line")}>
      <p className="rc-finder-kicker">{t("Finding the invoice for")}</p>
      <div className="rc-finder-line">
        <span className="rc-date">{line.booking_date ?? "–"}</span>
        <strong className="rc-amount">{display(signed(line), line.currency)}</strong>
        <span className="rc-finder-title">{lineTitle(line)}</span>
        {line.state === "partly_allocated" ? <span className="small muted">{t("left: {{amount}}", { amount: show(line.rest, line.currency) })}</span> : null}
        {line.statement_verified ? null : <span className="rc-sig warn">{t("statement balances do not check out")}</span>}
      </div>
      {/* 144: every fact of the transfer, labelled (DECISIONS 144) */}
      <dl className="rc-finder-facts">
        <TransactionFacts line={line} currency={line.currency} account={line.account} />
      </dl>
      {several ? (
        <p className="small">{t("{{n}} lines selected, together: {{amount}}", { n: lines.length, amount: sideTotal(lines) })} · {t("the columns compare the line above")}</p>
      ) : null}
      <Coverage lines={lines.length ? lines : [line]} invoices={invoices} />
      {kinds(line).length ? (
        <p className="small muted">
          {t("Kind (AI)")}: {kinds(line).map((k) => `${ENGINE[k.engine]}: ${KIND[k.kind] ?? k.kind} ${probability(k.probability)}`).join(" · ")}
          {kinds(line).some((k) => k.lent) ? ` · ${t("asked once for the partner")}` : ""}
          {expectsInvoice(line) ? ` · ${t("an invoice is expected, but none is in the store")}` : ""}
        </p>
      ) : null}
      {line.earlier_marks?.length ? (
        <p className="small muted">
          {t("Earlier for this partner")}: {line.earlier_marks.map((e) => t("{{reason}} ({{n}} lines)", { reason: MARK[e.category] ?? e.category, n: e.lines })).join(", ")}
        </p>
      ) : null}
      {line.allocations.map((a) => (
        <div key={`${a.invoice_id}|${a.allocation_id ?? "d"}`} className="rc-decided">
          <span className="ok">{t("Paired with {{invoice}}: {{amount}}", { invoice: name(a.invoice_id), amount: show(a.line_amount, line.currency) })}</span>
          {readOnly ? null : (
            <button type="button" className="quiet small-btn" disabled={busy}
              onClick={() => onRevoke(a.allocation_id !== null ? "allocation" : "decision", a.allocation_id !== null ? String(a.allocation_id) : `${a.invoice_id}|${line.id}`)}>
              {t("Undo")}
            </button>
          )}
        </div>
      ))}
      {line.mark ? (
        <div className="rc-decided">
          <span>{t("Needs no invoice")}: {MARK[line.mark.category] ?? line.mark.category}{line.mark.note ? ` — ${line.mark.note}` : ""}</span>
          {readOnly ? null : <button type="button" className="quiet small-btn" disabled={busy} onClick={() => onRevoke("mark", String(line.mark!.id))}>{t("Undo")}</button>}
        </div>
      ) : null}
      {line.rejected.map((id) => (
        <div key={id} className="rc-decided">
          <span className="muted">{t("Not this one: {{invoice}}", { invoice: name(id) })}</span>
          {readOnly ? null : <button type="button" className="quiet small-btn" disabled={busy} onClick={() => onRevoke("decision", `${id}|${line.id}`)}>{t("Undo")}</button>}
        </div>
      ))}
    </div>
  );
}

function sideTotal(items: { currency: string | null; rest: string | null }[]): string {
  return new Set(items.map((x) => x.currency)).size > 1 ? t("several currencies") : display(sum(items.map(rest)), items[0]?.currency);
}

/** How much of the selected lines the ticked invoices cover, as a bar and in words. */
function Coverage({ lines, invoices }: { lines: ReconcileLine[]; invoices: ReconcileInvoice[] }) {
  const target = sum(lines.map(rest));
  if (target <= 0n) return null;
  if (new Set([...lines, ...invoices].map((x) => x.currency)).size > 1) {
    return <p className="small muted">{t("Different currencies: compared through the exchange rate")}</p>;
  }
  const cur = lines[0].currency;
  const covered = sum(invoices.map(rest));
  const left = target - covered;
  const share = Number((covered * 1000n) / target) / 10;
  const text = left === 0n ? t("Covered exactly")
    : left > 0n ? t("Still to cover: {{amount}}", { amount: display(left, cur) })
      : lines.length > 1 ? t("More than the lines: {{amount}}", { amount: display(-left, cur) }) : t("More than the line: {{amount}}", { amount: display(-left, cur) });
  return (
    <div className="rc-cover" role="group" aria-label={t("Coverage")}>
      <span className="small">{t("Covered: {{covered}} of {{target}}", { covered: display(covered, cur), target: display(target, cur) })}</span>
      <span className={`rc-meter${left === 0n ? " full" : left < 0n ? " over" : ""}`} aria-hidden="true">
        <span style={{ width: `${Math.min(100, Math.max(0, share))}%` }} />
      </span>
      <strong className={`small ${left === 0n ? "ok" : "warn-text"}`}>{text}</strong>
    </div>
  );
}

const ICON: Record<Verdict, string> = { yes: "✓", loose: "≈", no: "✗", differs: "✗", unknown: "–" };

function verdictText(what: "name" | "number" | "account", v: Verdict): string {
  if (what === "name") {
    return v === "yes" ? t("The name matches") : v === "loose" ? t("The name is similar") : v === "no" ? t("The name does not match") : t("No name to compare");
  }
  if (what === "number") return v === "yes" ? t("The memo names the invoice") : v === "no" ? t("The memo does not name the invoice") : t("No memo to compare");
  return v === "yes" ? t("Paid to the account on the invoice") : v === "differs" ? t("Paid to another account than the one on the invoice") : t("No account to compare");
}

function VerdictCell({ what, v }: { what: "name" | "number" | "account"; v: Verdict }) {
  const text = verdictText(what, v);
  return <span className={`rc-verdict v-${v}`} role="img" aria-label={text} title={text}>{ICON[v]}</span>;
}

/** The invoice's amount against the line's: exact, less or more by how much, or converted. */
function amountText(entry: FinderEntry, line: ReconcileLine): { text: string; tone: "ok" | "warn" | "muted" } {
  const m = entry.match;
  const fx = m?.fx ?? entry.candidate?.fx;
  if (fx) {
    const ok = ["fx_within", "combined"].includes(String(m?.amount_relation ?? entry.candidate?.amount_relation)); // 151: together
    return { text: fxText(fx, show(fx.converted, "HUF")), tone: ok ? "ok" : "warn" };
  }
  let diff: bigint | null = null;
  let cur: string | null = entry.invoice.currency;
  if (m?.difference) {
    diff = parseCanonical(m.difference.amount);
    cur = m.difference.currency;
  } else if (!m && entry.invoice.currency === line.currency) {
    diff = rest(entry.invoice) - rest(line);
  }
  if (diff === null) return { text: t("another currency"), tone: "muted" };
  if (diff === 0n) return { text: t("exact amount"), tone: "ok" };
  return diff < 0n ? { text: t("{{amount}} less than the line", { amount: display(-diff, cur) }), tone: "warn" }
    : { text: t("{{amount}} more than the line", { amount: display(diff, cur) }), tone: "warn" };
}

/** Why an invoice is not free for the line; nothing for a free one (every invoice of the first two groups is). */
function bindingText(b: Binding, invoice: ReconcileInvoice, lineById: Map<string, ReconcileLine>): string | null {
  const other = (ids: string[]) => lineById.get(ids[0] ?? "");
  switch (b.kind) {
    case "free": return null;
    case "partly_paid": return t("partly paid, left: {{amount}}", { amount: show(invoice.rest, invoice.currency) });
    case "this_line": return t("paired with this line");
    case "credited": return INVOICE_STATE.credited;
    case "rejected": return t("rejected for this line");
    case "paid": {
      const l = other(b.lines);
      return l ? t("paid by another line: {{date}}", { date: l.booking_date ?? "–" }) : t("paid by a line outside this package");
    }
    case "proposed_elsewhere": {
      const l = other(b.lines);
      return l ? t("proposed for another line: {{date}}, {{amount}}", { date: l.booking_date ?? "–", amount: display(signed(l), l.currency) })
        : t("proposed for another line");
    }
  }
}

function FinderRow({ entry, line, index, selected, onToggle, readOnly, scoped, lineById }: {
  entry: FinderEntry; line: ReconcileLine; index?: number; selected: boolean; onToggle: (id: string) => void; readOnly: boolean;
  scoped: boolean; lineById: Map<string, ReconcileLine>;
}) {
  const { invoice, match, candidate, ai, binding } = entry;
  const c = criteria(line, invoice, match, candidate);
  const amount = amountText(entry, line);
  const days = daysFromDue(line, invoice);
  const relation = match?.amount_relation ?? candidate?.amount_relation ?? null;
  const channel = (match?.signals ?? candidate?.signals ?? []).includes("payment_channel");
  const partly = parseCanonical(invoice.allocated) !== 0n && rest(invoice) > 0n;
  const proposed = candidate?.proposed || match?.fit === "proposed";
  const bound = bindingText(binding, invoice, lineById);
  return (
    <li className={`rc-frow${proposed ? " proposed" : ""}${selected ? " is-selected" : ""}`}>
      <input type="checkbox" checked={selected} disabled={readOnly} aria-label={t("Select the invoice {{name}}", { name: invoiceTitle(invoice) })} onChange={() => onToggle(invoice.id)} />
      <button type="button" className="rc-frow-body" disabled={readOnly} onClick={() => onToggle(invoice.id)} title={invoice.file ?? undefined}>
        <span className="rc-fcell rc-finv">
          <span className="rc-main">{index ? <span className="kbd">{index}</span> : null} {invoiceTitle(invoice)}</span>
          <span className="rc-sub">
            {[invoice.issue_date ? t("issued {{date}}", { date: invoice.issue_date }) : null,
              invoice.due_date ? t("due {{date}}", { date: invoice.due_date }) : t("no due date"),
              invoice.source !== "approved" ? (invoice.source === "no_run" ? t("command line") : t("run not approved")) : null].filter(Boolean).join(" · ")}
          </span>
          <span className="rc-sigs">
            {proposed ? <span className="rc-sig good">{t("proposed by code")}</span> : null}
            {!candidate && ai.length && !match?.fit ? <span className="rc-sig warn">{t("AI only: code found nothing that ties them")}</span> : null}
            {ai.map((a) => <span key={a.engine} className="rc-sig good">{`${ENGINE[a.engine] ?? a.engine} ${probability(a.probability)}`}</span>)}
            {relation === "combined" ? <span className="rc-sig good">{relationText(relation)}</span> : null}
            {channel ? <span className="rc-sig good">{SIGNAL.payment_channel}</span> : null}
            {candidate?.multiple_candidates ? <span className="rc-sig warn">{t("several candidates")}</span> : null}
            {candidate?.source_review_required ? <span className="rc-sig warn">{t("statement balances do not check out")}</span> : null}
            {candidate?.original ? <span className="rc-sig good">{t("on the card purchase's original {{amount}}", { amount: show(candidate.original.amount, candidate.original.currency) })}</span> : null}
            {invoice.own === false && invoice.party ? <span className="rc-sig warn">{t("Other party: {{party}}", { party: invoice.party.name })}</span> : null}
            {scoped && !invoice.party ? <span className="small muted">{t("no own party")}</span> : null}
          </span>
        </span>
        <span className="rc-fcell rc-famount">
          <span className="rc-amount">{show(partly ? invoice.rest : invoice.amount, invoice.currency)}</span>
          <span className={`small ${amount.tone === "ok" ? "ok" : amount.tone === "warn" ? "warn-text" : "muted"}`}>{amount.text}</span>
        </span>
        <VerdictCell what="name" v={c.name} />
        <VerdictCell what="number" v={c.number} />
        <VerdictCell what="account" v={c.account} />
        <span className="rc-fcell rc-ftime">
          <span className={days !== null && days > 0 ? "warn-text" : undefined}>{dueText(days)}</span>
          {match && !match.in_window && (match.fit || relation === "equal") ? <span className="small muted">{t("outside the invoice's search period")}</span> : null}
          {bound ? <span className={`small ${binding.kind === "partly_paid" ? "muted" : "warn-text"}`}>{bound}</span> : null}
          {invoice.credited_by ? <span className="small muted">{t("credit note: {{number}}", { number: invoice.credited_by.number ?? "–" })}</span> : null}
          {entry.alsoFor.length ? (
            <span className="small warn-text">{t("also proposed for another line: {{date}}", { date: lineById.get(entry.alsoFor[0])?.booking_date ?? "–" })}</span>
          ) : null}
        </span>
      </button>
    </li>
  );
}

function ColumnHead() {
  return (
    <div className="rc-fhead" aria-hidden="true">
      <span />
      <span className="rc-fhead-cols">
        <span>{t("Invoice")}</span><span className="num">{t("Amount")}</span>
        <span title={t("The name matches")}>{t("Name")}</span><span title={t("The memo names the invoice")}>{t("Number")}</span>
        <span title={t("Paid to the account on the invoice")}>{t("Bank account")}</span><span>{t("Against the due date")}</span>
      </span>
    </div>
  );
}

/** The finder's three groups under the selected line; `fits` are numbered for the keys 1–9. */
export function FinderLists({ line, sections, state, selected, onToggle, readOnly, scoped, lineById, canMark, onMark, markHint }: {
  line: ReconcileLine; sections: FinderSections; state: { loading: boolean; error: string | null }; selected: string[];
  onToggle: (id: string) => void; readOnly: boolean; scoped: boolean; lineById: Map<string, ReconcileLine>;
  canMark: boolean; onMark: () => void; markHint: string | null;
}) {
  useLocale();
  const [boundOpen, setBoundOpen] = useState(false);
  const [limit, setLimit] = useState(FIRST);
  const row = (e: FinderEntry, index?: number) => (
    <FinderRow key={e.invoice.id} entry={e} line={line} index={index} selected={selected.includes(e.invoice.id)} onToggle={onToggle}
      readOnly={readOnly} scoped={scoped} lineById={lineById} />
  );
  const { fits, byAmount, bound } = sections;
  return (
    <>
      <p className="rc-section">{t("Invoices that fit ({{n}})", { n: fits.length })}</p>
      {fits.length ? <ColumnHead /> : null}
      <ul className="plain" aria-label={t("Invoices that fit")}>
        {fits.map((e, n) => row(e, n < 9 ? n + 1 : undefined))}
      </ul>
      {!fits.length ? (
        <div className="rc-empty small">
          {state.loading ? <p className="muted">{t("Comparing the invoices with the line…")}</p> : (
            <>
              <p>{t("No invoice fits: neither the name, the invoice number, the account nor the exact amount matches.")}</p>
              {expectsInvoice(line) ? <p className="warn-text">{t("The AI expects an invoice for it, but none is in the store.")}</p> : null}
              {canMark && !readOnly ? (
                <p>
                  {t("If it needs no invoice, mark it:")}{" "}
                  <button type="button" className="secondary small-btn" onClick={onMark}>{t("Needs no invoice")} <span className="kbd">m</span></button>
                  {markHint ? <span className="muted"> {markHint}</span> : null}
                </p>
              ) : null}
            </>
          )}
        </div>
      ) : null}
      {state.error ? <p className="small muted rc-empty">{t("The comparison is not available: {{reason}}", { reason: state.error })}</p> : null}
      <p className="rc-section">{t("By amount only, nearest first")}</p>
      {byAmount.length ? <ColumnHead /> : null}
      <ul className="plain" aria-label={t("By amount only, nearest first")}>
        {byAmount.slice(0, limit).map((e) => row(e))}
        {!byAmount.length ? <li className="rc-more muted small">{t("No invoice matches.")}</li> : null}
        {byAmount.length > limit ? (
          <li className="rc-more"><button type="button" className="quiet small-btn" onClick={() => setLimit((n) => n + FIRST * 3)}>{t("Show {{n}} more", { n: Math.min(FIRST * 3, byAmount.length - limit) })}</button></li>
        ) : null}
      </ul>
      {bound.length ? (
        <>
          <button type="button" className="rc-section rc-section-toggle" aria-expanded={boundOpen} onClick={() => setBoundOpen((v) => !v)}>
            {boundOpen ? "▾" : "▸"} {t("Bound to another line or settled ({{n}})", { n: bound.length })}
          </button>
          {boundOpen ? (
            <>
              <ColumnHead />
              <ul className="plain" aria-label={t("Bound to another line or settled")}>{bound.map((e) => row(e))}</ul>
            </>
          ) : null}
        </>
      ) : null}
    </>
  );
}
