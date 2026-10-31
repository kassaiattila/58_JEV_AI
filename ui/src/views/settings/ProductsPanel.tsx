// 231 (stage D, D-c6): the products in Settings: what an offer is built from. Three lists on one segmented control: the
// products (each with its cover modules, the condition documents and the rules its version names, and the tariff it is
// priced by), the rules (each a decision table over the facts of its catalogue, with the page and clause it was read
// from) and the condition documents (their clauses). Each is kept as versions; a draft shows what keeps it from being
// made active and is made active here, a product by another person than its maker; an active one can be retired, and
// stays readable for the cases that keep it. 231 (U3c; the owner's decision of 2026-10-28: the tariff is part of the
// product): the tariffs are a list of this page (until then a Settings item of their own). 263 (plan E, E1; the owner's
// decisions of 2026-10-30): each list is a page of its own and each thing in it too (in the address and in the Settings
// table of contents), no longer a card below its list; a rule a product names opens under its own row.
import { Fragment, useMemo, useState, type ReactNode } from "react";
import type { ConditionDocument, Product, ProductRegistry, RegistryThing, Rule, Tariff } from "../../api";
import { DataTable } from "../../components/DataTable";
import { ItemSteps } from "../../components/ItemSteps";
import { PageActions } from "../../components/PageActions";
import { t, useLocale } from "../../i18n";
import { settingsHash } from "../../route";
import { ProposalsView } from "./ProposalsView";
import { PRODUCT_LISTS, settingsChanged, useSettingsTitle, type ProductList } from "./settingsTree";
import { TariffCard } from "./TariffsPanel";
import {
  Activation, Citation, DecisionTable, DOCUMENT_KIND, documentsByRef, current, inForce, levelLabel, RULE_KIND,
  ThingState, useRegistry, versionOf, VersionLine, VersionPicker, VersionsTable,
} from "./RegistryParts";

/** What each list holds, under its name on the section's page. */
const LIST_WHAT: Record<ProductList, string> = {
  products: "The products an offer is built from: their cover modules, condition documents, rules and tariff",
  tariffs: "How a product's premium is computed: the rates of its cover modules and the factors",
  rules: "The rules read from the condition documents: who and what may be insured, and on what terms",
  documents: "The condition documents and their clauses, which the rules cite",
  proposals: "Rules proposed from a condition document, for a person to accept, correct or reject",
};

