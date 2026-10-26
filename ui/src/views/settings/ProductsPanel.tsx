// 231 (stage D, D-c6): the products in Settings: what an offer is built from. Three lists on one segmented control: the
// products (each with its cover modules, the condition documents and the rules its version names, and the tariff it is
// priced by), the rules (each a decision table over the facts of its catalogue, with the page and clause it was read
// from) and the condition documents (their clauses). Each is kept as versions; a draft shows what keeps it from being
// made active and is made active here, a product by another person than its maker; an active one can be retired, and
// stays readable for the cases that keep it.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { ConditionDocument, Product, ProductRegistry, RegistryThing, Rule } from "../../api";
import { t, useLocale } from "../../i18n";
import {
  Activation, Citation, DecisionTable, DOCUMENT_KIND, documentsByRef, current, inForce, levelLabel, RULE_KIND,
  ThingState, useRegistry, versionOf, VersionLine, VersionPicker, VersionsTable,
} from "./RegistryParts";

type View = "products" | "rules" | "documents";
type Open = { view: View; ident: string } | null;

export function ProductsPanel() {
  useLocale();
  const registry = useRegistry();
  const [view, setView] = useState<View>("products");
  const [open, setOpen] = useState<Open>(null);
  if (registry.error) return <p className="notice error" role="alert">{registry.error.message}</p>;
  if (!registry.data) return <p className="muted">{t("Loading…")}</p>;
  const r = registry.data;
  const views: [View, string, number][] = [["products", t("Products"), r.products.length], ["rules", t("Rules"), r.rules.length],
    ["documents", t("Condition documents"), r.documents.length]];
  const show = (v: View, ident: string) => { setView(v); setOpen({ view: v, ident }); };
  return (
    <div className="registry">
      <div className="segmented-tabs" role="tablist" aria-label={t("Product registry")}>
        {views.map(([key, label, n]) => (
          <button key={key} type="button" role="tab" className="seg" aria-selected={view === key} onClick={() => setView(key)}>
            {label} <span className="tnum muted">{n}</span>
          </button>
        ))}
      </div>
      {view === "products" ? <ProductsView registry={r} open={open?.view === "products" ? open.ident : null} onOpen={(i) => show("products", i)}
        onClose={() => setOpen(null)} onChanged={registry.reload} /> : null}
      {view === "rules" ? <RulesView registry={r} open={open?.view === "rules" ? open.ident : null} onOpen={(i) => show("rules", i)}
        onClose={() => setOpen(null)} onChanged={registry.reload} /> : null}
      {view === "documents" ? <DocumentsView registry={r} open={open?.view === "documents" ? open.ident : null} onOpen={(i) => show("documents", i)}
        onClose={() => setOpen(null)} onChanged={registry.reload} /> : null}
    </div>
  );
}

interface ViewProps { registry: ProductRegistry; open: string | null; onOpen: (ident: string) => void; onClose: () => void; onChanged: () => void }

