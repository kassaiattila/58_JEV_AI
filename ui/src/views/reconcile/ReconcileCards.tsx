// 142 (DECISIONS 142, the reconciliation result's first part): the pairing page as cards. Each card is a group of
// related statement lines and invoices (jav/reconcile_overview.py): a transfer with the invoices it pays, an invoice
// with the lines that paid it, or a line or an invoice standing alone. A card shows every fact of both sides; each pair
// says how its booking day relates to the invoice's due date (every day after it is a delay); the lists a person checks
// (to decide, transfers without an invoice, invoices without a payment, overdue, paid late, possible double payments,
// to clarify) are chips at the top. The selected card's documents open on request, and by themselves when the card asks
// for a look (several candidates, a different amount, a possible double payment, an amount left, unverified balances).
// The two lists side by side (ReconcilePairing.tsx) stay for pairing by hand; a card sends its line there.
// Keyboard: arrows or j/k move between the cards, Enter accepts the selected card's proposal, d shows its documents.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api, ApiError, type ReconcileGroup, type ReconcileGroupPair, type ReconcileInvoice, type ReconcileInvoiceFacts,
  type ReconcileLine, type ReconcileList, type ReconcileWorkspace,
} from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { t, useLocale } from "../../i18n";
import { DocumentPair } from "./DocumentPair";
import { Fact, LineFacts } from "./LineFacts";
import {
  CARD_LIST, dueText, FLAG, GROUP_KIND, INVOICE_STATE, relationText, SIGNAL,
} from "./labels";
import { display, parseCanonical, show, sum } from "./money";
import { planPairing, rankedCandidates, toRequest } from "./pairing";
import { markable, suggestMark } from "./partners";
import { MarkPanel, ReasonPanel } from "./ReconcilePairing";

type View = ReconcileList | "all";
const VIEWS: View[] = ["to_decide", "line_without_invoice", "invoice_without_payment", "overdue", "late", "double_payment", "clarify",
  "paired", "marked", "credited", "excluded", "all"];
const PAGE = 40;
const CLARIFY = new Set(["several_candidates", "amount_differs", "statement_unverified", "double_payment", "rest_left"]);

const signed = (line: ReconcileLine): bigint | null => {
  const v = parseCanonical(line.amount);
  return v === null ? null : line.direction === "credit" ? v : -v;
};
const lineTitle = (l: ReconcileLine) => l.counterparty_name || l.description || l.memo || "–";
const invoiceTitle = (i: ReconcileInvoice) => [i.partner_name ?? i.supplier_name, i.number].filter(Boolean).join(" · ") || i.file || "–";
const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement && ((el instanceof HTMLInputElement && !["checkbox", "radio", "button"].includes(el.type))
    || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);

/** The text a search looks in: the card's lines and invoices. */
function searchText(g: ReconcileGroup, lines: Map<string, ReconcileLine>, invoices: Map<string, ReconcileInvoice>): string {
  const ls = g.lines.map((id) => lines.get(id)).filter((l): l is ReconcileLine => Boolean(l))
    .map((l) => [l.counterparty_name, l.memo, l.description, l.amount, show(l.amount), l.booking_date].join(" "));
  const is = g.invoices.map((id) => invoices.get(id)).filter((i): i is ReconcileInvoice => Boolean(i))
    .map((i) => [i.partner_name ?? i.supplier_name, i.number, i.amount, show(i.amount), i.issue_date, i.file].join(" "));
  return [...ls, ...is].join(" ").toLowerCase();
}

/** The pairs a card's proposal allocates at once: one line with its invoices, or one invoice with its lines. */
function proposalPlan(g: ReconcileGroup, lines: Map<string, ReconcileLine>, invoices: Map<string, ReconcileInvoice>) {
  const proposed = g.pairs.filter((p) => p.state === "proposed");
  if (!proposed.length || proposed.some((p) => p.several)) return null;
  const ls = [...new Set(proposed.map((p) => p.line_id))].map((id) => lines.get(id)).filter((l): l is ReconcileLine => Boolean(l));
  const is = [...new Set(proposed.map((p) => p.invoice_id))].map((id) => invoices.get(id)).filter((i): i is ReconcileInvoice => Boolean(i));
  const plan = planPairing(ls, is);
  return plan.ok && !plan.needsReason ? plan : null;
}

