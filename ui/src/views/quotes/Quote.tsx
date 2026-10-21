// 191 (plan F-quote-package B3; DECISIONS 191): the quote package. The owner asked that the quote can be chosen as a
// kind of work, as the reconciliation or the data extraction can. It starts from a quote request already processed: an
// email (its own text and its attachments, put together field by field) or a document read as one, in any package.
// Its stages: the request with its gaps, the quote (its lines proposed from the price list and changed by a person come
// with the next steps of the plan), and its approval.
import { useEffect, useState } from "react";
import {
  api, ApiError, type QuoteBlockerCode, type QuoteRequest, type QuoteRequestCandidate, type QuoteRequestPart,
  type QuoteView, type WorkpackageView,
} from "../../api";
import { Picker } from "../../components/Picker";
import { t, useLocale } from "../../i18n";
import { fieldLabel, numText, when } from "../../labels";
import type { Stage } from "../../route";

export const QUOTE_BLOCKER: Record<QuoteBlockerCode, string> = {
  "quote:request_missing": "The request can no longer be read: it was removed from its package, or it is no longer read as a quote request",
  "quote:no_customer": "The request names no customer: neither the email's text nor an attachment has one",
  "quote:no_items": "The request names no item: neither the email's text nor an attachment has one",
  "quote:no_price_list": "There is no active price list: upload one in Settings › Price lists and make it active",
};

const partKind = (p: QuoteRequestPart) =>
  ({ email_text: t("the email's text"), attachment: t("attachment"), document: t("document") })[p.kind] ?? p.kind;

/** The stages' status lines and the package's summary (`ui/src/logic/registry.tsx`). */
export function quoteStatus(view: WorkpackageView): Record<Stage, string> | null {
  const q = view.quote;
  if (!q) return null;
  return {
    process: q.request ? t("{{n}} part(s), {{m}} requested item(s)", { n: q.request.parts.length, m: q.request.items.length })
      : t("the request cannot be read"),
    review: q.blockers.length ? t("{{n}} gap(s) to clear first", { n: q.blockers.length }) : t("ready to compose"),
    result: t("not approved yet"),
  };
}

export function quoteSummary(view: WorkpackageView): string | null {
  const r = view.quote?.request;
  if (!r) return view.quote ? t("Quote from a request that can no longer be read") : null;
  const customer = r.fields.customer_name ? String(r.fields.customer_name) : null;
  return customer ? t("Quote for {{customer}}: {{title}}", { customer, title: r.title }) : t("Quote: {{title}}", { title: r.title });
}

export function QuoteStages({ view, stage }: { view: WorkpackageView; stage: Stage; onChanged: () => void }) {
  useLocale();
  const q = view.quote;
  if (!q) return <p className="muted">{t("Loading…")}</p>;
  if (stage === "process") return <RequestPanel view={q} />;
  return (
    <section className="card wide rc-stack" aria-label={stage === "review" ? t("The quote") : t("Approval")}>
      <h3>{stage === "review" ? t("The quote") : t("Approval")}</h3>
      {q.blockers.length ? <Gaps view={q} /> : null}
      <p className="muted">{t("Composing and approving the quote come with the next step of the development; until then the request is checked on the Request stage.")}</p>
    </section>
  );
}

function Gaps({ view }: { view: QuoteView }) {
  useLocale();
  return (
    <ul className="plain template-issues" aria-label={t("Gaps")}>
      {view.blockers.map((b) => <li key={b.code} className="blocker"><span>{t(QUOTE_BLOCKER[b.code] ?? b.message)}</span></li>)}
    </ul>
  );
}

/** A header field's value as text; a missing one is a dash. */
const valueText = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));

function RequestPanel({ view }: { view: QuoteView }) {
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

function RequestData({ request: r }: { request: QuoteRequest }) {
  useLocale();
  const from = (n: number | undefined | null) => (n === undefined || n === null ? "" : `${partKind(r.parts[n])}: ${r.parts[n].name}`);
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

export function QuoteCreate({ onDone }: { onDone: (wpId: string) => void }) {
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
      const made = await api.createQuotePackage({ name: name.trim() || fallback, source: chosen.workpackage_id, item_id: chosen.item_id });
      onDone(made.workpackage_id);
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
