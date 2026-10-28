// 169 (DECISIONS 169): a reconciliation package's inputs as its item list, in Preparation and behind a fold in Pairing —
// the same card as every other package's items (168). The pairing takes the scope's statements and the invoices other
// packages processed, so the list says where each one comes from and which run's result counts. A document can be left
// out of this reconciliation only, with a reason (the owner's choice: it stays in its own package and in every other
// reconciliation), and restored. Files are added to an existing documents or statement package (DECISIONS 168) with the
// same three steps, and processed there, where the run's button shows its cost cap.
import { useState, type FormEvent } from "react";
import { api, ApiError, getActor, type AddSummary, type DsRow } from "../../../api";
import type { ReconcileTarget, ReconcileWorkspace } from "../api";
import { DataTable } from "../../../components/DataTable";
import { Icon } from "../../../components/Icon";
import { useAction, useLoad } from "../../../hooks";
import { t, useLocale } from "../../../i18n";
import { wpHash } from "../../../route";
import { AddDocuments, AddSummaryLine } from "../../../views/PackageAdd";
import { AddStatements } from "../AddStatements";

type TargetKind = "documents" | "statements";

/** The inputs in one line: the documents the pairing takes, by kind, then what is left out. */
function Tally({ ws }: { ws: ReconcileWorkspace }) {
  useLocale();
  const c = ws.counts;
  const statements = c.statements ?? 0;
  const invoices = c.own_invoices ?? 0;
  return (
    <p className="items-tally">
      <strong>{t("{{n}} documents", { n: statements + invoices })}</strong>
      <span>{t("{{n}} statements", { n: statements })}</span>
      <span>{t("{{n}} invoices", { n: invoices })}</span>
      {ws.scope.party_id && c.other_invoices ? <span className="muted">{t("{{n}} invoices of other parties", { n: c.other_invoices })}</span> : null}
      {c.left_out ? <span className="status s-removed">{t("{{n}} left out", { n: c.left_out })}</span> : null}
    </p>
  );
}

function targetText(p: ReconcileTarget): string {
  const span = p.period_start && p.period_end ? ` · ${p.period_start} – ${p.period_end}` : "";
  return p.inputs ? t("{{name}} · {{n}} of its documents are in this reconciliation", { name: p.name, n: p.inputs }) + span
    : t("{{name}} · {{n}} items", { name: p.name, n: p.items }) + span;
}

/** The chosen package's own add form, read fresh (its revision guards the addition). */
function TargetAdd({ target, kind, onDone, onCancel }: {
  target: ReconcileTarget; kind: TargetKind; onDone: (s: AddSummary | null) => void; onCancel: () => void;
}) {
  useLocale();
  const view = useLoad(`wp:${target.id}`, () => api.workpackage(target.id));
  if (view.error) return <p className="notice error" role="alert">{view.error.message}</p>;
  if (!view.data) return <p className="muted small">{t("Loading…")}</p>;
  const note = t("The added files wait for processing in “{{name}}”; once processed there, they take part in this reconciliation.", { name: target.name });
  return kind === "statements"
    ? <AddStatements wp={view.data.workpackage} onCancel={onCancel} onDone={() => onDone(null)} />
    : <AddDocuments wp={view.data.workpackage} source="folder" note={note} onCancel={onCancel} onDone={onDone} />;
}

