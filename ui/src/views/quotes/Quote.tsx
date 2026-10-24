// 191 (plan F-quote-package B3; DECISIONS 191): the quote package. The owner asked that the quote can be chosen as a
// kind of work, as the reconciliation or the data extraction can. It starts from a quote request already processed: an
// email (its own text and its attachments, put together field by field) or a document read as one, in any package.
// Its stages: the request with its gaps, the quote (its lines proposed from the price list, then composed by a person
// beside the request, 192: QuoteEditor.tsx), and its approval as a version of the package's own.
import { useEffect, useState } from "react";
import {
  api, ApiError, type QuoteBlockerCode, type QuoteMatchAnswer, type QuoteProposal, type QuoteRequest,
  type QuoteRequestCandidate, type QuoteRequestPart, type QuoteView, type WorkpackageView,
} from "../../api";
import { BlockerList } from "../../components/BlockerList";
import { Picker } from "../../components/Picker";
import { t, useLocale } from "../../i18n";
import { numText, usdBudget, when } from "../../labels";
import { go, type Stage } from "../../route";
import { QuoteApprovalStage, QuoteCompose } from "./QuoteEditor";
import { quoteFieldLabel as fieldLabel } from "./quoteStatus";

export const QUOTE_BLOCKER: Record<QuoteBlockerCode, string> = {
  "quote:request_missing": "The request can no longer be read: it was removed from its package, or it is no longer read as a quote request",
  "quote:no_customer": "The request names no customer: neither the email's text nor an attachment has one",
  "quote:no_items": "The request names no item: neither the email's text nor an attachment has one",
  "quote:no_price_list": "There is no active price list: upload one in Settings › Price lists and make it active",
};

const partKind = (p: QuoteRequestPart) =>
  ({ email_text: t("the email's text"), attachment: t("attachment"), document: t("document") })[p.kind] ?? p.kind;

export function QuoteStages({ view, stage, onChanged }: { view: WorkpackageView; stage: Stage; onChanged: () => void }) {
  useLocale();
  const q = view.quote;
  if (!q) return <p className="muted">{t("Loading…")}</p>;
  const wpId = view.workpackage.id;
  if (stage === "process") return <RequestPanel view={q} />;
  if (stage === "review") {
    // 192: once the quote has a draft (or a version), it is composed beside the request
    return q.draft.draft || q.draft.approval.active ? <QuoteCompose wpId={wpId} view={q} onChanged={onChanged} />
      : <ProposalPanel wpId={wpId} view={q} onChanged={onChanged} />;
  }
  return <QuoteApprovalStage wpId={wpId} view={q} archived={view.workpackage.status === "archived"} onChanged={onChanged} />;
}

// 191 B4c: a proposed line's mark (DESIGN.md §4): sure green, to check a person's turn (orange), not listed off (amber)
const MARK: Record<string, { cls: string; label: string }> = {
  sure: { cls: "s-done", label: "sure" }, check: { cls: "s-review", label: "to check" },
  not_listed: { cls: "s-warn", label: "not in the price list" },
};
const STATE: Record<QuoteProposal["state"], { cls: string; label: string }> = {
  queued: { cls: "s-queued", label: "queued" }, running: { cls: "s-running", label: "being made" },
  done: { cls: "s-done", label: "made" }, failed: { cls: "s-failed", label: "failed" },
};
const capOf = (usd: Record<string, string>) => Object.values(usd).reduce((s, v) => s + (Number(v) || 0), 0);

/** The proposal: each requested item with the price list item proposed for it, asked by a person and made by the
 *  worker; while it is queued or being made the page asks again every two seconds. */
