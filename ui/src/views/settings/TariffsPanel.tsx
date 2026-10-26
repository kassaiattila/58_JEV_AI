// 231 (stage D, D-c6): the tariffs in Settings: what a premium is computed from (the owner's decision of 2026-10-26: a
// tariff store of its own, beside the products). A tariff opens as the order the premium is computed in, the same order
// the itemised calculation follows (`jav/app/rating.py`): each cover module on the units of its level (the basis times
// the rate per thousand), its factors in their order, each read from a fact or an outcome of the rules through its
// table, the line's rounding, a module's minimum, the modules summed, the total factors, the total's rounding and the
// policy minimum. Each tariff is kept as versions; a draft is made active here, an active one retired.
import { useEffect, useRef, useState } from "react";
import type { Catalogue, Factor, ProductRegistry, RegistryThing, Tariff } from "../../api";
import { t, useLocale } from "../../i18n";
import { numText } from "../../labels";
import {
  Activation, amountText, ConditionText, current, factTitle, inForce, levelLabel, outcomeTitle, roundingText, ThingState,
  useRegistry, versionOf, VersionLine, VersionPicker, VersionsTable,
} from "./RegistryParts";

export function TariffsPanel() {
  useLocale();
  const registry = useRegistry();
  const [open, setOpen] = useState<string | null>(null);
  if (registry.error) return <p className="notice error" role="alert">{registry.error.message}</p>;
  if (!registry.data) return <p className="muted">{t("Loading…")}</p>;
  const r = registry.data;
  if (!r.tariffs.length) return <p className="muted">{t("No tariff yet. A product set is added with the command python -m jav.cli product-set --install.")}</p>;
  const chosen = r.tariffs.find((x) => x.ident === open);
  return (
    <div className="registry">
      <table className="table compact registry-table" aria-label={t("Tariffs")}>
        <thead><tr><th>{t("Title")}</th><th>{t("In force")}</th><th>{t("Currency")}</th><th className="num">{t("Cover modules")}</th><th className="num">{t("Policy minimum")}</th><th>{t("State")}</th></tr></thead>
        <tbody>
          {r.tariffs.map((x) => {
            const c = current(x).content;
            return (
              <tr key={x.ident} aria-selected={x.ident === open}>
                <td><button type="button" className="link-btn registry-open" onClick={() => setOpen(x.ident)}>{c.title ?? x.ident}</button></td>
                <td className="tnum">{inForce(c.valid.valid_from, c.valid.valid_to)}</td>
                <td className="mono">{c.currency}</td>
                <td className="num">{Object.keys(c.modules).length}</td>
                <td className="num">{c.policy_minimum ? amountText(c.policy_minimum) : "–"}</td>
                <td><ThingState thing={x} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {chosen ? <TariffCard key={chosen.ident} registry={r} thing={chosen} onClose={() => setOpen(null)} onChanged={registry.reload} /> : null}
    </div>
  );
}

function TariffCard({ registry, thing, onClose, onChanged }: {
  registry: ProductRegistry; thing: RegistryThing<Tariff>; onClose: () => void; onChanged: () => void;
}) {
  useLocale();
  const [n, setN] = useState(thing.versions[0].state === "draft" ? thing.versions[0].version : current(thing).version);
  const version = versionOf(thing, n);
  const tariff = version.content;
  // the products it prices name its modules and the catalogue its facts are of
  const products = registry.products.map((p) => current(p).content).filter((p) => p.tariff === thing.ident);
  const cat: Catalogue | undefined = registry.catalogues[products[0]?.catalogue ?? Object.keys(registry.catalogues)[0]];
  const moduleName = new Map(products.flatMap((p) => p.modules.map((m) => [m.code, m.name] as const)));
  const factorTitle = (name: string) => tariff.factors[name]?.title ?? name;
  // in the order the products list their cover modules (a stored tariff's modules are in the order of their codes)
  const order = [...moduleName.keys()];
  const rank = (code: string) => (order.includes(code) ? order.indexOf(code) : order.length);
  const modules = Object.entries(tariff.modules).sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.scrollIntoView?.({ block: "nearest" }); heading.current?.focus(); }, [thing.ident]);
  const title = tariff.title ?? thing.ident;
  return (
    <section className="card wide registry-card" aria-label={title}>
      <div className="card-head">
        <h3 ref={heading} tabIndex={-1}>{title}</h3>
        <span className="button-row">
          <VersionPicker thing={thing} version={version.version} onChange={setN} />
          <button type="button" className="quiet small-btn" onClick={onClose}>{t("Close")}</button>
        </span>
      </div>
      <VersionLine version={version} />
      <p className="muted small">
        {t("In force {{days}}", { days: inForce(tariff.valid.valid_from, tariff.valid.valid_to) })} · {t("in {{currency}}", { currency: tariff.currency })}
        {products.length ? ` · ${t("prices {{products}}", { products: products.map((p) => p.name).join(", ") })}` : ""}
      </p>
      <Activation kind="tariff" thing={thing} version={version} onDone={onChanged} />
      <h4>{t("How the premium is computed")}</h4>
      <ol className="calc-steps">
        <li>
          <span className="step-no tnum" aria-hidden="true">1</span>
          <div>
            <p>{t("Each cover module on the units of its level: the basis times the rate per thousand, then its factors in their order.")}</p>
            <table className="table compact" aria-label={t("Cover modules")}>
              <thead><tr><th>{t("Cover module")}</th><th>{t("Level")}</th><th>{t("Basis")}</th><th className="num">{t("Rate")}</th><th>{t("Prices only")}</th><th>{t("Factors")}</th><th className="num">{t("Minimum")}</th></tr></thead>
              <tbody>
                {modules.map(([code, m]) => (
                  <tr key={code}>
                    <td>{moduleName.get(code) ?? <span className="mono">{code}</span>}</td>
                    <td>{levelLabel(cat, m.level)}</td>
                    <td>{factTitle(cat, m.basis)}</td>
                    <td className="num nowrap">{numText(m.rate.value, 4)} ‰</td>
                    <td>{Object.keys(m.only).length ? Object.entries(m.only).map(([f, c]) => (
                      <span key={f}>{factTitle(cat, f)} <ConditionText cat={cat} def={cat?.facts[f]} condition={c} /></span>
                    )) : <span className="muted">{t("every unit")}</span>}</td>
                    <td>{m.factors.length ? m.factors.map(factorTitle).join(" → ") : "–"}</td>
                    <td className="num nowrap">{m.minimum ? amountText(m.minimum) : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </li>
        <li>
          <span className="step-no tnum" aria-hidden="true">2</span>
          <p>{t("Each line rounded {{rounding}}.", { rounding: roundingText(tariff.line_rounding, tariff.currency) })}</p>
        </li>
        <li>
          <span className="step-no tnum" aria-hidden="true">3</span>
          <p>{t("A cover module's lines summed; below its minimum, the minimum. The modules summed in {{currency}}.", { currency: tariff.currency })}</p>
        </li>
        <li>
          <span className="step-no tnum" aria-hidden="true">4</span>
          <p>{tariff.total_factors.length ? t("The sum times the total factors: {{factors}}.", { factors: tariff.total_factors.map(factorTitle).join(" → ") })
            : t("No total factor.")}</p>
        </li>
        <li>
          <span className="step-no tnum" aria-hidden="true">5</span>
          <p>{t("The total rounded {{rounding}}", { rounding: roundingText(tariff.total_rounding, tariff.currency) })}
            {tariff.policy_minimum ? `; ${t("below the policy minimum of {{amount}}, the minimum.", { amount: amountText(tariff.policy_minimum) })}` : "."}</p>
        </li>
      </ol>
      <p className="muted small">{t("A missing factor, a value no row takes, a cover start the tariff is not in force on or an amount in another currency gives no total: never a default.")}</p>
      <h4>{t("Factors")}</h4>
      <div className="factor-grid">
        {Object.entries(tariff.factors).map(([name, f]) => <FactorTable key={name} factor={f} cat={cat} />)}
      </div>
      <h4>{t("Versions")}</h4>
      <VersionsTable thing={thing} />
    </section>
  );
}

function FactorTable({ factor, cat }: { factor: Factor; cat?: Catalogue }) {
  useLocale();
  const def = factor.fact ? cat?.facts[factor.fact] : factor.outcome ? cat?.outcomes[factor.outcome] : undefined;
  const reads = factor.fact ? factTitle(cat, factor.fact) : factor.outcome ? outcomeTitle(cat, factor.outcome) : "–";
  return (
    <div className="factor">
      <p className="factor-head"><strong>{factor.title}</strong> <span className="muted small">{factor.fact ? t("reads the fact {{name}}", { name: reads }) : t("reads the rules' outcome {{name}}", { name: reads })}</span></p>
      {factor.table.length ? (
        <table className="table compact" aria-label={factor.title}>
          <thead><tr><th>{t("When")}</th><th className="num">{t("Factor")}</th></tr></thead>
          <tbody>
            {factor.table.map((row, i) => (
              <tr key={i}>
                <td><ConditionText cat={cat} def={def} condition={row.when} /></td>
                <td className="num">× {numText(row.factor, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted small">{t("The outcome's value is the factor.")}</p>}
    </div>
  );
}