/** Adding files for the reconciliation: which package they go to, then that package's three steps. */
function AddForReconcile({ wpId, onCancel, onAdded, initial = "documents" }: {
  wpId: string; onCancel: () => void; onAdded: (target: ReconcileTarget, summary: AddSummary | null) => void; initial?: TargetKind;
}) {
  useLocale();
  const targets = useLoad(`reconcile-targets:${wpId}`, () => api.reconcileTargets(wpId));
  const [kind, setKind] = useState<TargetKind>(initial);
  const [chosen, setChosen] = useState<string>("");
  if (targets.error) return <p className="notice error" role="alert">{targets.error.message}</p>;
  if (!targets.data) return <p className="muted small">{t("Loading…")}</p>;
  const list = targets.data[kind];
  const target = list.find((p) => p.id === chosen) ?? list[0] ?? null;
  return (
    <div className="add-target">
      <div className="form-row">
        <fieldset className="segmented">
          <legend className="sr-only">{t("What to add")}</legend>
          <label><input type="radio" name="rc-add-kind" checked={kind === "documents"} onChange={() => { setKind("documents"); setChosen(""); }} /> {t("Invoices")}</label>
          <label><input type="radio" name="rc-add-kind" checked={kind === "statements"} onChange={() => { setKind("statements"); setChosen(""); }} /> {t("Bank statements")}</label>
        </fieldset>
        {list.length ? (
          <label className="block grow">{kind === "documents" ? t("Add them to the documents package") : t("Add them to the statement package")}
            <select value={target?.id ?? ""} onChange={(e) => setChosen(e.target.value)}>
              {list.map((p) => <option key={p.id} value={p.id}>{targetText(p)}</option>)}
            </select>
          </label>
        ) : null}
      </div>
      {target ? (
        <TargetAdd key={`${kind}:${target.id}`} target={target} kind={kind} onCancel={onCancel} onDone={(s) => onAdded(target, s)} />
      ) : (
        <div className="button-row">
          <p className="muted small">{kind === "documents" ? t("There is no open documents package yet; create one from the package list.")
            : t("This party has no statement package yet; create one from the package list.")}</p>
          <button type="button" className="quiet" onClick={onCancel}>{t("Cancel")}</button>
        </div>
      )}
    </div>
  );
}

