// 196 (plan F-Word-output W3, DECISIONS 196): the reply letter to the quote request, beside the approved quote. The
// owner asked for a draft only: the system never sends it and never touches the mailbox. The paragraph after the
// greeting is the frame's own until a person asks GPT for one fitted to the request (the button shows its cost cap);
// the code refuses a paragraph with a number, a link or an address, and the frame's own stays. The person reads and
// changes the whole body and accepts it; only then does the letter download as a file Outlook opens as an unsent
// message, the version's Word quote attached. While GPT's paragraph is queued or being written the page asks again
// every two seconds.
import { useEffect, useState } from "react";
import { api, ApiError, type QuoteLetterView } from "../../api";
import { Icon } from "../../components/Icon";
import { errorText, useAction } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { usdBudget, when } from "../../labels";

const STATE: Record<NonNullable<QuoteLetterView["state"]>, { cls: string; label: string }> = {
  queued: { cls: "s-queued", label: "queued" }, running: { cls: "s-running", label: "being written" },
  done: { cls: "s-done", label: "written" }, failed: { cls: "s-failed", label: "failed" },
};
const PROBLEM: Record<string, string> = {
  number: "it holds a number", link: "it holds a web address", email: "it holds an email address",
  marker: "it holds a marker", empty: "it is empty", too_long: "it is too long",
};

export function QuoteLetterCard({ wpId, letter, archived, onChanged }: {
  wpId: string; letter: QuoteLetterView; archived: boolean; onChanged: () => void;
}) {
  useLocale();
  const { busy, error, notice, run } = useAction();
  const [body, setBody] = useState(letter.body ?? "");
  const [edited, setEdited] = useState(false);
  // the body follows the service while the person has not typed (a written paragraph, an acceptance elsewhere)
  useEffect(() => { if (!edited) setBody(letter.body ?? ""); }, [letter.body, edited]);
  const active = letter.state === "queued" || letter.state === "running";
  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(onChanged, 2000);
    return () => window.clearInterval(timer);
  }, [active, onChanged]);
  if (letter.version === null) return null;
  const cap = Object.values(letter.cap).reduce((s, v) => s + (Number(v) || 0), 0);
  const unused = letter.state === "done" && letter.problems.length > 0;
  const accepted = letter.accepted;
  const changed = !accepted || body.trim() !== accepted.body.trim();

  const ask = () => run(() => api.requestQuoteLetterParagraph(wpId), { then: () => { setEdited(false); onChanged(); } });
  const accept = () => run(() => api.acceptQuoteLetter(wpId, body, letter.decision_state), {
    then: () => { setEdited(false); onChanged(); },
    done: t("The letter has been accepted; download it and send it from Outlook."),
    failed: (e) => {
      if (!(e instanceof ApiError && e.status === 409)) return errorText(e);
      setEdited(false);
      onChanged();
      return t("The letter changed since it was shown; it has been reloaded. Check it and accept it again.");
    },
  });

  return (
    <section className="card wide rc-stack quote-letter" aria-label={t("The reply letter")}>
      <div className="card-head">
        <h2>{t("The reply letter (draft)")}</h2>
        <span className="button-row">
          <button type="button" className="secondary" disabled={busy || active || archived}
            title={cap > 0 ? t("GPT writes the paragraph after the greeting, without numbers, and can spend up to {{usd}}", { usd: usdBudget(cap) }) : undefined}
            onClick={() => void ask()}>
            {letter.state ? t("Ask GPT again for the paragraph") : t("Ask GPT for the paragraph")}
            {cap > 0 ? <span className="spend" aria-hidden="true">≤ {usdBudget(cap)}</span> : null}
          </button>
        </span>
      </div>
      <p className="muted small">{t("The system never sends the letter. Accept it, download it and send it from Outlook: it opens there as a new message, with the quote's Word document attached.")}</p>
      <dl className="quote-facts quote-facts-wide">
        <div><dt>{t("To")}</dt><dd className={letter.to ? "" : "muted"}>{letter.to ?? t("no address: add it in Outlook")}</dd></div>
        <div><dt>{t("Subject")}</dt><dd>{letter.subject}</dd></div>
        <div><dt>{t("Answers with")}</dt><dd className="tnum">{t("version {{n}}", { n: letter.version })}</dd></div>
      </dl>
      {letter.state ? (
        <p className="small">
          <span className={`status ${unused ? "s-warn" : STATE[letter.state].cls}`}>
            {unused ? t("GPT's paragraph is not used: {{why}}", { why: letter.problems.map((p) => t(PROBLEM[p] ?? p)).join(", ") })
              : t(STATE[letter.state].label)}
          </span>{" "}
          {letter.state === "failed" && letter.error ? <span className="muted small">{letter.error}</span> : null}
          {unused ? <span className="muted small">{t("The frame's own paragraph stays in the letter.")}</span> : null}
        </p>
      ) : (
        <p className="small muted">{t("The paragraph after the greeting is the frame's own; GPT can write one fitted to the request, never a number.")}</p>
      )}
      <label className="block">{t("The letter's text")}
        <textarea className="quote-letter-body" rows={12} value={body} disabled={archived} maxLength={20000}
          onChange={(e) => { setBody(e.target.value); setEdited(true); }} />
      </label>
      <div className="button-row">
        <button type="button" className="primary" disabled={busy || archived || !body.trim() || !changed} onClick={() => void accept()}>
          {t("Accept the letter")}
        </button>
        {accepted ? (
          <a className="secondary dl-btn small-btn" href={api.quoteLetterEmlUrl(wpId, letter.version)} download>
            <Icon name="download" />{t("Download the letter (Outlook)")}</a>
        ) : null}
        {accepted ? (
          <span className="muted small">
            {changed ? t("Changed since it was accepted: accept it again to download this text.")
              : t("Accepted by {{who}}, {{when}}.", { who: accepted.by, when: when(accepted.at) })}
          </span>
        ) : null}
      </div>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {notice ? <p role="status" className="small ok">{notice}</p> : null}
    </section>
  );
}