/** `list` is the chosen list (none: the section's page), `ident` a thing in it, `open` a rule opened on a product. */
export function ProductsPanel({ list, ident, open }: { list?: string; ident?: string; open?: string }) {
  useLocale();
  const registry = useRegistry();
  if (registry.error) return <p className="notice error" role="alert">{registry.error.message}</p>;
  if (!registry.data) return <p className="muted">{t("Loading…")}</p>;
  const r = registry.data;
  const changed = () => { registry.reload(); settingsChanged(); };
  const counts: Record<ProductList, number | null> = {
    products: r.products.length, tariffs: r.tariffs.length, rules: r.rules.length, documents: r.documents.length, proposals: null,
  };
  const spec = PRODUCT_LISTS.find((l) => l.key === list);
  if (spec && ident) { // a thing's page, with the previous and next thing of its list
    return (
      <>
        <PageActions><ItemSteps list={spec.dataset} /></PageActions>
        <Thing registry={r} list={spec.key} ident={ident} open={open ?? null} onChanged={changed} />
      </>
    );
  }
  // 263 (E1): a list is the one list: searchable, sortable, grouped; a row opens its thing's page
  if (spec?.key === "proposals") return <ProposalsView registry={r} onChanged={changed} />;
  // 263 (F4): an empty list says how one comes, not only "No data."
  if (spec) return <DataTable key={spec.key} dataset={spec.dataset} label={t(spec.label)} storageId={spec.dataset} persist={spec.dataset}
    emptyText={t("There is none yet. A process's example material installs an invented one (Cases › New case, then the process).")} />;
  return ( // the section's page: its lists, each with what it holds and how many
    <table className="table compact registry-table" aria-label={t("Product registry")}>
      <thead><tr><th>{t("List")}</th><th className="num">{t("Count")}</th><th>{t("What it holds")}</th></tr></thead>
      <tbody>
        {PRODUCT_LISTS.map(({ key, label }) => (
          <tr key={key}>
            <td><a className="registry-open" href={settingsHash("products", key)}>{t(label)}</a></td>
            <td className="num">{counts[key] ?? "–"}</td>
            <td className="muted">{t(LIST_WHAT[key])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** One thing of a list, found in the registry (a run of rule proposals is read by its own page). */
function Thing({ registry, list, ident, open, onChanged }: {
  registry: ProductRegistry; list: ProductList; ident: string; open: string | null; onChanged: () => void;
}) {
  useLocale();
  const documents = useMemo(() => documentsByRef(registry.documents), [registry.documents]);
  if (list === "proposals") return <ProposalsView registry={registry} runId={ident} onChanged={onChanged} />;
  const things: RegistryThing<unknown>[] = list === "products" ? registry.products : list === "tariffs" ? registry.tariffs
    : list === "rules" ? registry.rules : registry.documents;
  const thing = things.find((x) => x.ident === ident);
  if (!thing) return <p className="notice warn">{t("It is not in the registry (any more).")}</p>;
  if (list === "products") return <ProductCard key={ident} registry={registry} thing={thing as RegistryThing<Product>} open={open} onChanged={onChanged} />;
  if (list === "tariffs") return <TariffCard key={ident} registry={registry} thing={thing as RegistryThing<Tariff>} onChanged={onChanged} />;
  if (list === "rules") return <RuleCard key={ident} registry={registry} thing={thing as RegistryThing<Rule>} documents={documents} onChanged={onChanged} />;
  return <DocumentCard key={ident} registry={registry} thing={thing as RegistryThing<ConditionDocument>} onChanged={onChanged} />;
}

/** A thing's sheet opens with its version line and, on the right, the version shown. */
function SheetBar<C>({ thing, version, onChange }: { thing: RegistryThing<C>; version: ReturnType<typeof versionOf<C>>; onChange: (n: number) => void }) {
  return (
    <div className="sheet-bar">
      <VersionLine version={version} />
      <VersionPicker thing={thing} version={version.version} onChange={onChange} />
    </div>
  );
}

function ProductCard({ registry, thing, open, onChanged }: {
  registry: ProductRegistry; thing: RegistryThing<Product>; open: string | null; onChanged: () => void;
}) {
  useLocale();
  const [n, setN] = useState(newestDraftOrCurrent(thing));
  const version = versionOf(thing, n);
  const product = version.content;
  const cat = registry.catalogues[product.catalogue];
  const documents = useMemo(() => documentsByRef(registry.documents), [registry.documents]);
  const rules = useMemo(() => new Map(registry.rules.flatMap((r) => r.versions.map((v) => [v.ref, v.content] as const))), [registry.rules]);
  const tariff = product.tariff ? registry.tariffs.find((x) => x.ident === product.tariff) : undefined;
  const names = new Map(product.modules.map((m) => [m.code, m.name]));
  useSettingsTitle(version.name);
  return (
    <section className="sheet registry-card" aria-label={version.name}>
      <SheetBar thing={thing} version={version} onChange={setN} />
      <Activation kind="product" thing={thing} version={version} secondPerson onDone={onChanged} />
      <h4>{t("Cover modules")}</h4>
      <table className="table compact" aria-label={t("Cover modules")}>
        <thead><tr><th>{t("Name")}</th><th>{t("Code")}</th><th>{t("Kind")}</th><th>{t("Needs")}</th></tr></thead>
        <tbody>
          {product.modules.map((m) => (
            <tr key={m.code}>
              <td>{m.name}</td>
              <td className="mono">{m.code}</td>
              <td>{m.kind === "base" ? t("Base cover") : t("Extension")}</td>
              <td>{m.requires.length ? m.requires.map((x) => names.get(x) ?? x).join(", ") : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h4>{t("Condition documents")}</h4>
      <table className="table compact" aria-label={t("Condition documents")}>
        <thead><tr><th>{t("Title")}</th><th>{t("Kind")}</th><th>{t("In force")}</th><th className="num">{t("Clauses")}</th><th>{t("Version")}</th></tr></thead>
        <tbody>
          {product.documents.map((ref) => {
            const d = documents.get(ref);
            return (
              <tr key={ref}>
                <td>{d?.title ?? ref}</td>
                <td>{d ? DOCUMENT_KIND[d.kind] ?? d.kind : "–"}</td>
                <td className="tnum">{d ? inForce(d.valid_from, d.valid_to) : "–"}</td>
                <td className="num">{d?.sections.length ?? "–"}</td>
                <td className="mono">{ref}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <h4>{t("Rules")}</h4>
      <RuleRows refs={product.rules} rules={rules} documents={documents} registry={registry} modules={names} open={open}
        href={(ref) => settingsHash("products", "products", thing.ident, ref === open ? null : ref)} />
      <h4>{t("Tariff")}</h4>
      <p className="registry-line">
        {tariff ? <>{current(tariff).content.title ?? tariff.ident} <ThingState thing={tariff} /> <a href={settingsHash("products", "tariffs", tariff.ident)}>{t("Open the tariff")}</a></>
          : product.tariff ? <span className="error-text">{t("The tariff {{tariff}} is not in the registry.", { tariff: product.tariff })}</span>
            : <span className="muted">{t("No tariff: the product's premium is not computed.")}</span>}
      </p>
      {cat ? null : <p className="notice warn small">{t("The fact catalogue {{id}} is not installed.", { id: product.catalogue })}</p>}
      <h4>{t("Versions")}</h4>
      <VersionsTable thing={thing} />
    </section>
  );
}

/** A card opens on the draft waiting for its activation, else on the version in use. */
const newestDraftOrCurrent = <C,>(thing: RegistryThing<C>) =>
  (thing.versions[0].state === "draft" ? thing.versions[0].version : current(thing).version);

/** A product's rules; the open one shows its whole rule under its own row (its link opens and closes it). */
function RuleRows({ refs, rules, documents, registry, modules, open, href }: {
  refs: string[]; rules: Map<string, Rule>; documents: Map<string, ConditionDocument>; registry: ProductRegistry;
  modules?: Map<string, string>; open: string | null; href: (ref: string) => string;
}) {
  useLocale();
  return (
    <table className="table compact registry-rules" aria-label={t("Rules")}>
      <thead><tr><th>{t("Title")}</th><th>{t("Kind")}</th><th>{t("Level")}</th><th>{t("Cover modules")}</th><th>{t("Read from")}</th></tr></thead>
      <tbody>
        {refs.map((ref) => {
          const rule = rules.get(ref);
          if (!rule) return <tr key={ref}><td colSpan={5} className="error-text">{t("The rule {{rule}} is not in the registry.", { rule: ref })}</td></tr>;
          const cat = registry.catalogues[rule.catalogue];
          const doc = documents.get(rule.source.document);
          return (
            <Fragment key={ref}>
              <tr aria-selected={ref === open}>
                <td><a className="registry-open" href={href(ref)} aria-expanded={ref === open}>{rule.title}</a></td>
                <td>{RULE_KIND[rule.kind] ?? rule.kind}</td>
                <td>{levelLabel(cat, rule.level)}</td>
                <td>{rule.modules.length ? rule.modules.map((m) => modules?.get(m) ?? m).join(", ") : <span className="muted">{t("every module")}</span>}</td>
                <td>{citeShort(rule, doc)}</td>
              </tr>
              {ref === open ? (
                <tr className="row-detail">
                  <td colSpan={5}><RuleDetail rule={rule} title={rule.title} registry={registry} documents={documents} modules={modules} /></td>
                </tr>
              ) : null}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

const citeShort = (rule: Rule, doc?: ConditionDocument) =>
  [doc ? shortTitle(doc.title) : rule.source.document, rule.source.clause ? t("clause {{clause}}", { clause: rule.source.clause }) : null,
    rule.source.page != null ? t("p. {{n}}", { n: rule.source.page }) : null].filter(Boolean).join(" · ");

/** A document's short name: the code in its title's last brackets ("… (GC-2026)"), else the title. */
const shortTitle = (title: string) => /\(([^()]+)\)\s*$/.exec(title)?.[1] ?? title;

function RuleDetail({ rule, title, registry, documents, modules, children }: {
  rule: Rule; title: string; registry: ProductRegistry; documents: Map<string, ConditionDocument>; modules?: Map<string, string>;
  children?: ReactNode;
}) {
  useLocale();
  const cat = registry.catalogues[rule.catalogue];
  return (
    <div className="registry-rule" aria-label={title} role="group">
      <h4>{title}</h4>
      <p className="muted small">
        {RULE_KIND[rule.kind] ?? rule.kind} · {t("on each {{level}}", { level: levelLabel(cat, rule.level) })}
        {" · "}{rule.modules.length ? t("for {{modules}}", { modules: rule.modules.map((m) => modules?.get(m) ?? m).join(", ") }) : t("for every module")}
      </p>
      <DecisionTable rule={rule} cat={cat} />
      <Citation source={rule.source} documents={documents} />
      {children}
    </div>
  );
}

function RuleCard({ registry, thing, documents, onChanged }: {
  registry: ProductRegistry; thing: RegistryThing<Rule>; documents: Map<string, ConditionDocument>; onChanged: () => void;
}) {
  useLocale();
  const [n, setN] = useState(newestDraftOrCurrent(thing));
  const version = versionOf(thing, n);
  const modules = new Map(registry.products.flatMap((p) => current(p).content.modules.map((m) => [m.code, m.name] as const)));
  useSettingsTitle(version.content.title);
  return (
    <section className="sheet registry-card" aria-label={version.content.title}>
      <SheetBar thing={thing} version={version} onChange={setN} />
      <Activation kind="rule" thing={thing} version={version} onDone={onChanged} />
      <RuleDetail rule={version.content} title={t("What it decides")} registry={registry} documents={documents} modules={modules} />
      <h4>{t("Versions")}</h4>
      <VersionsTable thing={thing} />
    </section>
  );
}

function DocumentCard({ registry, thing, onChanged }: {
  registry: ProductRegistry; thing: RegistryThing<ConditionDocument>; onChanged: () => void;
}) {
  useLocale();
  const [n, setN] = useState(newestDraftOrCurrent(thing));
  const version = versionOf(thing, n);
  const doc = version.content;
  useSettingsTitle(doc.title);
  // the rules (in use) that cite each clause of this version
  const citing = new Map<string, string[]>();
  for (const r of registry.rules) {
    const rule = current(r).content;
    if (rule.source.document === version.ref && rule.source.clause) citing.set(rule.source.clause, [...(citing.get(rule.source.clause) ?? []), rule.title]);
  }
  return (
    <section className="sheet registry-card" aria-label={doc.title}>
      <SheetBar thing={thing} version={version} onChange={setN} />
      <p className="muted small">{DOCUMENT_KIND[doc.kind] ?? doc.kind} · {t("in force {{days}}", { days: inForce(doc.valid_from, doc.valid_to) })} · <span className="mono">{version.ref}</span></p>
      <Activation kind="document" thing={thing} version={version} onDone={onChanged} />
      <h4>{t("Clauses")}</h4>
      <table className="table compact" aria-label={t("Clauses")}>
        <thead><tr><th>{t("Clause")}</th><th className="num">{t("Page")}</th><th>{t("Title")}</th><th>{t("Rules read from it")}</th></tr></thead>
        <tbody>
          {doc.sections.map((s) => (
            <tr key={s.clause}>
              <td className="mono">{s.clause}</td>
              <td className="num">{s.page ?? "–"}</td>
              <td>{s.title ?? "–"}</td>
              <td>{citing.get(s.clause)?.join(" · ") ?? <span className="muted">–</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h4>{t("Versions")}</h4>
      <VersionsTable thing={thing} />
    </section>
  );
}
