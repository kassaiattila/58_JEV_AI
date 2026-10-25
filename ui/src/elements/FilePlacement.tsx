// 181 (plan 170 L5; DECISIONS 181) the email routing's own pages; 231 (plan stage C, C1c) a special screen element of the
// file routing capability (`jav/domains/email/capabilities.py`): for every document that arrived by email it proposes
// the package it belongs to (the open package whose party, period and role fit it, or a new one); a person accepts the
// proposals one by one or every clear one at once, rejects them or chooses another package. An attachment the routing
// cannot place by itself shows why (an amber mark); a document of another kind is only listed. The element shows the
// email packages it routes (show: sources), the routing itself (show: decide) or what went where (show: routed).
import { useMemo, useState } from "react";
import { api, type RoutingBlocker, type RoutingItem, type RoutingNote, type RoutingView, type WorkpackageView } from "../api";
import { useAction, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { docTypeLabel } from "../labels";
import type { Stage } from "../route";
import type { ElementProps } from "./registry";

export const BLOCKER: Record<RoutingBlocker, string> = {
  no_result: "Not processed yet: its email package's run has not read it",
  no_data: "Read, but it has no data: see its to-dos in its email package",
  unknown_party: "No own party: neither its buyer nor its supplier is an own party's",
  unclear_direction: "Unclear whether it is incoming or outgoing",
  internal: "An invoice between two own parties: choose its package",
  not_own: "Neither side is an own party",
  no_day: "No date to place it in a period",
  suspicious: "It came with a suspicious email",
};

// 183 (DECISIONS 183): shown under a proposal; it does not keep the proposal from being accepted
const NOTE: Record<RoutingNote, string> = {
  sent_incoming: "An incoming invoice in a sent email",
};

/** 187: the attachment's decision state as this page read it, sent back with a change. */
function stateOf(item: RoutingItem): Record<string, number> | undefined {
  return item.decision_state === undefined ? undefined : { [item.item_id]: item.decision_state };
}

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
  const { busy, error, run } = useAction();
  const [choosing, setChoosing] = useState<string | null>(null);
  const routable = view.items.filter((i) => i.placement.routable);
  const others = view.items.filter((i) => !i.placement.routable);
  // a new package is named with its role's title in the interface's language
  const titles = Object.fromEntries(routable.filter((i) => i.placement.role && i.placement.role_title)
    .map((i) => [i.placement.role as string, t(i.placement.role_title as string)]));
  const act = (fn: () => Promise<unknown>) => run(fn, { then: () => { setChoosing(null); onChanged(); } });
  return (
    <section className="card wide rc-stack" aria-label={t("Routing")}>
      <div className="card-head">
        <h3>{t("Documents to route")}</h3>
        <button type="button" className={view.counts.clear ? "primary" : "secondary"} disabled={busy || !view.counts.clear}
          onClick={() => void act(() => api.routingAcceptClear(wpId, titles))}>
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
                      <button type="button" className="quiet small-btn" disabled={busy} onClick={() => void act(() => api.routingUndo(wpId, i.item_id, i.decision_state))}>{t("Undo")}</button>
                    </span>
                  ) : choosing === i.item_id ? (
                    <ChooseTarget item={i} busy={busy} onPick={(target) => void act(() => api.routingAccept(wpId, [i.item_id], target, undefined, stateOf(i)))}
                      onCancel={() => setChoosing(null)} />
                  ) : (
                    <span className="rt-actions small">
                      {i.proposal ? <button type="button" className="secondary small-btn" disabled={busy}
                        onClick={() => void act(() => api.routingAccept(wpId, [i.item_id], undefined, titles, stateOf(i)))}>{t("Accept")}</button> : null}
                      {i.placement.role ? <button type="button" className="secondary small-btn" disabled={busy} onClick={() => setChoosing(i.item_id)}>{t("Choose a package…")}</button> : null}
                      <button type="button" className="quiet small-btn" disabled={busy} onClick={() => void act(() => api.routingReject(wpId, [i.item_id], stateOf(i)))}>{t("Do not route")}</button>
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
          <ul className="small">{others.map((i) => <li key={i.item_id}>{i.file}{i.doc_type ? ` · ${docTypeLabel(i.doc_type)}` : ""} <span className="muted">{emailText(i)}</span></li>)}</ul>
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
  const note = item.placement.note ? <div className="small muted">{t(NOTE[item.placement.note])}</div> : null;
  if (p.target) {
    return (
      <>
        <span className="status s-review">
          <a href={`#/workpackages/${encodeURIComponent(p.target.id)}`}>{p.target.name}</a>
          {p.others.length ? <span className="muted"> {t("(+{{n}} more)", { n: p.others.length })}</span> : null}
        </span>
        {note}
      </>
    );
  }
  const n = p.new!;
  const name = item.placement.role_title ? [n.party, n.period_start.slice(0, 7), t(item.placement.role_title)].join(" · ") : n.name;
  return <><span className="status s-review">{t("New package: {{name}}", { name })}</span>{note}</>;
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

/** 231 (C1c): the routing on a routing case's tab, by the element's `show` setting (the routing view is its data). */
export function FilePlacement({ caseId, element, onChanged }: ElementProps) {
  useLocale();
  const view = element.data as RoutingView | null;
  if (!view) return <p className="muted">{t("Loading…")}</p>;
  if (element.show === "sources") return <Sources view={view} />;
  if (element.show === "decide") return <Decide wpId={caseId} view={view} onChanged={onChanged} />;
  return <Routed view={view} />;
}