export function ProposalPanel({ wpId, view, onChanged, askStep }: {
  wpId: string; view: QuoteView; onChanged: () => void;
  /** 231 (A6): on a case's page, asking starts the case's step, which asks for the proposal */
  askStep?: () => Promise<unknown>;
}) {
  useLocale();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const p = view.proposal;
  const active = p?.state === "queued" || p?.state === "running";
  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(onChanged, 2000);
    return () => window.clearInterval(timer);
  }, [active, onChanged]);
  const cap = capOf(view.proposal_cap.usd);
  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const ask = () => run(askStep ?? (() => api.requestQuoteProposal(wpId)));
  // 192: the quote's draft from the finished proposal, or from the requested items alone
  const start = (source: "proposal" | "request") => run(() => api.startQuoteDraft(wpId, { source, expected_state: view.draft.state }));
  const usable = p?.state === "done" && !p.stale;
  return (
    <section className="card wide rc-stack quote-proposal" aria-label={t("Proposal from the price list")}>
      <div className="card-head">
        <h3>{t("Proposal from the price list")}</h3>
        <span className="button-row">
          {/* the view's one solid action: asking while there is no usable proposal, then composing the quote from it */}
          <button type="button" className={!p || p.state === "failed" || p.stale ? "primary" : "secondary"}
            disabled={busy || active || view.blockers.length > 0}
            title={cap > 0 ? t("Asks the AI about {{n}} item(s) and can spend up to {{usd}}", { n: view.proposal_cap.items, usd: usdBudget(cap) }) : undefined}
            onClick={() => void ask()}>
            {p ? t("Ask for a new proposal") : t("Ask for the proposal")}
            {cap > 0 ? <span className="spend" aria-hidden="true">≤ {usdBudget(cap)}</span> : null}
          </button>
          {usable ? (
            <button type="button" className="primary" disabled={busy || view.blockers.length > 0} onClick={() => void start("proposal")}>
              {t("Compose the quote from the proposal")}
            </button>
          ) : null}
        </span>
      </div>
      {view.blockers.length ? <Gaps view={view} /> : null}
      {p ? (
        <p className="small">
          <span className={`status ${STATE[p.state].cls}`}>{t(STATE[p.state].label)}</span>{" "}
          <span className="muted tnum">
            {[p.engine === "gpt" ? t("GPT only") : "JEV", t("price list version {{n}}", { n: p.version }),
              when(p.finished_at ?? p.requested_at)].join(" · ")}
          </span>
          {p.stale ? <>{" "}<span className="status s-warn">{t("the request or the price list changed since")}</span></> : null}
          {p.error ? <span className="error-text"> {p.error}</span> : null}
        </p>
      ) : (
        <p className="small muted">{t("The system proposes a price list item for each requested item; code prices the lines. You review and change every line before the quote is approved.")}</p>
      )}
      {p && p.lines.length ? <ProposalLines lines={p.lines} /> : null}
      {!usable && !view.blockers.length ? (
        <p className="small muted">
          {t("You can also compose the quote without a proposal: each requested item becomes a line whose item you choose.")}{" "}
          <button type="button" className="quiet small-btn" disabled={busy} onClick={() => void start("request")}>{t("Start without a proposal")}</button>
        </p>
      ) : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </section>
  );
}

