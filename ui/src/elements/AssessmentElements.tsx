// 231 (stage D, D-f5): the elements of an assessment's calculation: a rule evaluation (its verdict, the facts it missed,
// its blockers, each unit's outcomes with the rules that gave them), the wait for missing facts (what is missing, the
// task's deadline or how it ended, and saying with a reason that they will not come), and a premium's computation from
// its tariff (each line, the modules' minimums, the total under the ledger's double rule). The evaluation and the premium
// keep a record per version; the earlier ones are a quiet fold. Each renders the data its step's capability gives
// (jav/app/evaluation_steps.py, jav/app/missing_info.py).
import { Fragment, useState } from "react";
import { api, type CalculationData, type EvaluatedUnit, type EvaluationData, type MissingInfoData, type PremiumMoney, type PremiumStep } from "../api";
import type { Catalogue } from "../api/products";
import { errorText } from "../hooks";
import { t, useLocale } from "../i18n";
import { numText, saidText, when } from "../labels";
import { amountText, factTitle, levelLabel, outcomeTitle, Value } from "../views/settings/RegistryParts";
import { calculationStatus, missingStatus, VERDICT, verdictStatus } from "./caseStatus";
import type { ElementProps } from "./registry";

const loading = <p className="muted">{t("Loading…")}</p>;

/** How a person tells a unit: the company, the site's address, the asset group's kind. */
function unitName(cat: Catalogue | undefined, named: Record<string, unknown>, fallback: string): string {
  if (typeof named.company_name === "string") return named.company_name;
  if (typeof named.site_address === "string") return named.site_address;
  if (typeof named.asset_group === "string") return cat?.labels[named.asset_group] ? t(cat.labels[named.asset_group]) : named.asset_group;
  return fallback;
}

const money = (m: PremiumMoney | null | undefined) => (m ? amountText(m) : "–");

function Outcomes({ cat, unit }: { cat: Catalogue | undefined; unit: EvaluatedUnit }) {
  const entries = Object.entries(unit.combined);
  if (!entries.length) return <span className="faint">–</span>;
  return (
    <ul className="plain outcomes">
      {entries.map(([name, value]) => (
        <li key={name}><span className="muted">{outcomeTitle(cat, name)}:</span> <Value cat={cat} def={cat?.outcomes[name]} value={value} /></li>
      ))}
    </ul>
  );
}

