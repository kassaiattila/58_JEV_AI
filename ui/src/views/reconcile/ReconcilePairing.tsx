// 132 (backlog F-reconciliation E2): the pairing page of a reconciliation package — statement lines on the left,
// invoices on the right (the owner's choice of 2026-10-09). The selected line's candidates stand at the top of the
// invoice list, highlighted, with what ties them. Several lines or invoices can be selected; the bar at the bottom
// shows the totals and the difference, and pairs them (one line with several invoices or one invoice with several
// lines, with an amount per pair and a reason when a rest is left), rejects a candidate with a reason, or marks the
// selected lines as needing no invoice — several at once, because most lines of a real statement need none
// (DECISIONS 132). Every decision can be undone from the line's details. Keyboard: arrows or j/k move, Space selects,
// 1–9 picks a candidate, Enter pairs, x rejects, m marks, d shows the documents, Esc clears, ? lists the keys.
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  api, ApiError, OPEN_LINE_STATES, type ReconcileCandidate, type ReconcileInvoice, type ReconcileLine, type ReconcileLineState,
  type ReconcileWorkspace,
} from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { t, useLocale } from "../../i18n";
import { tmap } from "../../labels";
import { DocumentPair } from "./DocumentPair";
import { EXCLUDED, INVOICE_STATE, LINE_STATE, MARK, relationText, SIGNAL } from "./labels";
import { display, parseCanonical, parseInput, show, sum } from "./money";
import { candidateOf, check, planPairing, rankedCandidates, rest, toRequest, type PlannedPair, type Plan, type Refusal } from "./pairing";

type LineFilter = "todo" | "all" | ReconcileLineState;
type Mode = null | "pair" | "reject" | "mark" | "keys";
const PAGE = 300;
const FILTERS: LineFilter[] = ["todo", "proposed", "amount_only", "partly_allocated", "open", "allocated", "marked", "excluded", "all"];

const REFUSAL: Record<Refusal, string> = tmap({
  nothing: "Select a statement line and an invoice.",
  many_to_many: "Select one line with one or more invoices, or one invoice with one or more lines.",
  line_marked: "A selected line is marked as needing no invoice; undo the mark first.",
  line_excluded: "A selected line is left out of the pairing (an incoming payment, a fee or a transfer between own accounts).",
  line_settled: "A selected line is already paired in full.",
  invoice_settled: "A selected invoice is already paid in full.",
  currency: "A line and an invoice of different currencies pair only one to one and in whole, when the card's conversion relates them.",
  too_many: "The amount does not reach every selected item; select fewer.",
}) as Record<Refusal, string>;

const signed = (line: ReconcileLine): bigint | null => {
  const v = parseCanonical(line.amount);
  return v === null ? null : line.direction === "credit" ? v : -v;
};
const lineTitle = (l: ReconcileLine) => l.counterparty_name || l.description || l.memo || "–";
const invoiceTitle = (i: ReconcileInvoice) => [i.supplier_name, i.number].filter(Boolean).join(" · ") || i.file || "–";
/** Whether the key goes into a text field (a checkbox or a radio button with the focus does not take letters). */
const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement && ((el instanceof HTMLInputElement && !["checkbox", "radio", "button"].includes(el.type))
    || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);

function filterLabel(f: LineFilter): string {
  if (f === "todo") return t("To decide");
  if (f === "all") return t("All");
  return LINE_STATE[f];
}

function matches(line: ReconcileLine, q: string): boolean {
  if (!q) return true;
  const hay = [line.counterparty_name, line.description, line.memo, line.amount, show(line.amount), line.booking_date].join(" ").toLowerCase();
  return hay.includes(q.toLowerCase());
}

function invoiceMatches(inv: ReconcileInvoice, q: string): boolean {
  if (!q) return true;
  const hay = [inv.supplier_name, inv.number, inv.amount, show(inv.amount), inv.file, inv.issue_date].join(" ").toLowerCase();
  return hay.includes(q.toLowerCase());
}

interface Props { ws: ReconcileWorkspace; readOnly: boolean; onWorkspace: (ws: ReconcileWorkspace) => void; reload: () => void }