function ProposalLines({ lines }: { lines: QuoteProposal["lines"] }) {
  useLocale();
  return (
    <table className="table compact quote-proposal-lines" aria-label={t("Proposed lines")}>
      <thead>
        <tr>
          <th>{t("Requested item")}</th><th className="num">{t("Quantity")}</th><th>{t("Proposed price list item")}</th>
          <th>{t("Mark")}</th><th>{t("Other candidates")}</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((line) => (
          <tr key={line.row}>
            <td>{line.description ?? "—"}</td>
            <td className="num tnum">{line.quantity === null || line.quantity === undefined ? "—" : `${numText(line.quantity, 4)} ${line.unit ?? ""}`.trim()}</td>
            <td>
              {line.answer.sku ? (
                <span className="quote-item"><code className="mono">{line.answer.sku}</code>{line.answer.name ? <span>{line.answer.name}</span> : null}</span>
              ) : <span className="muted">—</span>}
            </td>
            <td><MarkCell answer={line.answer} /></td>
            <td className="muted small">{(line.answer.candidates ?? []).filter((c) => c !== line.answer.sku).join(", ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MarkCell({ answer }: { answer: QuoteMatchAnswer }) {
  useLocale();
  if (answer.error || !answer.mark) return <span className="status s-failed" title={answer.error ?? undefined}>{t("failed")}</span>;
  const m = MARK[answer.mark];
  return (
    <span className={`status ${m.cls}`} title={answer.method === "code" ? t("the item code is written in the request") : undefined}>
      {t(m.label)}{answer.method === "code" ? ` · ${t("by its code")}` : ""}
    </span>
  );
}

function Gaps({ view }: { view: QuoteView }) {
  useLocale();
  return (
    <BlockerList parts label={t("Gaps")}
      items={view.blockers.map((b) => ({ key: b.code, content: <span>{t(QUOTE_BLOCKER[b.code] ?? b.message)}</span> }))} />
  );
}

/** A header field's value as text; a missing one is a dash. */
const valueText = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));

export function RequestPanel({ view }: { view: QuoteView }) {
  useLocale();
  const r = view.request;
  return (
    <div className="stage-stack">
      <section className="card wide rc-stack quote-request" aria-label={t("The request")}>
        <div className="card-head">
          <h3>{r ? r.title || t("(no subject)") : t("The request")}</h3>
          {view.source ? (
            <a href={`#/workpackages/${encodeURIComponent(view.source.workpackage_id)}`}>
              {t("in {{name}}", { name: view.source.workpackage_name ?? view.source.workpackage_id })}
            </a>
          ) : null}
        </div>
        {r ? (
          <p className="small muted">
            {[r.kind === "email" ? t("email") : t("document"), r.sender, r.received_at ? when(r.received_at) : null].filter(Boolean).join(" · ")}
          </p>
        ) : null}
        {view.blockers.length ? <Gaps view={view} /> : <p className="small ok">{t("The request has what a quote needs.")}</p>}
        {r ? <RequestData request={r} /> : null}
      </section>
      <PriceLists view={view} />
    </div>
  );
}

/** The request's fields with the part each came from, its items and its parts (192: under its email too, `compact`:
 *  a part named by its kind, an attachment by its file, as the email's page shows the rest beside it). */
export function RequestData({ request: r, compact = false }: { request: QuoteRequest; compact?: boolean }) {
  useLocale();
  const from = (n: number | undefined | null) => {
    if (n === undefined || n === null) return "";
    const p = r.parts[n];
    if (compact) return p.kind === "email_text" ? partKind(p) : p.name || partKind(p);
    return `${partKind(p)}: ${p.name}`;
  };
  return (
    <>
      <table className="table compact quote-fields" aria-label={t("The request's data")}>
        <thead><tr><th>{t("Field")}</th><th>{t("Value")}</th><th>{t("Read from")}</th></tr></thead>
        <tbody>
          {Object.keys(r.fields).map((f) => (
            <tr key={f}>
              <td>{fieldLabel(f)}</td>
              <td className={r.fields[f] ? "" : "muted"}>{valueText(r.fields[f])}</td>
              <td className="muted small">{from(r.sources[f])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="template-output-head">
        <h3>{fieldLabel("requested_items")}</h3>
        <span className="muted small">{r.items_from === null ? t("none") : t("read from {{part}}", { part: from(r.items_from) })}</span>
      </div>
      {r.items.length ? (
        <table className="table compact quote-items" aria-label={fieldLabel("requested_items")}>
          <thead><tr><th>{t("Description")}</th><th className="num">{t("Quantity")}</th><th>{t("Unit")}</th></tr></thead>
          <tbody>
            {r.items.map((i, n) => (
              <tr key={n}>
                <td>{valueText(i.description)}</td>
                <td className="num tnum">{i.quantity === null || i.quantity === undefined ? "—" : numText(i.quantity, 4)}</td>
                <td>{valueText(i.unit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <p className="small muted">
        {t("Parts:")} {r.parts.map((p) => `${partKind(p)} (${p.name || "—"})`).join(" · ") || t("none")}
      </p>
    </>
  );
}

function PriceLists({ view }: { view: QuoteView }) {
  useLocale();
  return (
    <section className="card wide rc-stack" aria-label={t("Price list")}>
      <h3>{t("Price list")}</h3>
      {view.price_lists.length ? (
        <ul className="plain small">
          {view.price_lists.map((p) => (
            <li key={p.price_list}>
              <strong>{p.name}</strong>{" "}
              <span className="muted tnum">{t("version {{n}} · {{items}} items · {{currency}}", { n: p.version, items: p.items, currency: p.currency })}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="small">{t("No active price list.")} <a href="#/settings/prices">{t("Settings › Price lists")}</a></p>
      )}
    </section>
  );
}

/** A request in the picker: its title, then its customer, its package and its day. */
function optionOf(c: QuoteRequestCandidate) {
  return {
    value: `${c.workpackage_id}|${c.item_id}`, label: c.title || t("(no subject)"),
    detail: [c.customer_name, c.workpackage_name, c.received_at?.slice(0, 10)].filter(Boolean).join(" · "),
  };
}

export function QuoteCreate(_props: { onDone: (wpId: string) => void }) {
  useLocale();
  const [q, setQ] = useState("");
  const [found, setFound] = useState<QuoteRequestCandidate[] | null>(null);
  const [chosen, setChosen] = useState<QuoteRequestCandidate | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {  // the service searches; a short pause between keys keeps it from asking at every key
    let live = true;
    const timer = window.setTimeout(() => {
      api.quoteRequests(q.trim() || undefined)
        .then((r) => { if (live) setFound(r.requests); })
        .catch((e) => { if (live) setError(e instanceof ApiError ? e.message : String(e)); });
    }, q ? 250 : 0);
    return () => { live = false; window.clearTimeout(timer); };
  }, [q]);

  const fallback = chosen ? t("Quote: {{name}}", { name: chosen.customer_name || chosen.title }).slice(0, 200) : "";
  async function submit() {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      // 231 (A6c): a case of the IT quote's process pack, opened on its own page
      const made = await api.startCase({ pack: "it_quote", name: name.trim() || fallback,
        record: { workpackage_id: chosen.workpackage_id, item_id: chosen.item_id } });
      go({ view: "cases", caseId: made.case_id });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const options = (found ?? []).map(optionOf);
  return (
    <form className="create rc-stack" aria-label={t("New quote")} onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <p className="muted small">{t("A quote starts from a quote request already processed: an email with its attachments, or a document read as one. The quote package reads it as it stands in its package and puts its parts together; it processes no file itself.")}</p>
      <Picker label={t("Quote request")} value={chosen ? `${chosen.workpackage_id}|${chosen.item_id}` : null} options={options}
        loading={found === null} onSearch={setQ} placeholder={t("Choose a request…")}
        selectedLabel={chosen ? optionOf(chosen).label : undefined}
        emptyText={q ? t("No request matches.") : t("No quote request yet: an email or a document read as one in a processed package.")}
        onChange={(v) => setChosen((found ?? []).find((c) => `${c.workpackage_id}|${c.item_id}` === v) ?? null)} />
      {chosen ? (
        <div className="small quote-chosen">
          <p>
            {[chosen.customer_name ? t("customer: {{name}}", { name: chosen.customer_name }) : t("no customer named"),
              t("{{n}} requested item(s)", { n: chosen.items })].join(" · ")}
            {" · "}<a href={`#/workpackages/${encodeURIComponent(chosen.workpackage_id)}`}>{chosen.workpackage_name}</a>
          </p>
          {chosen.quotes.length ? (
            <p className="warn-text">
              {t("Quotes already made from it:")}{" "}
              {chosen.quotes.map((x, i) => (
                <span key={x.id}>{i ? ", " : ""}<a href={`#/workpackages/${encodeURIComponent(x.id)}`}>{x.name}</a></span>
              ))}
            </p>
          ) : null}
        </div>
      ) : null}
      <label className="block">{t("Name")} <span className="muted">{t("(optional)")}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} placeholder={fallback} />
      </label>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      <div className="button-row">
        <button type="submit" className="primary" disabled={busy || !chosen}>{busy ? t("Creating…") : t("Create")}</button>
      </div>
    </form>
  );
}
