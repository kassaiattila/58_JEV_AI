// 181 (plan 170 L5; DECISIONS 181): the email routing package. For every document that arrived by email it proposes
// the package it belongs to (the open package whose party, period and role fit it, or a new one); a person accepts the
// proposals one by one or every clear one at once, rejects them or chooses another package. An attachment the routing
// cannot place by itself shows why (an amber mark); a document of another kind is only listed. Its stages: the email
// packages it routes, the routing itself, and what went where.
import { useMemo, useState } from "react";
import { api, ApiError, type RoutingBlocker, type RoutingItem, type RoutingView, type WorkpackageView } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { go, type Stage } from "../../route";

export const BLOCKER: Record<RoutingBlocker, string> = {
  no_result: "Not processed yet: its email package's run has not read it",
  unknown_party: "No own party: neither its buyer nor its supplier is an own party's",
  unclear_direction: "Unclear whether it is incoming or outgoing",
  internal: "An invoice between two own parties: choose its package",
  not_own: "Neither side is an own party",
  no_day: "No date to place it in a period",
  suspicious: "It came with a suspicious email",
  sent_incoming: "An incoming invoice in a sent email",
};

function emailText(item: RoutingItem): string {
  const e = item.email;
  if (!e) return "";
  const parts = [e.folder === "sent" ? t("sent") : null, e.received_at?.slice(0, 10) ?? null, e.sender, e.subject].filter(Boolean);
  return parts.join(" · ");
}

function placementText(item: RoutingItem): string {
  const p = item.placement;
  return [p.role_title ? t(p.role_title) : null, p.party, p.day].filter(Boolean).join(" · ");
}

/** The stages' status line and the package's summary (`ui/src/logic/registry.tsx`). */
export function routingStatus(view: WorkpackageView): Record<Stage, string> | null {
  const r = view.routing;
  if (!r) return null;
  return {
    process: t("{{n}} email package(s), {{m}} attachment(s)", { n: r.sources.length, m: r.counts.attachments }),
    review: r.counts.routable - r.counts.decided ? t("{{n}} to decide", { n: r.counts.routable - r.counts.decided }) : t("every document decided"),
    result: t("{{n}} routed", { n: r.counts.accepted }),
  };
}

export function routingSummary(view: WorkpackageView): string | null {
  const r = view.routing;
  return r ? t("Routing of {{n}} email package(s): {{m}} document(s) to route", { n: r.sources.length, m: r.counts.routable }) : null;
}

export function RoutingStages({ view, stage, onChanged }: { view: WorkpackageView; stage: Stage; onChanged: () => void }) {
  useLocale();
  const r = view.routing;
  if (!r) return <p className="muted">{t("Loading…")}</p>;
  if (stage === "process") return <Sources view={r} />;
  if (stage === "review") return <Decide wpId={view.workpackage.id} view={r} onChanged={onChanged} />;
  return <Routed view={r} />;
}

function Sources({ view }: { view: RoutingView }) {
  return (
    <section className="card wide rc-stack" aria-label={t("Email packages")}>
      <h3>{t("Email packages")}</h3>
      <p className="small muted">{t("The PDF attachments of these packages are routed: each is read in its email package, then proposed for the package of its party, period and role.")}</p>
      <ul>
        {view.sources.map((s) => <li key={s.id}><a href={`#/workpackages/${encodeURIComponent(s.id)}`}>{s.name ?? s.id}</a></li>)}
      </ul>
      <p className="small">{t("{{n}} attachment(s): {{m}} to route, {{k}} of another kind", {
        n: view.counts.attachments, m: view.counts.routable, k: view.counts.attachments - view.counts.routable })}</p>
    </section>
  );
}

