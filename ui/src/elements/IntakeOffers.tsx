// 231 (plan stage C, C1a; DECISIONS 231): what an email may start, on its own page: every process whose intake takes
// emails and whose record step finds its record in this one (`jav/app/intake.py`), with the record put together, what
// it lacks as a whole, the cases already started from it, and its start. The page names no process: the offers are
// the process packs'. Until C1a the quote's own card under its email (192 B6a).
import { useState } from "react";
import { api, ApiError, type IntakeOffer } from "../api";
import { Icon } from "../components/Icon";
import { t, useLocale } from "../i18n";
import { go } from "../route";
import { RecordData } from "./RecordData";

export function IntakeOffers({ offers }: { offers: IntakeOffer[] }) {
  if (!offers.length) return null;
  // 263 (F1): one solid button per view - the first offer no case was started from yet
  const lead = offers.find((o) => !o.cases.length)?.pack;
  return <>{offers.map((o) => <Offer key={o.pack} offer={o} lead={o.pack === lead} />)}</>;
}

function Offer({ offer: o, lead }: { offer: IntakeOffer; lead: boolean }) {
  useLocale();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const title = t(o.title);
  async function start() {
    setBusy(true);
    setError(null);
    try {
      const name = `${title}: ${o.label || o.preview?.title || t("(no subject)")}`.slice(0, 200);
      const made = await api.startCase({ pack: o.pack, name, record: o.record });
      go({ view: "cases", caseId: made.case_id });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  }
  return (
    <section className="quote-on-email pad-s" aria-label={title}>
      <div className="quote-on-email-head">
        <h3>{title}</h3>
        {/* the email's next step: the view's one solid action until a case is started from it */}
        <button type="button" className={lead ? "primary small-btn" : "secondary small-btn"} disabled={busy}
          onClick={() => void start()}>
          <Icon name="plus" />{o.cases.length ? t("Start another case from this email") : t("Start a case from this email")}
        </button>
      </div>
      {o.gaps.length ? (
        <ul className="plain">
          {o.gaps.map((g) => <li key={g.code} className="small"><span className="status long s-review">{t(g.message)}</span></li>)}
        </ul>
      ) : <p className="small ok">{t("The record has what a case needs.")}</p>}
      {o.cases.length ? (
        <p className="small">
          {t("Cases already started from it:")}{" "}
          {o.cases.map((x, i) => (
            <span key={x.id}>{i ? ", " : ""}<a href={`#/cases/${encodeURIComponent(x.id)}`}>{x.name}</a></span>
          ))}
        </p>
      ) : null}
      {o.preview ? <RecordData record={o.preview} listField={o.list_field ?? "items"} docType={o.record_type} compact /> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </section>
  );
}