/** 231 (C2d): `kind` lists only the statements or only the invoices (a pairing case's Statements and Invoices tabs). */
export function ReconcileInputs({ ws, readOnly, onWorkspace, kind }: {
  ws: ReconcileWorkspace; readOnly: boolean; onWorkspace: (ws: ReconcileWorkspace) => void; kind?: "statement" | "invoice";
}) {
  useLocale();
  const wpId = ws.workpackage_id;
  const [showLeftOut, setShowLeftOut] = useState(false);
  const [showOthers, setShowOthers] = useState(false);
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState<{ target: ReconcileTarget; summary: AddSummary | null } | null>(null);
  const [leaving, setLeaving] = useState<{ ids: string[]; name: string } | null>(null);
  const [reason, setReason] = useState("");
  const { busy, error, run } = useAction();
  const leftOut = ws.counts.left_out ?? 0;
  const others = ws.scope.party_id ? ws.counts.other_invoices ?? 0 : 0;

  const act = (call: () => Promise<ReconcileWorkspace>) => run(call, {
    then: (next) => { onWorkspace(next); setLeaving(null); setReason(""); },
    failed: (e) => {
      const err = e as ApiError;
      return err.status === 409 ? t("Someone changed the package meanwhile; it has been reloaded.")
        : err.status === 422 && !getActor() ? t("Choose your name at the top first: the change is recorded with it.") : err.message;
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const why = reason.trim();
    if (leaving && why) void act(() => api.reconcileLeaveOut(wpId, leaving.ids, why));
  }

  const leave = (rows: DsRow[]) => {
    setLeaving({ ids: rows.map((r) => String(r.doc_id)), name: String(rows[0]?.name ?? "") });
    setReason("");
    setAdding(false);
  };
  const cell = (col: { key: string }, row: DsRow) => (col.key === "name" && row._left_out
    ? <span className="removed-name">{String(row.name ?? "")}</span> : undefined);

  return (
    <section className="card wide items-card" aria-label={t("The package's items")}>
      <div className="card-head">
        <div className="items-head">
          <h2>{t("The package's items")}</h2>
          <Tally ws={ws} />
        </div>
        {readOnly || adding ? null : (
          <button type="button" className="secondary" onClick={() => { setAdded(null); setLeaving(null); setAdding(true); }}>
            <Icon name="plus" />{t("Add documents")}</button>
        )}
      </div>
      <p className="muted small">{t("The pairing takes the statements of the scope and the invoices other packages processed. Leaving a document out affects this reconciliation only: it stays in its own package.")}</p>
      {adding ? (
        <AddForReconcile wpId={wpId} onCancel={() => setAdding(false)} initial={kind === "statement" ? "statements" : "documents"}
          onAdded={(target, summary) => { setAdding(false); setAdded({ target, summary }); }} />
      ) : null}
      {added ? (
        <>
          {added.summary ? <AddSummaryLine summary={added.summary} /> : null}
          <div className="items-pending" role="region" aria-label={t("Pending items")}>
            <span className="status s-pending">{t("The files wait for processing in “{{name}}”", { name: added.target.name })}</span>
            <a href={wpHash(added.target.id, "process")}>{t("Process them there")}</a>
          </div>
        </>
      ) : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {leaving ? (
        <form className="form-row inline-form" onSubmit={submit} aria-label={t("Leave out of this reconciliation")}>
          <label className="block grow">{leaving.ids.length === 1 ? t("Why leave “{{name}}” out of this reconciliation?", { name: leaving.name })
            : t("Why leave these documents ({{n}}) out of this reconciliation?", { n: leaving.ids.length })}
            {/* the form opens for this one answer */}
            <input value={reason} maxLength={500} required autoFocus onChange={(e) => setReason(e.target.value)}
              placeholder={t("for example: another company's invoice, a duplicate download")} />
          </label>
          {/* leaving out can be undone (restore), so it is not drawn as destructive */}
          <button type="submit" className="secondary" disabled={busy || !reason.trim()}>{t("Leave out of this reconciliation")}</button>
          <button type="button" className="quiet" onClick={() => { setLeaving(null); setReason(""); }}>{t("Cancel")}</button>
          <p className="muted small form-note">{t("The document stays in its own package and in every other reconciliation, and it can be restored here.")}</p>
        </form>
      ) : null}
      {/* what the decisions read is in the key: after any change the list reloads and the selection clears */}
      <DataTable key={`${wpId}:${JSON.stringify(ws.decision_state ?? null)}:${leftOut}:${kind ?? ""}`} dataset="reconcile_inputs"
        label={t("The package's items")} selectable={!readOnly}
        scope={{ workpackage_id: wpId, ...(showLeftOut ? { left_out: "1" } : {}), ...(showOthers ? { others: "1" } : {}),
          ...(kind ? { kind } : {}) }}
        // U1: the invoices' and the statements' own tabs say which of them is missing
        emptyText={kind === "invoice" ? t("No invoice is in the scope yet: the invoices other packages processed for its party and period show here.")
          : kind === "statement" ? t("No statement is in the scope yet.") : t("No statement or invoice is in the scope yet.")}
        storageId="reconcile_inputs" maxHeight="50vh" cell={cell}
        toolbar={<>
          <label className="check small"><input type="checkbox" checked={showLeftOut} onChange={(e) => setShowLeftOut(e.target.checked)} />
            {" "}{leftOut ? t("Left-out documents too ({{n}})", { n: leftOut }) : t("Left-out documents too")}</label>
          {others && kind !== "statement" ? (
            <label className="check small"><input type="checkbox" checked={showOthers} onChange={(e) => setShowOthers(e.target.checked)} />
              {" "}{t("Other parties' invoices too ({{n}})", { n: others })}</label>
          ) : null}
        </>}
        selectionActions={readOnly ? undefined : (rows) => {
          const inUse = rows.filter((r) => !r._left_out);
          const gone = rows.filter((r) => r._left_out);
          return (
            <>
              {inUse.length ? (
                <button type="button" className="secondary small-btn" disabled={busy} onClick={() => leave(inUse)}>
                  {t("Leave {{n}} out of this reconciliation…", { n: inUse.length })}</button>
              ) : null}
              {gone.length ? (
                <button type="button" className="secondary small-btn" disabled={busy}
                  onClick={() => void act(() => api.reconcileRestoreLeftOut(wpId, gone.map((r) => String(r.doc_id))))}>
                  {t("Restore {{n}}", { n: gone.length })}</button>
              ) : null}
            </>
          );
        }}
        actions={(row) => (
          <>
            {row._wp && row.item_id ? (
              <>
                <a className="small" href={api.sourceUrl(String(row._wp), String(row.item_id))} target="_blank" rel="noreferrer">{t("Open document")}</a>
                <a className="small" href={api.sourceUrl(String(row._wp), String(row.item_id))} download>{t("Download")}</a>
              </>
            ) : null}
            {readOnly ? null : row._left_out ? (
              <button type="button" className="quiet small-btn" disabled={busy}
                onClick={() => void act(() => api.reconcileRestoreLeftOut(wpId, [String(row.doc_id)]))}>{t("Restore")}</button>
            ) : (
              <button type="button" className="quiet small-btn" disabled={busy} onClick={() => leave([row])}>{t("Leave out")}</button>
            )}
          </>
        )} />
    </section>
  );
}