function Decide({ wpId, view, onChanged }: { wpId: string; view: RoutingView; onChanged: () => void }) {
  useLocale();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [choosing, setChoosing] = useState<string | null>(null);
  const routable = view.items.filter((i) => i.placement.routable);
  const others = view.items.filter((i) => !i.placement.routable);
  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setChoosing(null);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card wide rc-stack" aria-label={t("Routing")}>
      <div className="card-head">
        <h3>{t("Documents to route")}</h3>
        <button type="button" className={view.counts.clear ? "primary" : "secondary"} disabled={busy || !view.counts.clear}
          onClick={() => void act(() => api.routingAcceptClear(wpId))}>
          {t("Accept every clear proposal ({{n}})", { n: view.counts.clear })}
        </button>
      </div>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {routable.length ? (
        <div className="table-scroll">
        <table className="table compact rt-table" aria-label={t("Documents to route")}>
          <thead><tr><th>{t("Document")}</th><th>{t("What it is")}</th><th>{t("Proposal")}</th><th>{t("Decision")}</th></tr></thead>
          <tbody>
            {routable.map((i) => (
              <tr key={i.item_id}>
                <td><strong>{i.file}</strong><div className="small muted">{emailText(i)}</div></td>
                <td>{placementText(i) || <span className="muted">—</span>}</td>
                <td><ProposalCell item={i} /></td>
                <td>
                  {i.decision ? (
                    <span className="inline small">
                      <DecisionMark item={i} />
                      <button type="button" className="quiet small-btn" disabled={busy} onClick={() => void act(() => api.routingUndo(wpId, i.item_id))}>{t("Undo")}</button>
                    </span>
                  ) : choosing === i.item_id ? (
                    <ChooseTarget item={i} busy={busy} onPick={(target) => void act(() => api.routingAccept(wpId, [i.item_id], target))}
                      onCancel={() => setChoosing(null)} />
                  ) : (
                    <span className="rt-actions small">
                      {i.proposal ? <button type="button" className="secondary small-btn" disabled={busy}
                        onClick={() => void act(() => api.routingAccept(wpId, [i.item_id]))}>{t("Accept")}</button> : null}
                      {i.placement.role ? <button type="button" className="secondary small-btn" disabled={busy} onClick={() => setChoosing(i.item_id)}>{t("Choose a package…")}</button> : null}
                      <button type="button" className="quiet small-btn" disabled={busy} onClick={() => void act(() => api.routingReject(wpId, [i.item_id]))}>{t("Do not route")}</button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      ) : <p className="muted">{t("No attachment of these email packages is an invoice or a bank statement.")}</p>}
      {others.length ? (
        <details className="details">
          <summary>{t("Attachments of another kind ({{n}})", { n: others.length })}</summary>
          <ul className="small">{others.map((i) => <li key={i.item_id}>{i.file}{i.doc_type ? ` · ${i.doc_type}` : ""} <span className="muted">{emailText(i)}</span></li>)}</ul>
        </details>
      ) : null}
    </section>
  );
}

function ProposalCell({ item }: { item: RoutingItem }) {
  if (item.decision) return <span className="muted">—</span>;
  if (item.placement.problem) return <span className="status s-warn">{t(BLOCKER[item.placement.problem])}</span>;
  const p = item.proposal;
  if (!p) return <span className="muted">—</span>;
  if (p.target) {
    return (
      <span className="status s-review">
        <a href={`#/workpackages/${encodeURIComponent(p.target.id)}`}>{p.target.name}</a>
        {p.others.length ? <span className="muted"> {t("(+{{n}} more)", { n: p.others.length })}</span> : null}
      </span>
    );
  }
  return <span className="status s-review">{t("New package: {{name}}", { name: p.new!.name })}</span>;
}

function DecisionMark({ item }: { item: RoutingItem }) {
  const d = item.decision!;
  if (d.decision === "rejected") return <span className="status">{t("not routed")}</span>;
  return (
    <span className="status s-done">
      {d.made ? t("added to a new package") : t("added")}{" "}
      {d.target ? <a href={`#/workpackages/${encodeURIComponent(d.target)}`}>{t("open")}</a> : null}
      {item.held === false ? <span className="warn-text"> · {t("removed there since")}</span> : null}
    </span>
  );
}

function ChooseTarget({ item, busy, onPick, onCancel }: { item: RoutingItem; busy: boolean; onPick: (target: string) => void; onCancel: () => void }) {
  useLocale();
  const roles = useLoad("package-roles", api.packageRoles);
  const list = useLoad("workpackages-brief", api.workpackagesBrief);
  const [choice, setChoice] = useState(item.proposal?.target?.id ?? "");
  const kinds = useMemo(() => roles.data?.roles.find((r) => r.name === item.placement.role)?.package_kinds ?? [], [roles.data, item.placement.role]);
  const options = (list.data?.workpackages ?? []).filter((w) => kinds.includes(w.source_kind));
  return (
    <span className="inline small">
      <select value={choice} onChange={(e) => setChoice(e.target.value)} aria-label={t("Package for {{file}}", { file: item.file })}>
        <option value="">{t("Choose…")}</option>
        {options.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
      <button type="button" className="secondary small-btn" disabled={busy || !choice} onClick={() => onPick(choice)}>{t("Add")}</button>
      <button type="button" className="quiet small-btn" onClick={onCancel}>{t("Cancel")}</button>
    </span>
  );
}

function Routed({ view }: { view: RoutingView }) {
  useLocale();
  const accepted = view.items.filter((i) => i.decision?.decision === "accepted");
  const byTarget = new Map<string, RoutingItem[]>();
  for (const i of accepted) byTarget.set(i.decision!.target ?? "", [...(byTarget.get(i.decision!.target ?? "") ?? []), i]);
  const rejected = view.items.filter((i) => i.decision?.decision === "rejected").length;
  return (
    <section className="card wide rc-stack" aria-label={t("Routed documents")}>
      <h3>{t("Routed documents")}</h3>
      {accepted.length ? (
        <table className="table compact rt-table rt-routed" aria-label={t("Routed documents")}>
          <thead><tr><th>{t("Package")}</th><th>{t("Documents")}</th></tr></thead>
          <tbody>
            {[...byTarget.entries()].map(([target, items]) => (
              <tr key={target}>
                <td><a href={`#/workpackages/${encodeURIComponent(target)}`}>{items[0].decision!.target_name ?? target}</a></td>
                <td>{items.map((i) => i.file).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted">{t("Nothing routed yet.")}</p>}
      {rejected ? <p className="small muted">{t("{{n}} document(s) not routed.", { n: rejected })}</p> : null}
      <p className="small muted">{t("A routed document is processed by its package's next run; start it there.")}</p>
    </section>
  );
}

export function RoutingCreate({ onDone }: { onDone: (wpId: string) => void }) {
  useLocale();
  const list = useLoad("workpackages-brief", api.workpackagesBrief);
  const [chosen, setChosen] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mailboxes = (list.data?.workpackages ?? []).filter((w) => w.source_kind === "mailbox");
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const names = mailboxes.filter((w) => chosen.includes(w.id)).map((w) => w.name);
      const view = await api.createRoutingPackage({ name: name.trim() || t("Routing: {{names}}", { names: names.join(", ") }).slice(0, 200), sources: chosen });
      onDone(view.workpackage.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const offer = view.routing_offer;
  if (!offer) return null;
  async function start() {
    setBusy(true);
    setError(null);
    try {
      const made = await api.createRoutingPackage({ name: t("Routing: {{names}}", { names: view.workpackage.name }).slice(0, 200), sources: [view.workpackage.id] });
      go({ view: "workpackages", wpId: made.workpackage.id, stage: "review" });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
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