function ProductsView({ registry, open, onOpen, onClose, onChanged }: ViewProps) {
  useLocale();
  const tariffs = new Map(registry.tariffs.map((x) => [x.ident, x]));
  if (!registry.products.length) return <p className="muted">{t("No product yet. A product set is added with the command python -m jav.cli product-set --install.")}</p>;
  const chosen = registry.products.find((p) => p.ident === open);
  return (
    <>
      <table className="table compact registry-table" aria-label={t("Products")}>
        <thead><tr><th>{t("Name")}</th><th>{t("State")}</th><th>{t("Cover modules")}</th><th className="num">{t("Rules")}</th><th>{t("Tariff")}</th></tr></thead>
        <tbody>
          {registry.products.map((p) => {
            const c = current(p).content;
            const tariff = c.tariff ? tariffs.get(c.tariff) : undefined;
            return (
              <tr key={p.ident} aria-selected={p.ident === open}>
                <td><button type="button" className="link-btn registry-open" onClick={() => onOpen(p.ident)}>{current(p).name}</button></td>
                <td><ThingState thing={p} /></td>
                <td>{c.modules.map((m) => m.name).join(" · ")}</td>
                <td className="num">{c.rules.length}</td>
                <td>{tariff ? current(tariff).content.title ?? tariff.ident : c.tariff ? <span className="mono">{c.tariff}</span> : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {chosen ? <ProductCard key={chosen.ident} registry={registry} thing={chosen} onClose={onClose} onChanged={onChanged} /> : null}
    </>
  );
}

function useScrolled(ident: string) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    ref.current?.scrollIntoView?.({ block: "nearest" });
    ref.current?.focus();
  }, [ident]);
  return ref;
}

function ProductCard({ registry, thing, onClose, onChanged }: {
  registry: ProductRegistry; thing: RegistryThing<Product>; onClose: () => void; onChanged: () => void;
}) {
  useLocale();
  const [n, setN] = useState(newestDraftOrCurrent(thing));
  const version = versionOf(thing, n);
  const product = version.content;
  const cat = registry.catalogues[product.catalogue];
  const documents = useMemo(() => documentsByRef(registry.documents), [registry.documents]);
  const rules = useMemo(() => new Map(registry.rules.flatMap((r) => r.versions.map((v) => [v.ref, v.content] as const))), [registry.rules]);
  const tariff = product.tariff ? registry.tariffs.find((x) => x.ident === product.tariff) : undefined;
  const [rule, setRule] = useState<string | null>(null);
  const heading = useScrolled(thing.ident);
  const names = new Map(product.modules.map((m) => [m.code, m.name]));
  return (
    <section className="card wide registry-card" aria-label={version.name}>
      <div className="card-head">
        <h3 ref={heading} tabIndex={-1}>{version.name}</h3>
        <span className="button-row">
          <VersionPicker thing={thing} version={version.version} onChange={setN} />
          <button type="button" className="quiet small-btn" onClick={onClose}>{t("Close")}</button>
        </span>
      </div>
      <VersionLine version={version} />
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
      <RuleRows refs={product.rules} rules={rules} documents={documents} registry={registry} modules={names} open={rule} onOpen={setRule} />
      {rule && rules.get(rule) ? (
        <RuleDetail key={rule} rule={rules.get(rule)!} title={rules.get(rule)!.title} registry={registry} documents={documents}
          modules={names} onClose={() => setRule(null)} />
      ) : null}
      <h4>{t("Tariff")}</h4>
      <p className="registry-line">
        {tariff ? <>{current(tariff).content.title ?? tariff.ident} <ThingState thing={tariff} /> <a href="#/settings/tariffs">{t("Open the tariffs")}</a></>
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

function RuleRows({ refs, rules, documents, registry, modules, open, onOpen }: {
  refs: string[]; rules: Map<string, Rule>; documents: Map<string, ConditionDocument>; registry: ProductRegistry;
  modules?: Map<string, string>; open: string | null; onOpen: (ref: string) => void;
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
            <tr key={ref} aria-selected={ref === open}>
              <td><button type="button" className="link-btn registry-open" onClick={() => onOpen(ref)}>{rule.title}</button></td>
              <td>{RULE_KIND[rule.kind] ?? rule.kind}</td>
              <td>{levelLabel(cat, rule.level)}</td>
              <td>{rule.modules.length ? rule.modules.map((m) => modules?.get(m) ?? m).join(", ") : <span className="muted">{t("every module")}</span>}</td>
              <td>{citeShort(rule, doc)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

const citeShort = (rule: Rule, doc?: ConditionDocument) =>
  [doc ? shortTitle(doc.title) : rule.source.document, rule.source.clause ? t("clause {{clause}}", { clause: rule.source.clause }) : null,
    rule.source.page != null ? t("p. {{n}}", { n: rule.source.page }) : null].filter(Boolean).join(" · ");

/** A document's short name: the code in its title's last brackets ("… (KB-ÁF-2026)"), else the title. */
const shortTitle = (title: string) => /\(([^()]+)\)\s*$/.exec(title)?.[1] ?? title;

function RuleDetail({ rule, title, registry, documents, modules, onClose, children }: {
  rule: Rule; title: string; registry: ProductRegistry; documents: Map<string, ConditionDocument>; modules?: Map<string, string>;
  onClose?: () => void; children?: ReactNode;
}) {
  useLocale();
  const cat = registry.catalogues[rule.catalogue];
  return (
    <div className="registry-rule" aria-label={title} role="group">
      <div className="card-head">
        <h4>{title}</h4>
        {onClose ? <button type="button" className="quiet small-btn" onClick={onClose}>{t("Close")}</button> : null}
      </div>
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

function RulesView({ registry, open, onOpen, onClose, onChanged }: ViewProps) {
  useLocale();
  const documents = useMemo(() => documentsByRef(registry.documents), [registry.documents]);
  if (!registry.rules.length) return <p className="muted">{t("No rule yet.")}</p>;
  const chosen = registry.rules.find((r) => r.ident === open);
  return (
    <>
      <table className="table compact registry-table" aria-label={t("Rules")}>
        <thead><tr><th>{t("Title")}</th><th>{t("Kind")}</th><th>{t("Level")}</th><th>{t("Read from")}</th><th>{t("State")}</th></tr></thead>
        <tbody>
          {registry.rules.map((r) => {
            const rule = current(r).content;
            return (
              <tr key={r.ident} aria-selected={r.ident === open}>
                <td><button type="button" className="link-btn registry-open" onClick={() => onOpen(r.ident)}>{rule.title}</button></td>
                <td>{RULE_KIND[rule.kind] ?? rule.kind}</td>
                <td>{levelLabel(registry.catalogues[rule.catalogue], rule.level)}</td>
                <td>{citeShort(rule, documents.get(rule.source.document))}</td>
                <td><ThingState thing={r} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {chosen ? <RuleCard key={chosen.ident} registry={registry} thing={chosen} documents={documents} onClose={onClose} onChanged={onChanged} /> : null}
    </>
  );
}

function RuleCard({ registry, thing, documents, onClose, onChanged }: {
  registry: ProductRegistry; thing: RegistryThing<Rule>; documents: Map<string, ConditionDocument>; onClose: () => void; onChanged: () => void;
}) {
  useLocale();
  const [n, setN] = useState(newestDraftOrCurrent(thing));
  const version = versionOf(thing, n);
  const heading = useScrolled(thing.ident);
  const modules = new Map(registry.products.flatMap((p) => current(p).content.modules.map((m) => [m.code, m.name] as const)));
  return (
    <section className="card wide registry-card" aria-label={version.content.title}>
      <div className="card-head">
        <h3 ref={heading} tabIndex={-1}>{version.content.title}</h3>
        <span className="button-row">
          <VersionPicker thing={thing} version={version.version} onChange={setN} />
          <button type="button" className="quiet small-btn" onClick={onClose}>{t("Close")}</button>
        </span>
      </div>
      <VersionLine version={version} />
      <Activation kind="rule" thing={thing} version={version} onDone={onChanged} />
      <RuleDetail rule={version.content} title={t("What it decides")} registry={registry} documents={documents} modules={modules} />
      <h4>{t("Versions")}</h4>
      <VersionsTable thing={thing} />
    </section>
  );
}

function DocumentsView({ registry, open, onOpen, onClose, onChanged }: ViewProps) {
  useLocale();
  if (!registry.documents.length) return <p className="muted">{t("No condition document yet.")}</p>;
  const chosen = registry.documents.find((d) => d.ident === open);
  return (
    <>
      <table className="table compact registry-table" aria-label={t("Condition documents")}>
        <thead><tr><th>{t("Title")}</th><th>{t("Kind")}</th><th>{t("In force")}</th><th className="num">{t("Clauses")}</th><th>{t("State")}</th></tr></thead>
        <tbody>
          {registry.documents.map((d) => {
            const doc = current(d).content;
            return (
              <tr key={d.ident} aria-selected={d.ident === open}>
                <td><button type="button" className="link-btn registry-open" onClick={() => onOpen(d.ident)}>{doc.title}</button></td>
                <td>{DOCUMENT_KIND[doc.kind] ?? doc.kind}</td>
                <td className="tnum">{inForce(doc.valid_from, doc.valid_to)}</td>
                <td className="num">{doc.sections.length}</td>
                <td><ThingState thing={d} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {chosen ? <DocumentCard key={chosen.ident} registry={registry} thing={chosen} onClose={onClose} onChanged={onChanged} /> : null}
    </>
  );
}

function DocumentCard({ registry, thing, onClose, onChanged }: {
  registry: ProductRegistry; thing: RegistryThing<ConditionDocument>; onClose: () => void; onChanged: () => void;
}) {
  useLocale();
  const [n, setN] = useState(newestDraftOrCurrent(thing));
  const version = versionOf(thing, n);
  const doc = version.content;
  const heading = useScrolled(thing.ident);
  // the rules (in use) that cite each clause of this version
  const citing = new Map<string, string[]>();
  for (const r of registry.rules) {
    const rule = current(r).content;
    if (rule.source.document === version.ref && rule.source.clause) citing.set(rule.source.clause, [...(citing.get(rule.source.clause) ?? []), rule.title]);
  }
  return (
    <section className="card wide registry-card" aria-label={doc.title}>
      <div className="card-head">
        <h3 ref={heading} tabIndex={-1}>{doc.title}</h3>
        <span className="button-row">
          <VersionPicker thing={thing} version={version.version} onChange={setN} />
          <button type="button" className="quiet small-btn" onClick={onClose}>{t("Close")}</button>
        </span>
      </div>
      <VersionLine version={version} />
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
