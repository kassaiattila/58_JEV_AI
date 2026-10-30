// 231 (stage D, D-c6): the tariffs in Settings: what a premium is computed from (the owner's decision of 2026-10-26: a
// tariff store of its own, beside the products). A tariff opens as the order the premium is computed in, the same order
// the itemised calculation follows (`jav/app/rating.py`): each cover module on the units of its level (the basis times
// the rate per thousand), its factors in their order, each read from a fact or an outcome of the rules through its
// table, the line's rounding, a module's minimum, the modules summed, the total factors, the total's rounding and the
// policy minimum. Each tariff is kept as versions; a draft is made active here, an active one retired. 263 (E1): the
// list is the Products section's (the one list); a tariff is a page of its own.
import { useState } from "react";
import type { Catalogue, Factor, ProductRegistry, RegistryThing, Tariff } from "../../api";
import { UsedBy, useUsedBy } from "../../components/UsedBy";
import { useSettingsTitle } from "./settingsTree";
import { t, useLocale } from "../../i18n";
import { numText } from "../../labels";
import {
  Activation, amountText, ConditionText, current, factTitle, inForce, levelLabel, outcomeTitle, roundingText,
  versionOf, VersionLine, VersionPicker, VersionsTable,
} from "./RegistryParts";

export function TariffCard({ registry, thing, onChanged }: {
  registry: ProductRegistry; thing: RegistryThing<Tariff>; onChanged: () => void;
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
  const title = tariff.title ?? thing.ident;
  useSettingsTitle(title);
  const used = useUsedBy("tariff");
  return (
    <section className="sheet registry-card" aria-label={title}>
      <div className="sheet-bar">
        <VersionLine version={version} />
        <span className="button-row"><UsedBy used={used} ident={thing.ident} /><VersionPicker thing={thing} version={version.version} onChange={setN} /></span>
      </div>
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