export function EvaluationView(p: ElementProps) {
  useLocale();
  const d = p.element.data as EvaluationData | null;
  if (!d) return loading;
  const title = p.element.step ? p.page.steps[p.element.step]?.title : null;
  const latest = d.latest;
  const cat = d.catalogue ?? undefined;
  const state = verdictStatus(d);
  const byId = new Map((latest?.units ?? []).map((u) => [u.unit_id, u]));
  return (
    <section className="card wide" aria-label={title ? t(title) : t("Rules")}>
      <div className="card-head">
        <h2>{title ? t(title) : t("Rules")}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      {!latest ? <p className="muted small">{t("The rules are evaluated once the facts are frozen.")}</p> : (
        <>
          <p className="muted small">{t("Version {{n}}, from the checked input's version {{m}}; the modules evaluated: {{modules}}.", {
            n: latest.version, m: latest.input_version,
            modules: latest.modules.length ? latest.modules.map((m) => (cat?.labels[m] ? t(cat.labels[m]) : m)).join(", ") : t("every module (the input names none)") })}</p>
          {latest.missing.length ? (
            <ul className="plain" aria-label={t("Missing facts")}>
              {latest.missing.map((m, i) => (
                <li key={i} className="todo-text">{t("{{fact}} of {{unit}} is missing", { fact: t(m.title),
                  unit: unitName(cat, byId.get(m.unit_id)?.named ?? {}, m.unit_id) })}</li>
              ))}
            </ul>
          ) : null}
          {latest.blockers.length ? <ul className="plain">{latest.blockers.map((b, i) => <li key={i} className="blocker">{b}</li>)}</ul> : null}
          <table className="table compact" aria-label={t("Each unit's outcomes")}>
            <thead><tr><th>{t("Assessed unit")}</th><th>{t("Outcomes")}</th><th>{t("By the rules")}</th></tr></thead>
            <tbody>
              {latest.units.map((u) => {
                const depth = Math.max(0, (cat?.levels ?? []).indexOf(u.level));
                const gave = Object.entries(u.rules).filter(([, r]) => r.matched.length || r.missing.length);
                return (
                  <tr key={u.unit_id}>
                    <td style={{ paddingLeft: `${8 + depth * 16}px` }}>
                      <span className="muted small">{levelLabel(cat, u.level)}</span><div>{unitName(cat, u.named, u.unit_id)}</div>
                    </td>
                    <td><Outcomes cat={cat} unit={u} /></td>
                    <td>
                      {gave.length ? (
                        <ul className="plain small">
                          {gave.map(([ref, r]) => (
                            <li key={ref}>{d.rules[ref] ? t(d.rules[ref].title) : ref}
                              {r.missing.length ? <span className="todo-text"> · {t("undecided: {{facts}}", { facts: r.missing.map((f) => factTitle(cat, f)).join(", ") })}</span> : null}</li>
                          ))}
                        </ul>
                      ) : <span className="faint">–</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <EarlierVersions rows={d.versions.slice(1).map((v) => ({ version: v.version, from: v.input_version, at: v.made_at,
            what: v.verdict ? VERDICT[v.verdict] ?? v.verdict : "–" }))} from={t("Checked input")} />
        </>
      )}
    </section>
  );
}

function EarlierVersions({ rows, from }: { rows: { version: number; from: number; at: string; what: string }[]; from: string }) {
  if (!rows.length) return null;
  return (
    <details className="earlier">
      <summary className="muted small">{t("Earlier versions ({{n}})", { n: rows.length })}</summary>
      <table className="table compact">
        <thead><tr><th className="num">{t("Version")}</th><th className="num">{from}</th><th>{t("Outcome")}</th><th>{t("When")}</th></tr></thead>
        <tbody>
          {rows.map((r) => <tr key={r.version}><td className="num">{r.version}</td><td className="num">{r.from}</td><td>{r.what}</td>
            <td className="tnum">{when(r.at)}</td></tr>)}
        </tbody>
      </table>
    </details>
  );
}

// --- the premium -----------------------------------------------------------------------------------------------------

function Factors({ steps, names }: { steps: PremiumStep[]; names: Record<string, string | null> }) {
  if (!steps.length) return <span className="faint">–</span>;
  return <>{steps.map((s, i) => <Fragment key={s.name}>{i ? ", " : null}{names[s.name] ? t(names[s.name]!) : s.name} ×{numText(s.factor, 4)}</Fragment>)}</>;
}

export function CalculationView(p: ElementProps) {
  useLocale();
  const d = p.element.data as CalculationData | null;
  if (!d) return loading;
  const title = p.element.step ? p.page.steps[p.element.step]?.title : null;
  const latest = d.latest;
  const state = calculationStatus(d);
  const factors = d.tariff?.factors ?? {};
  const cat = d.catalogue;
  const unit = (id: string) => (d.units?.[id] ? unitName(cat, d.units[id].named, id) : id);
  const module = (code: string) => (d.modules?.[code] ? t(d.modules[code]) : code);
  return (
    <section className="card wide" aria-label={title ? t(title) : t("Premium")}>
      <div className="card-head">
        <h2>{title ? t(title) : t("Premium")}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      {!latest ? <p className="muted small">{t("The premium is computed once the risk is accepted.")}</p> : (
        <>
          <p className="muted small">{t("Version {{n}}, from the evaluation's version {{m}}, by the tariff {{tariff}}.", {
            n: latest.version, m: latest.evaluation_version, tariff: d.tariff?.title ? t(d.tariff.title) : latest.tariff_ref })}</p>
          {latest.blockers_said?.length
            ? <ul className="plain">{latest.blockers_said.map((b, i) => <li key={i} className="blocker">{saidText(b)}</li>)}</ul>
            : latest.blockers.length ? <ul className="plain">{latest.blockers.map((b, i) => <li key={i} className="blocker">{b}</li>)}</ul> : null}
          {latest.lines.length ? (
            <table className="table compact premium-lines" aria-label={t("The premium's lines")}>
              <thead><tr><th>{t("Module")}</th><th>{t("Assessed unit")}</th><th className="num">{t("Basis")}</th>
                <th className="num">{t("Base premium")}</th><th>{t("Factors")}</th><th className="num">{t("Amount")}</th></tr></thead>
              <tbody>
                {latest.modules.map((m) => {
                  const lines = latest.lines.filter((l) => l.module === m);
                  const total = latest.module_totals[m];
                  return (
                    <Fragment key={m}>
                      {lines.map((l, i) => (
                        <tr key={`${m}-${l.unit_id}-${i}`}>
                          <td>{i === 0 ? module(m) : null}</td><td>{unit(l.unit_id)}</td>
                          <td className="num">{money(l.basis)}</td><td className="num">{money(l.base)}</td>
                          <td><Factors steps={l.steps} names={factors} /></td><td className="num">{money(l.amount)}</td>
                        </tr>
                      ))}
                      {total ? (
                        <tr className="module-total">
                          <td colSpan={5}>{t("{{module}} together", { module: module(m) })}
                            {total.minimum_applied ? <span className="muted"> · {t("the module's minimum applies")}</span> : null}</td>
                          <td className="num">{money(total.total)}</td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          ) : null}
          {latest.total_steps.length ? (
            <p className="small">{t("On the whole: {{factors}}", { factors: latest.total_steps.map((s) => `${factors[s.name] ? t(factors[s.name]!) : s.name} ×${numText(s.factor, 4)}`).join(", ") })}</p>
          ) : null}
          {latest.total ? (
            <div className="ledger-total">
              <span>{t("Premium")}</span><strong className="tnum">{money(latest.total)}</strong>
              {latest.policy_minimum_applied ? <span className="muted small">{t("the policy's minimum applies")}</span> : null}
            </div>
          ) : null}
          <EarlierVersions rows={d.versions.slice(1).map((v) => ({ version: v.version, from: v.input_version, at: v.made_at,
            what: v.blockers ? t("Blocked") : money(v.total) }))} from={t("Evaluation")} />
        </>
      )}
    </section>
  );
}

// --- the missing facts -----------------------------------------------------------------------------------------------

export function MissingInfoView(p: ElementProps) {
  useLocale();
  const d = p.element.data as MissingInfoData | null;
  const [reason, setReason] = useState("");
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!d) return loading;
  const title = p.element.step ? p.page.steps[p.element.step]?.title : null;
  const state = missingStatus(d);
  const open = d.task?.status === "open";
  const giveUp = async () => {
    if (!p.element.step) return;
    setBusy(true);
    setError(null);
    try {
      await api.caseStepAction(p.caseId, p.element.step, "will_not_come", reason.trim());
      p.onChanged();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card" aria-label={title ? t(title) : t("Missing facts")}>
      <div className="card-head">
        <h2>{title ? t(title) : t("Missing facts")}</h2>
        {state ? <span className={`status ${state.mark}`}>{state.text}</span> : null}
      </div>
      {d.missing.length ? (
        <ul className="plain">
          {d.missing.map((m, i) => (
            <li key={i} className={open ? "todo-text" : undefined}>
              {d.units?.[m.unit_id] ? t("{{fact}} of {{unit}} is missing", { fact: t(m.title),
                unit: d.units[m.unit_id].label ? t(d.units[m.unit_id].label!) : unitName(undefined, d.units[m.unit_id].named, m.unit_id) }) : t(m.title)}
            </li>
          ))}
        </ul>
      ) : null}
      {open ? (
        <>
          <p className="small">{t("Get them by {{day}}: enter them in the Data check (reopen it) and freeze it again; the rules are evaluated again.", { day: when(d.task?.due_at) })}</p>
          <p className="muted small">{t("If they do not come by then, the case closes.")}</p>
          {asking ? (
            <div className="button-row">
              <input aria-label={t("Why they will not come")} placeholder={t("Why they will not come")} value={reason} onChange={(e) => setReason(e.target.value)} />
              <button type="button" className="secondary small-btn" disabled={!reason.trim() || busy} onClick={() => void giveUp()}>{t("The facts will not come")}</button>
              <button type="button" className="quiet small-btn" onClick={() => setAsking(false)}>{t("Cancel")}</button>
            </div>
          ) : <div className="button-row"><button type="button" className="secondary small-btn" onClick={() => setAsking(true)}>{t("The facts will not come")}</button></div>}
        </>
      ) : d.task?.note ? <p className="muted small">{d.task.note}</p> : null}
      {error ? <p className="notice error small" role="alert">{error}</p> : null}
    </section>
  );
}
