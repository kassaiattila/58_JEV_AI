// 231 (stage D, D-f4): the elements of an assessment's data check: the field review of a field check's step (its units
// with where each fact came from, the disagreements a person settles, a unit's facts corrected, and the freeze with the
// day cover starts), the facts a step read from the case's documents (document_facts), and an outside register's
// question and answer (lookup). Each renders the data its step's capability gives (jav/app/field_check.py,
// jav/app/fact_claims.py, jav/app/lookups.py); a person's actions go through the step's action endpoint with the state of
// the page they were made on.
import { Fragment, useState } from "react";
import { api, type AssessedUnit, type DocumentFactsData, type FieldReviewData, type LookupData, type OfferedClaim } from "../api";
import type { Catalogue, CatalogueFact } from "../api/products";
import { errorText } from "../hooks";
import { t, useLocale } from "../i18n";
import { docTypeLabel, when } from "../labels";
import { day, factTitle, levelLabel, Value } from "../views/settings/RegistryParts";
import { fieldReviewStatus } from "./caseStatus";
import type { ElementProps } from "./registry";

const loading = <p className="muted">{t("Loading…")}</p>;

/** A step's action with values, then the page again. */
function useAct(p: ElementProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (name: string, values?: Record<string, unknown>, note?: string) => {
    if (!p.element.step) return false;
    setBusy(true);
    setError(null);
    try {
      await api.caseStepAction(p.caseId, p.element.step, name, note, values);
      p.onChanged();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

/** A unit's name as a person reads it: the company's, the site's address, the asset group's kind. */
function unitName(cat: Catalogue, u: AssessedUnit): string {
  const f = u.facts;
  if (typeof f.company_name === "string") return f.company_name;
  if (typeof f.site_address === "string") return f.site_address;
  if (typeof f.asset_group === "string") return cat.labels[f.asset_group] ? t(cat.labels[f.asset_group]) : f.asset_group;
  return u.unit_id;
}

/** The units in their tree's order: a parent, then its children. */
function ordered(units: AssessedUnit[]): { unit: AssessedUnit; depth: number }[] {
  const live = units.filter((u) => !u.removed);
  const out: { unit: AssessedUnit; depth: number }[] = [];
  const visit = (parent: string | null, depth: number) => {
    for (const u of live.filter((x) => (x.parent_id ?? null) === parent)) {
      out.push({ unit: u, depth });
      visit(u.unit_id, depth + 1);
    }
  };
  visit(null, 0);
  return out;
}

function Source({ s }: { s: AssessedUnit["sources"][string] | undefined }) {
  const src = s?.source;
  if (!src) return <span className="faint">–</span>;
  const where = [src.file, src.page ? t("page {{n}}", { n: src.page }) : null].filter(Boolean).join(" · ");
  const reading = s?.interpretation?.reading?.startsWith("lookup:") ? t("register") : null;
  return (
    <span className="muted small">
      {where || reading || "–"}{src.quote ? <> · <q>{src.quote}</q></> : null}
    </span>
  );
}

// --- editing a unit's facts ------------------------------------------------------------------------------------------

const asNumber = (s: string) => s.replace(/[\s ]/g, "").replace(",", ".");

function shown(def: CatalogueFact, value: unknown): string {
  if (value === undefined || value === null) return "";
  const v = value as Record<string, unknown>;
  switch (def.type) {
    case "money": return String(v.amount ?? "");
    case "quantity": case "percentage": case "permille": return String(v.value ?? "");
    case "bool": return value ? "yes" : "no";
    case "codes": return (value as string[]).join(", ");
    default: return String(value);
  }
}

function typed(def: CatalogueFact, text: string): unknown {
  const s = text.trim();
  if (!s) return undefined;
  switch (def.type) {
    case "money": return { amount: asNumber(s), currency: def.currency };
    case "quantity": return { value: asNumber(s), unit: def.unit };
    case "percentage": case "permille": return { value: asNumber(s) };
    case "count": return Number.parseInt(asNumber(s), 10);
    case "decimal": return asNumber(s);
    case "bool": return s === "yes";
    case "codes": return s.split(",").map((x) => x.trim()).filter(Boolean);
    default: return s;
  }
}

function FactInput({ cat, def, value, onChange, label }: {
  cat: Catalogue; def: CatalogueFact; value: string; onChange: (v: string) => void; label: string;
}) {
  if (def.type === "bool") {
    return (
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">–</option><option value="yes">{t("Igen")}</option><option value="no">{t("Nem")}</option>
      </select>
    );
  }
  const name = (o: string) => (cat.labels[o] ? t(cat.labels[o]) : o);
  if (def.type === "code" && def.options) {
    return (
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">–</option>
        {def.options.map((o) => <option key={o} value={o}>{name(o)}</option>)}
      </select>
    );
  }
  if (def.type === "codes" && def.options) {
    // U1 (finding 15 of the walkthrough): a list of codes from its options is ticked, each by its name
    const options = def.options;
    const chosen = new Set(value.split(",").map((x) => x.trim()).filter(Boolean));
    const toggle = (o: string, on: boolean) => {
      const next = new Set(chosen);
      if (on) next.add(o); else next.delete(o);
      onChange([...options.filter((x) => next.has(x)), ...[...next].filter((x) => !options.includes(x))].join(", "));
    };
    return (
      <div className="check-list" role="group" aria-label={label}>
        {options.map((o) => (
          <label key={o} className="check">
            <input type="checkbox" checked={chosen.has(o)} onChange={(e) => toggle(o, e.target.checked)} /> {name(o)}
          </label>
        ))}
      </div>
    );
  }
  const unit = def.type === "money" ? def.currency : def.type === "quantity" ? (def.unit === "m2" ? "m²" : def.unit)
    : def.type === "percentage" ? "%" : null;
  // U1: a free code (or list of codes) the catalogue names reads by its name beside the input
  const named = def.type === "code" || def.type === "codes"
    ? value.split(",").map((x) => x.trim()).filter((x) => x && cat.labels[x]).map((x) => t(cat.labels[x])).join(", ") : "";
  return (
    <span className="fact-input">
      <input aria-label={label} type={def.type === "date" ? "date" : "text"} value={value}
        inputMode={["money", "quantity", "percentage", "permille", "count", "decimal"].includes(def.type) ? "decimal" : undefined}
        onChange={(e) => onChange(e.target.value)} />
      {unit ? <span className="muted small">{unit}</span> : null}
      {named ? <span className="muted small">{named}</span> : null}
    </span>
  );
}

function UnitRows({ cat, unit, depth, editing, onEdit, act }: {
  cat: Catalogue; unit: AssessedUnit; depth: number; editing: boolean; onEdit: (on: boolean) => void;
  act: ReturnType<typeof useAct>;
}) {
  const defs = Object.entries(cat.facts).filter(([, d]) => d.level === unit.level);
  const initial = Object.fromEntries(defs.map(([n, d]) => [n, shown(d, unit.facts[n])]));
  const [draft, setDraft] = useState<Record<string, string>>(initial);
  const changed = defs.some(([n]) => draft[n] !== initial[n]);
  const save = async () => {
    const facts: Record<string, unknown> = {};
    for (const [n, d] of defs) {
      const v = typed(d, draft[n] ?? "");
      if (v !== undefined) facts[n] = v;
    }
    if (await act.run("unit_save", { unit_id: unit.unit_id, facts, expected_state: unit.state, note: null })) onEdit(false);
  };
  const rows = editing ? defs.map(([n]) => n) : defs.map(([n]) => n).filter((n) => n in unit.facts);
  return (
    <>
      <tr className="unit-head">
        <th colSpan={3} scope="rowgroup" style={{ paddingLeft: `${8 + depth * 16}px` }}>
          <span className="muted">{levelLabel(cat, unit.level)}</span> · {unitName(cat, unit)}
        </th>
        <td className="num">
          {editing ? (
            <span className="button-row end">
              <button type="button" className={changed ? "primary small-btn" : "secondary small-btn"} disabled={!changed || act.busy}
                onClick={() => void save()}>{t("Save the unit")}</button>
              <button type="button" className="quiet small-btn" disabled={act.busy} onClick={() => { setDraft(initial); onEdit(false); }}>{t("Cancel")}</button>
            </span>
          ) : <button type="button" className="quiet small-btn" onClick={() => onEdit(true)}>{t("Edit")}</button>}
        </td>
      </tr>
      {rows.map((n) => (
        <tr key={n}>
          <td style={{ paddingLeft: `${20 + depth * 16}px` }}>{factTitle(cat, n)}</td>
          <td className="fact-value">
            {editing ? <FactInput cat={cat} def={cat.facts[n]} value={draft[n] ?? ""} label={factTitle(cat, n)}
              onChange={(v) => setDraft((d) => ({ ...d, [n]: v }))} />
              : <Value cat={cat} def={cat.facts[n]} value={unit.facts[n]} />}
          </td>
          <td colSpan={2}>{editing ? null : <Source s={unit.sources[n]} />}</td>
        </tr>
      ))}
    </>
  );
}

// --- the field review ------------------------------------------------------------------------------------------------

function Conflicts({ d, p, act }: { d: FieldReviewData; p: ElementProps; act: ReturnType<typeof useAct> }) {
  const open = d.claims.filter((c) => c.open);
  if (!open.length) return null;
  const units = new Map(d.units.map((u) => [u.unit_id, u]));
  const take = (c: OfferedClaim) => {
    const u = c.unit_id ? units.get(c.unit_id) : undefined;
    if (!u) return;
    const by = p.page.steps[c.from_step]?.title;
    void act.run("unit_save", { unit_id: u.unit_id, facts: { ...u.facts, [c.fact]: c.value }, expected_state: u.state,
                                note: t("taken from {{step}}", { step: by ? t(by) : c.from_step }) });
  };
  return (
    <section aria-label={t("What the sources disagree on")}>
      <h3 className="todo-text">{t("What the sources disagree on: {{n}}", { n: open.length })}</h3>
      <table className="table compact">
        <thead><tr><th>{t("Assessed unit")}</th><th>{t("Fact")}</th><th>{t("Now")}</th><th>{t("Offered by")}</th><th>{t("Offered")}</th><th /></tr></thead>
        <tbody>
          {open.map((c, i) => {
            const u = c.unit_id ? units.get(c.unit_id) : undefined;
            const def = d.catalogue.facts[c.fact];
            const by = p.page.steps[c.from_step]?.title;
            return (
              <tr key={`${c.unit_key}-${c.fact}-${i}`}>
                <td>{u ? unitName(d.catalogue, u) : c.unit_key}</td>
                <td>{factTitle(d.catalogue, c.fact)}</td>
                <td>{u ? <Value cat={d.catalogue} def={def} value={u.facts[c.fact]} /> : "–"}</td>
                <td>{by ? t(by) : c.from_step}</td>
                <td><Value cat={d.catalogue} def={def} value={c.value} /></td>
                <td className="num">
                  {d.waits ? (
                    <span className="button-row">
                      <button type="button" className="secondary small-btn" disabled={act.busy}
                        onClick={() => void act.run("keep_value", { claim_key: c.claim_key })}>{t("Keep the value shown")}</button>
                      <button type="button" className="secondary small-btn" disabled={act.busy} onClick={() => take(c)}>{t("Take this value")}</button>
                    </span>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="muted small">{t("A value the sources give differently is never chosen by the system: keep the one shown, or take the other.")}</p>
    </section>
  );
}

function Freeze({ d, act }: { d: FieldReviewData; act: ReturnType<typeof useAct> }) {
  const [start, setStart] = useState(d.cover_start_hint ?? "");  // U1: a document's day, else the last freeze's
  const ready = d.conflicts === 0 && !!start;
  return (
    <div className="freeze">
      <div className="field">
        <label htmlFor="cover-start">{t("Cover starts")}</label>
        <input id="cover-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
      </div>
      <div className="button-row">
        <button type="button" className={ready ? "primary" : "secondary"} disabled={!ready || act.busy}
          onClick={() => void act.run("freeze", { cover_start: start, expected_state: d.state })}>{t("Freeze the facts")}</button>
        {d.conflicts ? <span className="todo-text small">{t("Settle the disagreements first.")}</span>
          : !start ? <span className="muted small">{t("Give the day cover starts.")}</span> : null}
      </div>
      <p className="muted small">{t("Freezing records the facts as they are now as the checked input: the rules and the premium are computed from it, and a later correction makes a new one.")}</p>
    </div>
  );
}

function Reopen({ act }: { act: ReturnType<typeof useAct> }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  if (!open) return <div className="button-row"><button type="button" className="secondary small-btn" onClick={() => setOpen(true)}>{t("Reopen the check")}</button></div>;
  return (
    <div className="button-row">
      <input aria-label={t("Why it is reopened")} placeholder={t("Why it is reopened")} value={reason} onChange={(e) => setReason(e.target.value)} />
      <button type="button" className="secondary small-btn" disabled={!reason.trim() || act.busy}
        onClick={() => void act.run("reopen", undefined, reason.trim())}>{t("Reopen")}</button>
      <button type="button" className="quiet small-btn" onClick={() => setOpen(false)}>{t("Cancel")}</button>
    </div>
  );
}

export function FieldReview(p: ElementProps) {
  useLocale();
  const d = p.element.data as FieldReviewData | null;
  const act = useAct(p);
  const [editing, setEditing] = useState<string | null>(null);
  if (!d) return loading;
  const state = fieldReviewStatus(d);
  const unplaced = d.claims.filter((c) => c.placement === "unplaced");
  const tree = ordered(d.units);
  return (
    <section className="card wide" aria-label={t("Data check")}>
      <div className="card-head">
        <h2>{t("Data check")}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      {d.frozen ? (
        <>
          <p className="notice ok-box">{t("Frozen as version {{n}} by {{who}}, {{when}}; cover starts {{day}}.",
            { n: d.frozen.version, who: d.frozen.by, when: when(d.frozen.at), day: day(d.frozen.cover_start) })}</p>
          <Reopen act={act} />
        </>
      ) : null}
      <Conflicts d={d} p={p} act={act} />
      {tree.length ? (
        <table className="table compact facts-ledger" aria-label={t("The units and their facts")}>
          <thead><tr><th>{t("Fact")}</th><th>{t("Value")}</th><th colSpan={2}>{t("Source")}</th></tr></thead>
          {tree.map(({ unit, depth }) => (
            <tbody key={unit.unit_id}>
              <UnitRows cat={d.catalogue} unit={unit} depth={depth} editing={editing === unit.unit_id && d.waits}
                onEdit={(on) => setEditing(on ? unit.unit_id : null)} act={act} />
            </tbody>
          ))}
        </table>
      ) : <p className="muted small">{t("No unit yet: the documents and the registers offer none.")}</p>}
      {unplaced.length ? (
        <ul className="plain" aria-label={t("Not placed")}>
          {unplaced.map((c, i) => (
            <li key={i} className="warning">{t("{{fact}} of {{unit}} was not placed: the unit it belongs to is not there.",
              { fact: factTitle(d.catalogue, c.fact), unit: c.unit_key })}</li>
          ))}
        </ul>
      ) : null}
      {d.waits ? <Freeze d={d} act={act} /> : null}
      {act.error ? <p className="notice error small" role="alert">{act.error}</p> : null}
    </section>
  );
}

// --- the facts read from the documents ------------------------------------------------------------------------------

export function DocumentFacts(p: ElementProps) {
  useLocale();
  const d = p.element.data as DocumentFactsData | null;
  if (!d) return loading;
  const title = p.element.step ? p.page.steps[p.element.step]?.title : null;
  return (
    <section className="card" aria-label={title ? t(title) : t("Facts from the documents")}>
      <div className="card-head">
        <h2>{title ? t(title) : t("Facts from the documents")}</h2>
        <span className="muted small tnum">{t("{{n}} document(s)", { n: d.documents.length })}</span>
      </div>
      {d.documents.length ? (
        <table className="table compact">
          <thead><tr><th>{t("Document")}</th><th>{t("Type")}</th><th className="num">{t("Facts")}</th></tr></thead>
          <tbody>
            {d.documents.map((doc) => (
              <Fragment key={doc.item}>
                <tr>
                  <td>{doc.file}</td>
                  <td>{docTypeLabel(doc.doc_type)}</td>
                  <td className="num">{doc.note ? <span className="muted">{t("not read: another type")}</span> : doc.claims}</td>
                </tr>
                {doc.unread.length ? (
                  <tr>
                    <td colSpan={3}>
                      <ul className="plain">
                        {doc.unread.map((u, i) => (
                          <li key={i} className="warning">{t("{{fact}}: “{{value}}” was not read ({{why}})",
                            { fact: d.catalogue ? factTitle(d.catalogue, u.fact) : u.fact,
                              value: Array.isArray(u.value) ? u.value.join(", ") : String(u.value), why: t(u.why) })}</li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      ) : <p className="muted small">{d.state === "done" ? t("The case has no processed document.") : t("The documents are not processed yet.")}</p>}
    </section>
  );
}

// --- an outside register ---------------------------------------------------------------------------------------------

export function lookupStatus(d: LookupData | null, state: string | undefined): { mark: string; text: string } | null {
  if (!d || !state) return null;
  if (state === "failed") return { mark: "s-failed", text: t("No answer") };
  if (state !== "done") return { mark: state === "running" ? "s-running" : "s-waiting", text: state === "running" ? t("Asking") : t("Waits") };
  if (!d.asked) return { mark: "s-waiting", text: t("Not asked") };
  return { mark: "s-done", text: d.claims.length ? t("Answered") : t("Not found") };
}

export function LookupView(p: ElementProps) {
  useLocale();
  const d = p.element.data as LookupData | null;
  const act = useAct(p);
  if (!d) return loading;
  const step = p.element.step ? p.page.steps[p.element.step] : undefined;
  const state = lookupStatus(d, step?.state ?? undefined);
  const cat = d.catalogue ?? undefined;
  const asked = Object.entries(d.question);
  return (
    <section className="card" aria-label={step?.title ? t(step.title) : t("Register")}>
      <div className="card-head">
        <h2>{step?.title ? t(step.title) : d.connector}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      {d.what ? <p className="muted small">{t(d.what)}</p> : null}
      {asked.length ? (
        <dl className="kv">
          {asked.map(([k, v]) => <Fragment key={k}><dt>{t("Asked with")}</dt>
            <dd>{cat?.facts[k] ? <>{factTitle(cat, k)}: <Value cat={cat} def={cat.facts[k]} value={v} /></> : `${k}: ${String(v)}`}</dd></Fragment>)}
        </dl>
      ) : null}
      {d.claims.length ? (
        <table className="table compact" aria-label={t("What the register says")}>
          <thead><tr><th>{t("Fact")}</th><th>{t("Value")}</th></tr></thead>
          <tbody>
            {d.claims.map((c, i) => (
              <tr key={i}><td>{cat ? factTitle(cat, c.fact) : c.fact}</td>
                <td>{cat ? <Value cat={cat} def={cat.facts[c.fact]} value={c.value} /> : String(c.value)}</td></tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {d.asked === false && d.missing.length ? (
        <p className="muted small">{t("Not asked: the documents give no {{facts}}.", { facts: d.missing.map((m) => (cat ? factTitle(cat, m) : m)).join(", ") })}</p>
      ) : null}
      {step?.state === "failed" ? (
        <>
          {step.note ? <p className="status long s-failed">{t(step.note)}</p> : null}
          <div className="button-row">
            <button type="button" className="secondary small-btn" disabled={act.busy} onClick={() => void act.run("retry")}>{t("Try again")}</button>
          </div>
        </>
      ) : null}
      {act.error ? <p className="notice error small" role="alert">{act.error}</p> : null}
    </section>
  );
}
