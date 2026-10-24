// 192 (plan F-quote-package B6a; DECISIONS 191, 192): the quote request under its email in a mailbox package. The
// request is put together from the email's text and its attachments; each value says which part it came from, so a
// part that lacks something (the text names no item, the list names no customer) is a note, not a to-do (the owner's
// choice). What the whole request lacks is said, the quotes already made from it are linked, and a quote starts here.
// The email's page shows it through the item part registry (`ui/src/logic/registry.tsx` `ITEM_PARTS`).
import { useState } from "react";
import { api, ApiError, type QuoteEmailPart } from "../../api";
import { Icon } from "../../components/Icon";
import { t, useLocale } from "../../i18n";
import { go } from "../../route";
import { QUOTE_BLOCKER, RequestData } from "./Quote";

export function QuoteOnEmail({ part }: { part: QuoteEmailPart }) {
  useLocale();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const r = part.request;
  const customer = r.fields.customer_name ? String(r.fields.customer_name) : null;
  async function start() {
    setBusy(true);
    setError(null);
    try {
      const name = t("Quote: {{name}}", { name: customer || r.title || t("(no subject)") }).slice(0, 200);
      // 231 (A6): a case of the IT quote's process pack, started from the email's record
      const made = await api.startCase({ pack: "it_quote", name, record: { workpackage_id: part.source.workpackage_id, item_id: part.source.item_id } });
      go({ view: "cases", caseId: made.case_id });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  }
  return (
    <section className="quote-on-email pad-s" aria-label={t("Quote request")}>
      <div className="quote-on-email-head">
        <h3>{t("Quote request")}</h3>
        {/* the email's next step: the view's one solid action until a quote is made from it */}
        <button type="button" className={part.quotes.length ? "secondary small-btn" : "primary small-btn"} disabled={busy}
          onClick={() => void start()}>
          <Icon name="plus" />{part.quotes.length ? t("Start another quote from this email") : t("Start a quote from this email")}
        </button>
      </div>
      {part.gaps.length ? (
        <ul className="plain">
          {part.gaps.map((g) => <li key={g.code} className="small"><span className="status long s-review">{t(QUOTE_BLOCKER[g.code] ?? g.message)}</span></li>)}
        </ul>
      ) : <p className="small ok">{t("The request has what a quote needs.")}</p>}
      {part.quotes.length ? (
        <p className="small">
          {t("Quotes already made from it:")}{" "}
          {part.quotes.map((x, i) => (
            <span key={x.id}>{i ? ", " : ""}<a href={x.case ? `#/cases/${encodeURIComponent(x.id)}` : `#/workpackages/${encodeURIComponent(x.id)}/review`}>{x.name}</a></span>
          ))}
        </p>
      ) : null}
      <RequestData request={r} compact />
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </section>
  );
}