export function ReconcilePairing({ ws, readOnly, onWorkspace, reload }: Props) {
  useLocale();
  const wpId = ws.workpackage_id;
  const [filter, setFilter] = useState<LineFilter>("todo");
  const [account, setAccount] = useState("");
  const [month, setMonth] = useState("");
  const [q, setQ] = useState("");
  const [invQ, setInvQ] = useState("");
  const [unpaidOnly, setUnpaidOnly] = useState(true);
  const [limit, setLimit] = useState(PAGE);
  const [active, setActive] = useState<string | null>(null);
  const [selLines, setSelLines] = useState<string[]>([]);
  const [selInvoices, setSelInvoices] = useState<string[]>([]);
  const [mode, setMode] = useState<Mode>(null);
  const [showDocs, setShowDocs] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const advanceFrom = useRef<number | null>(null);
  const lastIndex = useRef(0);

  const lineById = useMemo(() => new Map(ws.lines.map((l) => [l.id, l])), [ws.lines]);
  const invoiceById = useMemo(() => new Map(ws.invoices.map((i) => [i.id, i])), [ws.invoices]);
  const months = useMemo(() => [...new Set(ws.lines.map((l) => (l.booking_date ?? "").slice(0, 7)).filter(Boolean))].sort(), [ws.lines]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: ws.lines.length, todo: 0 };
    for (const l of ws.lines) {
      c[l.state] = (c[l.state] ?? 0) + 1;
      if (OPEN_LINE_STATES.includes(l.state)) c.todo += 1;
    }
    return c;
  }, [ws.lines]);
  const visible = useMemo(() => ws.lines.filter((l) =>
    (filter === "all" || (filter === "todo" ? OPEN_LINE_STATES.includes(l.state) : l.state === filter))
    && (!account || l.account === account) && (!month || (l.booking_date ?? "").startsWith(month)) && matches(l, q)), [ws.lines, filter, account, month, q]);
  const activeLine = active ? lineById.get(active) ?? null : null;
  // a state filter that a decision emptied falls back to the lines still to decide (its chip would vanish otherwise)
  useEffect(() => { if (filter !== "todo" && filter !== "all" && !counts[filter]) setFilter("todo"); }, [filter, counts]);
  const unambiguous = useMemo(() => ws.lines.filter((l) => l.state === "proposed"
    && l.candidates.some((c) => c.proposed && !c.multiple_candidates && !c.source_review_required)).length, [ws.lines]);

  // the cursor stays on its line while the line is listed; when it leaves the list (decided, filtered out), the line now
  // at its place takes the cursor; after a decision the cursor moves on to the next line
  useEffect(() => {
    const ids = visible.map((l) => l.id);
    const at = active ? ids.indexOf(active) : -1;
    let next: string | undefined;
    if (advanceFrom.current !== null) {
      const from = advanceFrom.current;
      advanceFrom.current = null;
      next = at >= 0 ? ids[at + 1] ?? ids[at] : ids[Math.min(from, ids.length - 1)];
    } else if (at >= 0) {
      lastIndex.current = at;
      return;
    } else next = ids[Math.min(lastIndex.current, ids.length - 1)];
    setActive(next ?? null);
    setSelLines(next ? [next] : []); // the selection follows the cursor to a new line
    setSelInvoices([]);
  }, [visible, active]);

  const lines = selLines.map((id) => lineById.get(id)).filter((l): l is ReconcileLine => Boolean(l));
  const invoices = selInvoices.map((id) => invoiceById.get(id)).filter((i): i is ReconcileInvoice => Boolean(i));
  const plan = planPairing(lines, invoices);
  const oneCurrency = new Set([...lines.map((l) => l.currency), ...invoices.map((i) => i.currency)]).size <= 1;
  const sideTotal = (items: { currency: string | null }[], total: bigint) =>
    !items.length ? "–" : new Set(items.map((x) => x.currency)).size > 1 ? t("several currencies") : display(total, items[0].currency);
  const lineSum = sum(lines.map(rest));
  const invoiceSum = sum(invoices.map(rest));
  const pairCandidate = lines.length === 1 && invoices.length === 1 ? candidateOf(lines[0], invoices[0].id) : undefined;
  const canReject = Boolean(pairCandidate) && !lines[0]?.allocations.some((a) => a.invoice_id === invoices[0]?.id);
  const canMark = lines.length > 0 && invoices.length === 0 && lines.every((l) => l.state !== "allocated" && parseCanonical(l.allocated) === 0n);

  function choose(id: string, additive: boolean) {
    setActive(id);
    if (additive) setSelLines((sel) => (sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]));
    else {
      if (id !== active) setSelInvoices([]);
      setSelLines([id]);
    }
    setMode((m) => (m === "keys" ? m : null));
  }

  const toggleInvoice = (id: string) => setSelInvoices((sel) => (sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]));

  async function act(fn: () => Promise<ReconcileWorkspace>, opts: { advance?: boolean; done?: string } = {}) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await fn();
      if (opts.advance) advanceFrom.current = Math.max(0, visible.findIndex((l) => l.id === active));
      setSelInvoices([]);
      setMode(null);
      onWorkspace(next);
      if (opts.done) setNotice(opts.done);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(t("Someone decided meanwhile; the lists have been reloaded and your selection kept. Check it and try again."));
        reload();
      } else setError(t("The decision could not be saved: {{reason}}", { reason: e instanceof ApiError ? e.message : String(e) }));
    } finally {
      setBusy(false);
    }
  }

  function pair() {
    if (readOnly || !plan.ok) return;
    if (!plan.needsReason) {
      void act(() => api.reconcileAllocate(wpId, toRequest(plan.pairs)), { advance: true });
      return;
    }
    setMode("pair");
  }

  // the keyboard works while no text field has the focus (Esc always)
  const keys = useRef<(e: KeyboardEvent) => void>(() => {});
  keys.current = (e: KeyboardEvent) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "Escape") {
      if (mode) setMode(null);
      else { setSelLines(active ? [active] : []); setSelInvoices([]); }
      return;
    }
    if (isTyping(e.target)) return;
    // Enter and Space keep their own meaning on a button or a link; Space also toggles a focused checkbox itself
    const onButton = e.target instanceof HTMLElement && (e.target.tagName === "BUTTON" || e.target.tagName === "A");
    const onCheckbox = e.target instanceof HTMLInputElement;
    const ids = visible.map((l) => l.id);
    const at = active ? ids.indexOf(active) : -1;
    if (e.key === "ArrowDown" || e.key === "j" || e.key === "ArrowUp" || e.key === "k") {
      e.preventDefault();
      const next = ids[e.key === "ArrowDown" || e.key === "j" ? Math.min(ids.length - 1, at + 1) : Math.max(0, at - 1)];
      if (next) choose(next, false);
    } else if (e.key === " " && !onButton && !onCheckbox && active) {
      e.preventDefault();
      setSelLines((sel) => (sel.includes(active) ? sel.filter((x) => x !== active) : [...sel, active]));
    } else if (/^[1-9]$/.test(e.key) && activeLine) {
      const c = rankedCandidates(activeLine).filter((x) => !activeLine.rejected.includes(x.invoice_id))[Number(e.key) - 1];
      if (c) toggleInvoice(c.invoice_id);
    } else if (e.key === "Enter" && !onButton) {
      e.preventDefault();
      pair();
    } else if (e.key === "x" && canReject && !readOnly) setMode("reject");
    else if (e.key === "m" && canMark && !readOnly) setMode("mark");
    else if (e.key === "d") setShowDocs((v) => !v);
    else if (e.key === "?") setMode((m) => (m === "keys" ? null : "keys"));
  };
  useEffect(() => {
    const on = (e: KeyboardEvent) => keys.current(e);
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  // the invoice list: the active line's candidates first, then the rest (unpaid ones by default)
  const candidates = activeLine ? rankedCandidates(activeLine).filter((c) => !activeLine.rejected.includes(c.invoice_id) && invoiceById.has(c.invoice_id)) : [];
  const candidateIds = new Set(candidates.map((c) => c.invoice_id));
  // without a search, the invoices nearest to the selected line's amount come first (same currency before others), so
  // the payment of a line without a candidate is found by eye; otherwise the newest first
  const others = ws.invoices.filter((i) => !candidateIds.has(i.id) && invoiceMatches(i, invQ)
    && (!unpaidOnly || (i.state !== "confirmed" && rest(i) > 0n) || selInvoices.includes(i.id)));
  const byAmount = Boolean(activeLine) && !invQ;
  if (byAmount && activeLine) {
    const target = rest(activeLine);
    const distance = (i: ReconcileInvoice) => { const d = rest(i) - target; return d < 0n ? -d : d; };
    others.sort((a, b) => Number(a.currency !== activeLine.currency) - Number(b.currency !== activeLine.currency)
      || (distance(a) < distance(b) ? -1 : distance(a) > distance(b) ? 1 : 0));
  } else others.sort((a, b) => (b.issue_date ?? "").localeCompare(a.issue_date ?? ""));
  const docInvoice = invoices[0] ?? (candidates[0] ? invoiceById.get(candidates[0].invoice_id) ?? null : null);
  const differs = oneCurrency && lines.length > 0 && invoices.length > 0 ? lineSum - invoiceSum : null;
  const currency = lines[0]?.currency ?? invoices[0]?.currency ?? null;

  return (
    <div className="rc-stack">
      <div className="rc-toolbar" role="toolbar" aria-label={t("Filters")}>
        <span className="chip-row" role="group" aria-label={t("Lines by state")}>
          {FILTERS.filter((f) => f === "todo" || f === "all" || counts[f]).map((f) => (
            <button key={f} type="button" className="chip" aria-pressed={filter === f} onClick={() => { setFilter(f); setLimit(PAGE); }}>
              {filterLabel(f)} ({counts[f] ?? 0})
            </button>
          ))}
        </span>
        <span className="spacer" />
        {!readOnly && unambiguous ? (
          <ConfirmButton className="secondary" disabled={busy} onConfirm={() => void act(() => api.reconcileAcceptProposed(wpId), { done: t("The unambiguous proposals have been accepted.") })}>
            {t("Accept the {{n}} unambiguous proposals", { n: unambiguous })}
          </ConfirmButton>
        ) : null}
        <button type="button" className="secondary" aria-pressed={showDocs} onClick={() => setShowDocs((v) => !v)}>{t("Documents")} <span className="kbd">d</span></button>
        <button type="button" className="quiet" aria-expanded={mode === "keys"} onClick={() => setMode((m) => (m === "keys" ? null : "keys"))}>{t("Keys")} <span className="kbd">?</span></button>
      </div>

      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {notice ? <p className="small ok" role="status">{notice}</p> : null}

      <div className="rc-grid">
        <section className="rc-pane" aria-label={t("Statement lines")}>
          <div className="rc-pane-head">
            <h2>{t("Statement lines")}</h2>
            <input type="search" placeholder={t("Search name, memo, amount")} aria-label={t("Search the lines")} value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} />
            {ws.scope.accounts.length > 1 ? (
              <select aria-label={t("Account or card")} value={account} onChange={(e) => setAccount(e.target.value)}>
                <option value="">{t("Every account")}</option>
                {ws.scope.accounts.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            ) : null}
            {months.length > 1 ? (
              <select aria-label={t("Month")} value={month} onChange={(e) => setMonth(e.target.value)}>
                <option value="">{t("Every month")}</option>
                {months.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : null}
            {visible.length > 1 && !readOnly ? (
              <label className="check small">
                <input type="checkbox" checked={visible.slice(0, limit).every((l) => selLines.includes(l.id))}
                  onChange={(e) => setSelLines(e.target.checked ? visible.slice(0, limit).map((l) => l.id) : active ? [active] : [])} />
                {t("Select all shown")}
              </label>
            ) : null}
          </div>
          <ul className="rc-list plain" aria-label={t("Statement lines")}>
            {visible.slice(0, limit).map((l) => (
              <LineRow key={l.id} line={l} active={l.id === active} selected={selLines.includes(l.id)} onChoose={choose} />
            ))}
            {!visible.length ? <li className="rc-more muted small">{t("No line matches the filters.")}</li> : null}
            {visible.length > limit ? (
              <li className="rc-more"><button type="button" className="quiet small-btn" onClick={() => setLimit((n) => n + PAGE)}>{t("Show {{n}} more", { n: Math.min(PAGE, visible.length - limit) })}</button></li>
            ) : null}
          </ul>
        </section>

        <section className="rc-pane" aria-label={t("Invoices")}>
          <div className="rc-pane-head">
            <h2>{t("Invoices")}</h2>
            <input type="search" placeholder={t("Search supplier, number, amount")} aria-label={t("Search the invoices")} value={invQ} onChange={(e) => setInvQ(e.target.value)} />
            <label className="check small"><input type="checkbox" checked={unpaidOnly} onChange={(e) => setUnpaidOnly(e.target.checked)} /> {t("Unpaid only")}</label>
          </div>
          <div className="rc-list">
            {activeLine ? <LineDetail line={activeLine} invoiceById={invoiceById} readOnly={readOnly} busy={busy}
              onRevoke={(kind, ref) => void act(() => api.reconcileRevoke(wpId, kind, ref), { done: t("The decision has been undone.") })} /> : null}
            {activeLine ? (
              <>
                <p className="rc-section">{candidates.length ? t("Candidates of the selected line") : t("The selected line has no candidate; search the invoices below")}</p>
                <ul className="plain">
                  {candidates.map((c, n) => {
                    const inv = invoiceById.get(c.invoice_id)!;
                    return <InvoiceRow key={inv.id} invoice={inv} candidate={c} index={n + 1} selected={selInvoices.includes(inv.id)} onToggle={toggleInvoice} readOnly={readOnly} />;
                  })}
                </ul>
              </>
            ) : null}
            <p className="rc-section">{byAmount ? t("Other invoices, nearest amount first") : t("Other invoices, newest first")}</p>
            <ul className="plain">
              {others.slice(0, PAGE).map((inv) => (
                <InvoiceRow key={inv.id} invoice={inv} selected={selInvoices.includes(inv.id)} onToggle={toggleInvoice} readOnly={readOnly} />
              ))}
              {!others.length ? <li className="rc-more muted small">{t("No invoice matches.")}</li> : null}
              {others.length > PAGE ? <li className="rc-more muted small">{t("Narrow the search to see the rest ({{n}}).", { n: others.length - PAGE })}</li> : null}
            </ul>
          </div>
        </section>
      </div>

      {readOnly ? null : (
        <section className="rc-bar" aria-label={t("Selection")}>
          <div className="rc-bar-row">
            <span className="rc-sum">{t("Lines")}: {lines.length} · <strong>{sideTotal(lines, lineSum)}</strong></span>
            <span className="rc-sum">{t("Invoices")}: {invoices.length} · <strong>{sideTotal(invoices, invoiceSum)}</strong></span>
            {differs !== null ? (
              <span className={`rc-sum rc-diff ${differs === 0n ? "zero" : "off"}`}>{t("Difference")}: {display(differs, currency)}</span>
            ) : lines.length && invoices.length ? <span className="rc-sum muted">{t("Different currencies: compared through the exchange rate")}</span> : null}
            <span className="spacer" />
            <button type="button" className="primary" disabled={busy || !plan.ok} onClick={pair}>{t("Pair")} <span className="kbd">Enter</span></button>
            <button type="button" className="secondary" disabled={busy || !canReject} aria-expanded={mode === "reject"} onClick={() => setMode(mode === "reject" ? null : "reject")}>
              {t("Not this one")} <span className="kbd">x</span>
            </button>
            <button type="button" className="secondary" disabled={busy || !canMark} aria-expanded={mode === "mark"} onClick={() => setMode(mode === "mark" ? null : "mark")}>
              {t("Needs no invoice")} <span className="kbd">m</span>
            </button>
            <button type="button" className="quiet" disabled={!lines.length && !invoices.length} onClick={() => { setSelLines(active ? [active] : []); setSelInvoices([]); setMode(null); }}>
              {t("Clear")} <span className="kbd">Esc</span>
            </button>
          </div>
          {!plan.ok && lines.length && invoices.length ? <p className="small warn-text">{REFUSAL[plan.why]}</p> : null}
          {mode === "pair" && plan.ok ? (
            <PairPanel plan={plan} busy={busy} onCancel={() => setMode(null)}
              onSave={(pairs, note) => void act(() => api.reconcileAllocate(wpId, toRequest(pairs), note), { advance: true })} />
          ) : null}
          {mode === "reject" && canReject ? (
            <ReasonPanel label={t("Why is this invoice not paid by this line?")} action={t("Save the rejection")} busy={busy} onCancel={() => setMode(null)}
              onSave={(note) => void act(() => api.reconcileReject(wpId, invoices[0].id, lines[0].id, note))} />
          ) : null}
          {mode === "mark" && canMark ? (
            <MarkPanel count={lines.length} categories={ws.line_marks} busy={busy} onCancel={() => setMode(null)}
              onSave={(category, note) => void act(() => api.reconcileMark(wpId, lines.map((l) => l.id), category, note), { advance: true })} />
          ) : null}
          {mode === "keys" ? <KeysHelp /> : null}
        </section>
      )}

      {showDocs ? <DocumentPair wpId={wpId} line={activeLine} invoice={docInvoice} opens={ws.open} /> : null}
    </div>
  );
}

function LineRow({ line, active, selected, onChoose }: {
  line: ReconcileLine; active: boolean; selected: boolean; onChoose: (id: string, additive: boolean) => void;
}) {
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => { if (active) ref.current?.scrollIntoView?.({ block: "nearest" }); }, [active]);
  const amount = signed(line);
  const partly = parseCanonical(line.allocated) !== 0n && line.state !== "allocated";
  return (
    <li ref={ref} className={`rc-row${active ? " active" : ""}${selected ? " is-selected" : ""}`} aria-current={active ? "true" : undefined}>
      <input type="checkbox" checked={selected} aria-label={t("Select the line {{name}}", { name: lineTitle(line) })} onChange={() => onChoose(line.id, true)} />
      <button type="button" className="rc-rowbody" onClick={(e) => onChoose(line.id, e.ctrlKey || e.metaKey || e.shiftKey)}>
        <span className="rc-date">{line.booking_date ?? "–"}</span>
        <span className={`rc-amount${amount !== null && amount > 0n ? " credit" : ""}`}>{display(amount, line.currency)}</span>
        <span className="rc-text">
          <span className="rc-main">{lineTitle(line)}</span>
          <span className="rc-sub">{[line.memo, line.description].filter((x) => x && x !== lineTitle(line)).join(" · ") || line.file}</span>
        </span>
        <span className="rc-side">
          <span className={`rc-state s-${line.state}`}>{LINE_STATE[line.state] ?? line.state}</span>
          {partly ? <span className="small muted">{t("left: {{amount}}", { amount: show(line.rest, line.currency) })}</span> : null}
          {line.mark ? <span className="small muted">{MARK[line.mark.category] ?? line.mark.category}</span> : null}
          {line.excluded_reason ? <span className="small muted">{EXCLUDED[line.excluded_reason] ?? line.excluded_reason}</span> : null}
        </span>
      </button>
    </li>
  );
}

function InvoiceRow({ invoice, candidate, index, selected, onToggle, readOnly }: {
  invoice: ReconcileInvoice; candidate?: ReconcileCandidate; index?: number; selected: boolean; onToggle: (id: string) => void; readOnly: boolean;
}) {
  const partly = parseCanonical(invoice.allocated) !== 0n && invoice.state !== "confirmed";
  return (
    <li className={`rc-row${candidate ? " candidate" : ""}${selected ? " is-selected" : ""}`}>
      <input type="checkbox" checked={selected} disabled={readOnly} aria-label={t("Select the invoice {{name}}", { name: invoiceTitle(invoice) })} onChange={() => onToggle(invoice.id)} />
      <button type="button" className="rc-rowbody" disabled={readOnly} onClick={() => onToggle(invoice.id)}>
        <span className="rc-date">{invoice.issue_date ?? "–"}</span>
        <span className="rc-amount">{show(invoice.amount, invoice.currency)}</span>
        <span className="rc-text">
          <span className="rc-main">{index ? <span className="kbd">{index}</span> : null} {invoiceTitle(invoice)}</span>
          <span className="rc-sub">{[invoice.due_date ? t("due {{date}}", { date: invoice.due_date }) : null, invoice.file].filter(Boolean).join(" · ")}</span>
          {candidate ? (
            <span className="rc-sigs">
              {candidate.amount_relation ? <span className={`rc-sig ${candidate.amount_relation === "equal" || candidate.amount_relation === "fx_within" ? "good" : "warn"}`}>{relationText(candidate.amount_relation)}</span> : null}
              {candidate.signals.map((s) => <span key={s} className="rc-sig good">{SIGNAL[s] ?? s}</span>)}
              {candidate.amount_only ? <span className="rc-sig warn">{t("nothing else ties them")}</span> : null}
              {candidate.multiple_candidates ? <span className="rc-sig warn">{t("several candidates")}</span> : null}
              {candidate.source_review_required ? <span className="rc-sig warn">{t("statement balances do not check out")}</span> : null}
              {candidate.fx ? <span className="rc-sig">{t("{{amount}} at the MNB rate of {{day}}", { amount: show(candidate.fx.converted, "HUF"), day: candidate.fx.rate_day })}</span> : null}
            </span>
          ) : null}
        </span>
        <span className="rc-side">
          <span className={`rc-state s-${invoice.state ?? "none"}`}>{INVOICE_STATE[invoice.state ?? ""] ?? invoice.state ?? "–"}</span>
          {partly ? <span className="small muted">{t("left: {{amount}}", { amount: show(invoice.rest, invoice.currency) })}</span> : null}
          {invoice.source !== "approved" ? <span className="small muted">{invoice.source === "no_run" ? t("command line") : t("run not approved")}</span> : null}
        </span>
      </button>
    </li>
  );
}

function LineDetail({ line, invoiceById, readOnly, busy, onRevoke }: {
  line: ReconcileLine; invoiceById: Map<string, ReconcileInvoice>; readOnly: boolean; busy: boolean;
  onRevoke: (kind: "allocation" | "mark" | "decision", ref: string) => void;
}) {
  useLocale();
  const name = (id: string) => { const inv = invoiceById.get(id); return inv ? invoiceTitle(inv) : id.slice(0, 12); };
  return (
    <div className="rc-detail" aria-label={t("The selected line")}>
      <dl>
        <dt>{t("Date")}</dt><dd>{line.booking_date ?? "–"}</dd>
        <dt>{t("Amount")}</dt><dd className="mono">{display(signed(line), line.currency)}{line.state === "partly_allocated" ? ` · ${t("left: {{amount}}", { amount: show(line.rest, line.currency) })}` : ""}</dd>
        <dt>{t("Counterparty")}</dt><dd>{[line.counterparty_name, line.counterparty_account].filter(Boolean).join(" · ") || "–"}</dd>
        {line.memo ? <><dt>{t("Memo")}</dt><dd>{line.memo}</dd></> : null}
        {line.description ? <><dt>{t("Description")}</dt><dd>{line.description}</dd></> : null}
        <dt>{t("Statement")}</dt><dd>{line.file ?? "–"}{line.statement_verified ? "" : ` · ${t("balances do not check out")}`}</dd>
      </dl>
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

/** The amounts of the pairs (one currency) and the reason a rest needs; a converted pair has no amount to set. */
function PairPanel({ plan, busy, onSave, onCancel }: {
  plan: Extract<Plan, { ok: true }>; busy: boolean; onSave: (pairs: PlannedPair[], note?: string) => void; onCancel: () => void;
}) {
  useLocale();
  const [amounts, setAmounts] = useState<string[]>(() => plan.pairs.map((p) => (p.amount !== null ? display(p.amount) : "")));
  const [note, setNote] = useState("");
  const pairs: PlannedPair[] = plan.converted ? plan.pairs : plan.pairs.map((p, i) => ({ ...p, amount: parseInput(amounts[i]) }));
  const live: Plan = plan.converted ? plan : check(pairs);
  const needs = live.ok && live.needsReason;
  const leftLine = plan.converted ? [] : [...new Map(pairs.map((p) => [p.line.id, p.line])).values()].map((l) =>
    rest(l) - sum(pairs.filter((p) => p.line.id === l.id).map((p) => p.amount)));
  const leftInvoice = plan.converted ? [] : [...new Map(pairs.map((p) => [p.invoice.id, p.invoice])).values()].map((i) =>
    rest(i) - sum(pairs.filter((p) => p.invoice.id === i.id).map((p) => p.amount)));
  const cur = plan.pairs[0].line.currency;
  return (
    <form className="rc-panel" aria-label={t("Pairing with amounts")} onSubmit={(e) => {
      e.preventDefault();
      if (live.ok && (!needs || note.trim())) onSave(live.pairs, note.trim() || undefined);
    }}>
      <table>
        <thead><tr><th>{t("Statement line")}</th><th>{t("Invoice")}</th><th className="num">{t("Amount")}</th></tr></thead>
        <tbody>
          {plan.pairs.map((p, i) => (
            <tr key={`${p.line.id}|${p.invoice.id}`}>
              <td>{p.line.booking_date} · {lineTitle(p.line)} · {show(p.line.rest, p.line.currency)}</td>
              <td>{invoiceTitle(p.invoice)} · {show(p.invoice.rest, p.invoice.currency)}</td>
              <td className="num">
                {plan.converted ? t("whole amounts") : (
                  <input type="text" className="amount" inputMode="decimal" value={amounts[i]} aria-label={t("Amount of the pair")}
                    onChange={(e) => setAmounts((a) => a.map((v, j) => (j === i ? e.target.value : v)))} />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!plan.converted && live.ok ? (
        <p className="small">
          {t("Left on the lines: {{lines}} · left on the invoices: {{invoices}}", {
            lines: leftLine.map((v) => display(v, cur)).join(", "), invoices: leftInvoice.map((v) => display(v, cur)).join(", "),
          })}
        </p>
      ) : null}
      {!live.ok ? <p className="small warn-text">{REFUSAL[live.why]}</p> : null}
      {plan.converted && plan.needsReason ? <p className="small warn-text">{t("The converted amount is outside the card band or has no exchange rate: say why the line paid the invoice.")}</p> : null}
      {needs ? (
        <label className="block small">{t("Reason (required when a rest is left, e.g. instalment, bank fee, discount)")}
          <textarea value={note} maxLength={2000} autoFocus onChange={(e) => setNote(e.target.value)} />
        </label>
      ) : null}
      <div className="button-row">
        <button type="submit" className="primary" disabled={busy || !live.ok || (needs && !note.trim())}>{t("Save the pairing")}</button>
        <button type="button" className="quiet" onClick={onCancel}>{t("Cancel")}</button>
      </div>
    </form>
  );
}

function ReasonPanel({ label, action, busy, onSave, onCancel }: {
  label: string; action: string; busy: boolean; onSave: (note: string) => void; onCancel: () => void;
}) {
  useLocale();
  const [note, setNote] = useState("");
  return (
    <form className="rc-panel" onSubmit={(e) => { e.preventDefault(); if (note.trim()) onSave(note.trim()); }}>
      <label className="block small">{label}
        <input type="text" value={note} maxLength={2000} autoFocus onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="button-row">
        <button type="submit" className="primary" disabled={busy || !note.trim()}>{action}</button>
        <button type="button" className="quiet" onClick={onCancel}>{t("Cancel")}</button>
      </div>
    </form>
  );
}

function MarkPanel({ count, categories, busy, onSave, onCancel }: {
  count: number; categories: string[]; busy: boolean; onSave: (category: string, note?: string) => void; onCancel: () => void;
}) {
  useLocale();
  const [category, setCategory] = useState(categories[0] ?? "");
  const [note, setNote] = useState("");
  const needsNote = category === "other";
  return (
    <form className="rc-panel" aria-label={t("Needs no invoice")} onSubmit={(e) => { e.preventDefault(); if (category && (!needsNote || note.trim())) onSave(category, note.trim() || undefined); }}>
      <fieldset className="rc-reasons">
        <legend className="small">{t("Why do the {{n}} selected lines need no invoice?", { n: count })}</legend>
        {categories.map((c) => (
          <label key={c} className="check small"><input type="radio" name="mark" checked={category === c} onChange={() => setCategory(c)} /> {MARK[c] ?? c}</label>
        ))}
      </fieldset>
      <label className="block small">{needsNote ? t("Note (required)") : t("Note (optional)")}
        <input type="text" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="button-row">
        <button type="submit" className="primary" disabled={busy || !category || (needsNote && !note.trim())}>{t("Save for {{n}} lines", { n: count })}</button>
        <button type="button" className="quiet" onClick={onCancel}>{t("Cancel")}</button>
      </div>
    </form>
  );
}

function KeysHelp() {
  useLocale();
  const rows: [string, string][] = [
    ["↑ ↓ / j k", t("Previous or next line")], ["Space", t("Add the line to the selection or take it out")],
    ["1–9", t("Select or unselect a candidate invoice")], ["Enter", t("Pair the selection")], ["x", t("Not this one (with a reason)")],
    ["m", t("Needs no invoice (with a reason)")], ["d", t("Show or hide the documents")], ["Esc", t("Clear the selection or close the panel")],
  ];
  return <dl className="rc-keys rc-panel">{rows.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl>;
}