interface Props {
  ws: ReconcileWorkspace; readOnly: boolean; onWorkspace: (ws: ReconcileWorkspace) => void; reload: () => void;
  /** to the two lists, with a line selected (null: none) */
  onManual: (lineId: string | null) => void;
}

export function ReconcileCards({ ws, readOnly, onWorkspace, reload, onManual }: Props) {
  useLocale();
  const wpId = ws.workpackage_id;
  const overview = ws.overview;
  const [view, setView] = useState<View>("to_decide");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [focus, setFocus] = useState<string | null>(null);
  const [docs, setDocs] = useState<boolean | null>(null); // null: by itself (open when the selected card asks for a look)
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const lineById = useMemo(() => new Map(ws.lines.map((l) => [l.id, l])), [ws.lines]);
  const invoiceById = useMemo(() => new Map(ws.invoices.map((i) => [i.id, i])), [ws.invoices]);
  const groups = useMemo(() => overview?.groups ?? [], [overview]);
  const shown = useMemo(() => groups.filter((g) => (view === "all" || g.lists.includes(view))
    && (!q || searchText(g, lineById, invoiceById).includes(q.toLowerCase()))), [groups, view, q, lineById, invoiceById]);
  const unambiguous = useMemo(() => ws.lines.filter((l) => l.state === "proposed"
    && l.candidates.some((c) => c.proposed && !c.multiple_candidates && !c.source_review_required)).length, [ws.lines]);
  // a list a decision emptied falls back to the cards still to decide
  useEffect(() => { if (view !== "to_decide" && view !== "all" && overview && !overview.counts[view]) setView("to_decide"); }, [view, overview]);
  useEffect(() => { if (!shown.some((g) => g.id === focus)) setFocus(shown[0]?.id ?? null); }, [shown, focus]);
  useEffect(() => { setDocs(null); }, [focus]);

  async function act(fn: () => Promise<ReconcileWorkspace>, done?: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      onWorkspace(await fn());
      if (done) setNotice(done);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(t("Someone decided meanwhile; the lists have been reloaded. Check the card and try again."));
        reload();
      } else if (e instanceof ApiError && e.code === "reconcile_locked") {
        setError(t("This line is in an approved reconciliation; reopen that approval first."));
      } else setError(t("The decision could not be saved: {{reason}}", { reason: e instanceof ApiError ? e.message : String(e) }));
    } finally {
      setBusy(false);
    }
  }

  const focused = shown.find((g) => g.id === focus) ?? null;
  const keys = useRef<(e: KeyboardEvent) => void>(() => {});
  keys.current = (e: KeyboardEvent) => {
    if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
    const onButton = e.target instanceof HTMLElement && (e.target.tagName === "BUTTON" || e.target.tagName === "A");
    const at = focused ? shown.indexOf(focused) : -1;
    if (e.key === "ArrowDown" || e.key === "j" || e.key === "ArrowUp" || e.key === "k") {
      e.preventDefault();
      const next = shown[e.key === "ArrowDown" || e.key === "j" ? Math.min(shown.length - 1, at + 1) : Math.max(0, at - 1)];
      if (next) { setFocus(next.id); if (shown.indexOf(next) >= limit) setLimit((n) => n + PAGE); }
    } else if (e.key === "Enter" && !onButton && focused && !readOnly) {
      const plan = proposalPlan(focused, lineById, invoiceById);
      if (plan) { e.preventDefault(); void act(() => api.reconcileAllocate(wpId, toRequest(plan.pairs)), t("The proposal has been accepted.")); }
    } else if (e.key === "d" && focused) setDocs((v) => !(v ?? focused.flags.some((f) => CLARIFY.has(f))));
  };
  useEffect(() => {
    const on = (e: KeyboardEvent) => keys.current(e);
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  if (!overview) return <p className="muted">{t("Loading…")}</p>;
  return (
    <div className="rc-stack">
      <div className="rc-toolbar" role="toolbar" aria-label={t("Lists")}>
        <span className="chip-row" role="group" aria-label={t("Cards by list")}>
          {VIEWS.filter((v) => v === "to_decide" || v === "all" || overview.counts[v]).map((v) => (
            <button key={v} type="button" className={`chip${["overdue", "double_payment", "late"].includes(v) && overview.counts[v] ? " rc-chip-warn" : ""}`}
              aria-pressed={view === v} onClick={() => { setView(v); setLimit(PAGE); }}>
              {/* 153 (review): the chips count cards; the header and the lists count lines */}
              {CARD_LIST[v]} ({t("{{n}} card(s)", { n: overview.counts[v] ?? 0 })})
            </button>
          ))}
        </span>
      </div>
      <div className="rc-toolbar">
        <input type="search" placeholder={t("Search partner, supplier, number, amount")} aria-label={t("Search the cards")} value={q}
          onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} />
        <span className="spacer" />
        {!readOnly && unambiguous ? (
          <ConfirmButton className="secondary" disabled={busy} onConfirm={() => void act(() => api.reconcileAcceptProposed(wpId), t("The unambiguous proposals have been accepted."))}>
            {t("Accept the {{n}} unambiguous proposals", { n: unambiguous })}
          </ConfirmButton>
        ) : null}
        <button type="button" className="secondary" onClick={() => onManual(null)}>{t("Two lists (pair by hand)")}</button>
      </div>
      {view === "overdue" ? <p className="small muted">{t("The statements show nothing about cash or another account: an invoice here had no payment found on the package's statements up to the day they cover it.")}</p> : null}
      {view === "double_payment" ? <p className="small muted">{t("Two or more transfers each look like the full payment of the same invoice. It may be a double payment, or the invoice of another month is missing.")}</p> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {notice ? <p className="small ok" role="status">{notice}</p> : null}

      <div className="rc-cards" aria-label={t("Cards")}>
        {shown.slice(0, limit).map((g) => (
          <GroupCard key={g.id} group={g} lines={lineById} invoices={invoiceById} facts={overview.invoices} ws={ws}
            focused={g.id === focus} docs={g.id === focus && (docs ?? g.flags.some((f) => CLARIFY.has(f)))}
            readOnly={readOnly} busy={busy} act={act} onFocus={() => setFocus(g.id)}
            onDocs={() => { setFocus(g.id); setDocs((v) => (g.id === focus ? !(v ?? g.flags.some((f) => CLARIFY.has(f))) : true)); }}
            onManual={onManual} />
        ))}
        {!shown.length ? <p className="muted small">{t("No card in this list.")}</p> : null}
        {shown.length > limit ? (
          <button type="button" className="quiet small-btn" onClick={() => setLimit((n) => n + PAGE)}>{t("Show {{n}} more", { n: Math.min(PAGE, shown.length - limit) })}</button>
        ) : null}
      </div>
    </div>
  );
}

type Act = (fn: () => Promise<ReconcileWorkspace>, done?: string) => Promise<void>;

function GroupCard({ group: g, lines, invoices, facts, ws, focused, docs, readOnly, busy, act, onFocus, onDocs, onManual }: {
  group: ReconcileGroup; lines: Map<string, ReconcileLine>; invoices: Map<string, ReconcileInvoice>;
  facts: Record<string, ReconcileInvoiceFacts>; ws: ReconcileWorkspace; focused: boolean; docs: boolean; readOnly: boolean; busy: boolean;
  act: Act; onFocus: () => void; onDocs: () => void; onManual: (lineId: string | null) => void;
}) {
  useLocale();
  const ref = useRef<HTMLElement>(null);
  useEffect(() => { if (focused) ref.current?.scrollIntoView?.({ block: "nearest" }); }, [focused]);
  const [mode, setMode] = useState<null | { kind: "mark"; lines: string[] } | { kind: "reject"; pair: ReconcileGroupPair }>(null);
  const [docLine, setDocLine] = useState<string | null>(null);
  const [docInvoice, setDocInvoice] = useState<string | null>(null);
  const ls = g.lines.map((id) => lines.get(id)).filter((l): l is ReconcileLine => Boolean(l));
  const is = g.invoices.map((id) => invoices.get(id)).filter((i): i is ReconcileInvoice => Boolean(i));
  const wpId = ws.workpackage_id;
  const plan = readOnly ? null : proposalPlan(g, lines, invoices);
  const oneCurrency = new Set([...ls.map((l) => l.currency), ...is.map((i) => i.currency)]).size <= 1;
  const lineTotal = sum(ls.map(signed));
  const invoiceTotal = sum(is.map((i) => parseCanonical(i.amount)));
  const currency = ls[0]?.currency ?? is[0]?.currency ?? null;
  const name = ls[0] ? lineTitle(ls[0]) : is[0] ? invoiceTitle(is[0]) : "–";
  const open = ls.filter(markable);
  // an invoice without a payment: the lines code found for it without proposing one, shown in full beside it
  const options = ls.length ? [] : [...new Set(is.flatMap((i) => i.candidates.filter((c) => !c.proposed).map((c) => c.line_id)))]
    .map((id) => lines.get(id)).filter((l): l is ReconcileLine => Boolean(l)).slice(0, 3);
  const lineDoc = (docLine ? lines.get(docLine) : null) ?? lines.get(g.pairs[0]?.line_id ?? "") ?? ls[0] ?? options[0] ?? null;
  const invoiceDoc = (docInvoice ? invoices.get(docInvoice) : null) ?? invoices.get(g.pairs.find((p) => p.line_id === lineDoc?.id)?.invoice_id ?? "") ?? is[0] ?? null;

  function acceptOne(p: ReconcileGroupPair) {
    const line = lines.get(p.line_id);
    const combined = line?.candidates.find((c) => c.invoice_id === p.invoice_id)?.combined;
    const group = (combined ?? [p.invoice_id]).map((id) => invoices.get(id)).filter((i): i is ReconcileInvoice => Boolean(i));
    const one = line ? planPairing([line], group) : null;
    if (one?.ok && !one.needsReason) void act(() => api.reconcileAllocate(wpId, toRequest(one.pairs)), t("The proposal has been accepted."));
    else onManual(p.line_id);
  }

  return (
    <article ref={ref} className={`rc-card k-${g.kind}${focused ? " focused" : ""}`} aria-label={`${GROUP_KIND[g.kind]}: ${name}`}
      aria-current={focused ? "true" : undefined} onClick={(e) => { if (!(e.target instanceof HTMLElement && e.target.closest("button, a, input, textarea, select, label"))) onFocus(); }}>
      <header className="rc-card-head">
        <span className={`rc-kind k-${g.kind}`}>{GROUP_KIND[g.kind]}</span>
        <span className="rc-date">{g.date || "–"}</span>
        <strong className="rc-card-name">{name}</strong>
        {g.flags.filter((f) => f !== "late").map((f) => (
          <span key={f} className={`rc-sig ${["overdue", "double_payment", "amount_differs", "several_candidates", "statement_unverified", "rest_left"].includes(f) ? "warn" : ""}`}>{FLAG[f]}</span>
        ))}
        {g.flags.includes("late") ? <span className="rc-sig late">{FLAG.late}</span> : null}
      </header>

      <div className="rc-card-cols">
        <section className="rc-card-side" aria-label={t("Transfers")}>
          <h3>{ls.length > 1 ? t("Transfers ({{n}})", { n: ls.length }) : t("Transfer")}</h3>
          {ls.map((l) => <LineFacts key={l.id} line={l} repeat={g.pairs.some((p) => p.line_id === l.id && p.state === "repeat")} invoices={invoices} />)}
          {!ls.length && options.length ? (
            <>
              <p className="small warn-text">{t("Not paired; code found these transfers for it:")}</p>
              {options.map((l) => <LineFacts key={l.id} line={l} repeat={false} invoices={invoices} />)}
            </>
          ) : null}
          {!ls.length && !options.length ? <p className="muted small">{t("No transfer on the package's statements.")}</p> : null}
        </section>
        <section className="rc-card-side" aria-label={t("Invoices")}>
          <h3>{is.length > 1 ? t("Invoices ({{n}})", { n: is.length }) : t("Invoice")}</h3>
          {is.map((i) => <InvoiceFacts key={i.id} invoice={i} facts={facts[i.id]} lines={lines} />)}
          {!is.length ? <NoInvoice lines={ls} invoices={invoices} /> : null}
        </section>
      </div>

      {g.pairs.length ? (
        <table className="rc-pairs">
          <thead><tr><th>{t("Transfer")}</th><th>{t("Invoice")}</th><th className="num">{t("Amount")}</th><th>{t("Against the due date")}</th><th>{t("State")}</th><th /></tr></thead>
          <tbody>
            {g.pairs.map((p) => {
              const l = lines.get(p.line_id);
              const i = invoices.get(p.invoice_id);
              return (
                <tr key={`${p.line_id}|${p.invoice_id}|${p.state}`}>
                  <td>{l ? `${l.booking_date ?? "–"} · ${display(l ? signed(l) : null, l?.currency)}` : "–"}</td>
                  <td>{i ? `${i.number ?? i.file ?? "–"} · ${show(i.amount, i.currency)}` : "–"}</td>
                  <td className="num">{p.state === "allocated" ? show(p.line_amount, l?.currency) : p.state === "proposed" ? relationText(p.relation ?? null) : "–"}</td>
                  <td>{p.state === "repeat" ? "–" : <span className={(p.days_from_due ?? 0) > 0 ? "rc-late" : p.days_from_due === null ? "muted" : "ok"}>{dueText(p.days_from_due)}</span>}</td>
                  <td>{p.state === "allocated" ? t("Paired") : p.state === "proposed" ? (p.several ? t("Proposed (several candidates)") : t("Proposed")) : <span className="warn-text">{t("May repeat the payment")}</span>}</td>
                  <td className="rc-pair-actions">
                    {readOnly ? null : p.state === "proposed" ? (
                      <>
                        {p.several || !plan ? <button type="button" className="secondary small-btn" disabled={busy} onClick={() => acceptOne(p)}>{t("Accept this one")}</button> : null}
                        <button type="button" className="quiet small-btn" disabled={busy} onClick={() => setMode({ kind: "reject", pair: p })}>{t("Not this one")}</button>
                      </>
                    ) : p.state === "allocated" ? (
                      <button type="button" className="quiet small-btn" disabled={busy}
                        onClick={() => void act(() => api.reconcileRevoke(wpId, p.allocation_id != null ? "allocation" : "decision",
                          p.allocation_id != null ? String(p.allocation_id) : `${p.invoice_id}|${p.line_id}`), t("The decision has been undone."))}>
                        {t("Undo")}
                      </button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}

      <footer className="rc-card-foot">
        {ls.length ? <span className="rc-sum">{t("Transfers")}: <strong>{display(lineTotal, ls[0].currency)}</strong></span> : null}
        {is.length ? <span className="rc-sum">{t("Invoices")}: <strong>{oneCurrency ? display(invoiceTotal, is[0].currency) : t("several currencies")}</strong></span> : null}
        {ls.length && is.length && oneCurrency ? <Difference paid={-lineTotal} invoiced={invoiceTotal} currency={currency} /> : null}
        <span className="spacer" />
        {plan ? (
          <button type="button" className="primary" disabled={busy}
            onClick={() => void act(() => api.reconcileAllocate(wpId, toRequest(plan.pairs)), t("The proposal has been accepted."))}>
            {t("Accept")} <span className="kbd">Enter</span>
          </button>
        ) : null}
        {!readOnly && open.length ? (
          <button type="button" className="secondary" disabled={busy} onClick={() => setMode({ kind: "mark", lines: open.map((l) => l.id) })}>
            {open.length > 1 ? t("Needs no invoice ({{n}})", { n: open.length }) : t("Needs no invoice")}
          </button>
        ) : null}
        {!readOnly && ls.some((l) => l.mark) ? (
          <button type="button" className="quiet" disabled={busy}
            onClick={() => void act(() => api.reconcileUnmark(wpId, ls.filter((l) => l.mark).map((l) => l.id)), t("The marks have been undone."))}>
            {t("Undo the mark")}
          </button>
        ) : null}
        {!readOnly && (g.kind === "line_only" || g.kind === "invoice_only" || g.flags.includes("double_payment")) ? (
          <button type="button" className="quiet" onClick={() => onManual(open[0]?.id ?? null)}>{t("Pair by hand")}</button>
        ) : null}
        <button type="button" className="secondary" aria-expanded={docs} onClick={onDocs}>{t("Documents")} <span className="kbd">d</span></button>
      </footer>

      {mode?.kind === "mark" ? (
        <MarkPanel count={mode.lines.length} categories={ws.line_marks} suggestion={suggestMark(open)} busy={busy} onCancel={() => setMode(null)}
          onSave={(category, note) => void act(() => api.reconcileMark(wpId, mode.lines, category, note), t("The lines have been marked."))} />
      ) : null}
      {mode?.kind === "reject" ? (
        <ReasonPanel label={t("Why is this invoice not paid by this line?")} action={t("Save the rejection")} busy={busy} onCancel={() => setMode(null)}
          onSave={(note) => void act(() => api.reconcileReject(wpId, mode.pair.invoice_id, mode.pair.line_id, note), t("The candidate has been rejected."))} />
      ) : null}

      {docs ? (
        <div className="rc-card-docs">
          {ls.length > 1 || is.length > 1 || options.length > 1 ? (
            <div className="rc-doc-pick small">
              {ls.length > 1 || options.length > 1 ? (ls.length ? ls : options).map((l) => (
                <button key={l.id} type="button" className="chip" aria-pressed={lineDoc?.id === l.id} onClick={() => setDocLine(l.id)}>
                  {l.booking_date} · {display(signed(l), l.currency)}
                </button>
              )) : null}
              {is.length > 1 ? is.map((i) => (
                <button key={i.id} type="button" className="chip" aria-pressed={invoiceDoc?.id === i.id} onClick={() => setDocInvoice(i.id)}>
                  {i.number ?? i.file ?? "–"}
                </button>
              )) : null}
            </div>
          ) : null}
          <DocumentPair wpId={wpId} line={lineDoc} invoice={invoiceDoc} opens={ws.open} />
        </div>
      ) : null}
    </article>
  );
}

/** The card's transfers against its invoices, in words: equal, transferred more, or part of the invoices not paid. */
function Difference({ paid, invoiced, currency }: { paid: bigint; invoiced: bigint; currency: string | null }) {
  useLocale();
  const diff = paid - invoiced;
  if (diff === 0n) return <span className="rc-sum rc-diff zero">{t("The transfers match the invoices")}</span>;
  return (
    <span className="rc-sum rc-diff off">
      {diff > 0n ? t("Transferred {{amount}} more than invoiced", { amount: display(diff, currency) })
        : t("{{amount}} of the invoices is not paid by these transfers", { amount: display(-diff, currency) })}
    </span>
  );
}

function InvoiceFacts({ invoice: i, facts, lines }: { invoice: ReconcileInvoice; facts?: ReconcileInvoiceFacts; lines: Map<string, ReconcileLine> }) {
  useLocale();
  const partly = parseCanonical(i.allocated) !== 0n && i.state !== "confirmed";
  return (
    <div className="rc-facts">
      <div className="rc-facts-head">
        <span className="rc-amount">{show(i.amount, i.currency)}</span>
        <span className={`rc-state s-${i.state ?? "none"}`}>{INVOICE_STATE[i.state ?? ""] ?? i.state ?? "–"}</span>
        {i.own === false && i.party ? <span className="rc-sig warn">{t("Other party: {{party}}", { party: i.party.name })}</span> : null}
        {i.outgoing ? <span className="rc-sig">{t("Outgoing invoice")}</span> : null}
      </div>
      <Timing invoice={i} facts={facts} />
      <dl>
        {i.outgoing ? <Fact label={t("Buyer")}>{i.partner_name || "–"}</Fact> : null}
        <Fact label={t("Supplier")}>{i.supplier_name || "–"}</Fact>
        {i.supplier_tax_id ? <Fact label={t("Tax number")}>{i.supplier_tax_id}</Fact> : null}
        <Fact label={t("Invoice number")}>{i.number || "–"}</Fact>
        <Fact label={t("Issue date")}>{i.issue_date ?? "–"}</Fact>
        {i.fulfillment_date ? <Fact label={t("Fulfilment date")}>{i.fulfillment_date}</Fact> : null}
        <Fact label={t("Due date")}>{i.due_date ?? t("none on the invoice")}</Fact>
        {i.net_total ? <Fact label={t("Net")}>{show(i.net_total, i.currency)}</Fact> : null}
        {i.vat_total ? <Fact label={t("VAT")}>{show(i.vat_total, i.currency)}</Fact> : null}
        {partly ? <Fact label={t("Left to pay")}>{show(i.rest, i.currency)}</Fact> : null}
        {i.payment_method ? <Fact label={t("Payment method")}>{i.payment_method}</Fact> : null}
        {i.payment_account ? <Fact label={t("Supplier's account")}>{i.payment_account}</Fact> : null}
        {i.references?.length ? <Fact label={t("References")}>{i.references.join(", ")}</Fact> : null}
        {i.buyer_name ? <Fact label={t("Buyer")}>{i.buyer_name}</Fact> : null}
        {i.credited_by ? <Fact label={t("Credit note")}>{i.credited_by.number ?? "–"}</Fact> : null}
        <Fact label={t("File")}>{i.file ?? "–"}{i.source !== "approved" ? ` · ${i.source === "no_run" ? t("command line") : t("run not approved")}`: ""}</Fact>
      </dl>
      {/* the other possible lines, only while nothing is paid or proposed for the invoice */}
      {i.candidates.length && !["confirmed", "proposed", "credited", "partly_paid"].includes(i.state ?? "") ? <InvoiceOptions invoice={i} lines={lines} /> : null}
    </div>
  );
}

/** An invoice's payment against its due date: paid (and how late), overdue with no payment found, or not checkable. */
function Timing({ invoice: i, facts }: { invoice: ReconcileInvoice; facts?: ReconcileInvoiceFacts }) {
  useLocale();
  if (!facts || i.state === "credited" || i.state === "excluded") return null;
  if (facts.overdue_days !== null) {
    return (
      <p className="rc-timing warn-text">
        {t("Overdue, no payment found: {{n}} days after the due date, by {{day}} (the last day the statements cover it)", {
          n: facts.overdue_days, day: facts.checked_until ?? "–" })}
      </p>
    );
  }
  if (facts.paid_on) {
    const late = (facts.days_from_due ?? 0) > 0;
    return (
      <p className={`rc-timing ${late ? "rc-late" : ""}`}>
        {i.state === "confirmed" ? t("Paid on {{day}}", { day: facts.paid_on }) : t("Proposed payment on {{day}}", { day: facts.paid_on })}
        {" · "}{dueText(facts.days_from_due)}
      </p>
    );
  }
  if (i.state === "partly_covered" || i.state === "not_covered") {
    return <p className="rc-timing muted">{t("The statements do not cover its whole period, so a missing payment cannot be told.")}</p>;
  }
  return null;
}

/** The lines an invoice's code found without proposing them (same amount only, a different amount). */
function InvoiceOptions({ invoice, lines }: { invoice: ReconcileInvoice; lines: Map<string, ReconcileLine> }) {
  useLocale();
  const options = invoice.candidates.filter((c) => !c.proposed && lines.has(c.line_id));
  if (!options.length) return null;
  return (
    <p className="small muted rc-options">
      {t("Possible transfers")}: {options.map((c) => {
        const l = lines.get(c.line_id)!;
        const ties = c.signals.map((s) => SIGNAL[s] ?? s).join(", ");
        return `${l.booking_date} · ${display(signed(l), l.currency)} (${c.amount_only ? t("same amount only") : relationText(c.amount_relation)}${ties ? `; ${ties}` : ""})`;
      }).join(" · ")}
    </p>
  );
}

/** A card with a transfer and no invoice: the invoices code found for it without proposing one. */
function NoInvoice({ lines, invoices }: { lines: ReconcileLine[]; invoices: Map<string, ReconcileInvoice> }) {
  useLocale();
  const options = lines.flatMap((l) => rankedCandidates(l).filter((c) => !c.proposed && invoices.has(c.invoice_id) && !l.rejected.includes(c.invoice_id)));
  if (!options.length) {
    return <p className="muted small">{lines.some((l) => l.state === "excluded" || l.state === "marked") ? t("No invoice needed.") : t("No invoice found for this transfer.")}</p>;
  }
  return (
    <div className="small">
      <p className="muted">{t("No proposal; possible invoices:")}</p>
      <ul className="plain">
        {options.map((c) => {
          const i = invoices.get(c.invoice_id)!;
          return (
            <li key={`${c.line_id}|${c.invoice_id}`}>
              {invoiceTitle(i)} · {show(i.amount, i.currency)} · <span className="warn-text">{c.amount_only ? t("same amount only") : relationText(c.amount_relation)}</span>
              {c.signals.length ? ` · ${c.signals.map((s) => SIGNAL[s] ?? s).join(", ")}` : ""}
            </li>
          );
        })}
      </ul>
      <p className="muted">{t("Pair them by hand after checking the documents.")}</p>
    </div>
  );
}
