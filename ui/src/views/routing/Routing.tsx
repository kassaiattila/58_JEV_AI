// 181 (plan 170 L5; DECISIONS 181): the email routing package. For every document that arrived by email it proposes
// the package it belongs to (the open package whose party, period and role fit it, or a new one); a person accepts the
// proposals one by one or every clear one at once, rejects them or chooses another package. An attachment the routing
// cannot place by itself shows why (an amber mark); a document of another kind is only listed. Its stages: the email
// packages it routes, the routing itself, and what went where.
import { useState } from "react";
import { api, type WorkpackageView } from "../../api";
import { useAction, useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { go } from "../../route";

// 231 (C1c): the routing's stages moved to the file routing's screen element
export { BLOCKER, RoutingStages } from "../../elements/FilePlacement";

export function RoutingCreate({ onDone }: { onDone: (wpId: string) => void }) {
  useLocale();
  const list = useLoad("workpackages-brief", api.workpackagesBrief);
  const [chosen, setChosen] = useState<string[]>([]);
  const [name, setName] = useState("");
  const { busy, error, run } = useAction();
  const mailboxes = (list.data?.workpackages ?? []).filter((w) => w.source_kind === "mailbox");
  const submit = () => run(() => {
    const names = mailboxes.filter((w) => chosen.includes(w.id)).map((w) => w.name);
    return api.createRoutingPackage({ name: name.trim() || t("Routing: {{names}}", { names: names.join(", ") }).slice(0, 200), sources: chosen });
  }, { then: (view) => onDone(view.workpackage.id) });
  return (
    <form className="create rc-stack" aria-label={t("New email routing package")} onSubmit={(e) => { e.preventDefault(); if (chosen.length) void submit(); }}>
      <p className="muted small">{t("The routing proposes, for every invoice, outgoing invoice and bank statement that arrived by email, the package of its party, period and role. It processes no file and calls no AI service.")}</p>
      {list.error ? <p className="notice error" role="alert">{list.error.message}</p> : null}
      <fieldset className="wizard-choices">
        <legend>{t("Email packages")}</legend>
        {mailboxes.length ? mailboxes.map((w) => (
          <label key={w.id} className="check">
            <input type="checkbox" checked={chosen.includes(w.id)}
              onChange={(e) => setChosen((prev) => (e.target.checked ? [...prev, w.id] : prev.filter((x) => x !== w.id)))} /> {w.name}
          </label>
        )) : <p className="muted small">{list.data ? t("No email package yet: download a mailbox first.") : t("Loading…")}</p>}
      </fieldset>
      <label className="block">{t("Name")} <span className="muted">{t("(optional)")}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
      </label>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      <div className="button-row">
        <button type="submit" className="primary" disabled={busy || !chosen.length}>{busy ? t("Creating…") : t("Create")}</button>
      </div>
    </form>
  );
}

/** 181 (DECISIONS 170 K3): an email package's offer to route its attachments: a person starts the routing package with
 *  one click; the routing packages already made for it are linked. */
export function RoutingOffer({ view }: { view: WorkpackageView }) {
  useLocale();
  const { busy, error, run } = useAction();
  const offer = view.routing_offer;
  if (!offer) return null;
  const start = () => run(() => api.createRoutingPackage({ name: t("Routing: {{names}}", { names: view.workpackage.name }).slice(0, 200), sources: [view.workpackage.id] }),
    { then: (made) => go({ view: "workpackages", wpId: made.workpackage.id, stage: "review" }) });
  return (
    <section className="card rc-stack" aria-label={t("Email routing")}>
      <div className="button-row">
        <p className="small grow">{t("{{n}} document(s) of this package came as an email's attachment. The routing proposes the package each invoice, outgoing invoice and bank statement belongs to.", { n: offer.attachments })}</p>
        <button type="button" className="secondary" disabled={busy} onClick={() => void start()}>{t("Route the attachments")}</button>
      </div>
      {offer.routings.length ? (
        <p className="small">{t("Routed by:")} {offer.routings.map((r, i) => (
          <span key={r.id}>{i ? ", " : ""}<a href={`#/workpackages/${encodeURIComponent(r.id)}`}>{r.name}</a></span>
        ))}</p>
      ) : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </section>
  );
}
