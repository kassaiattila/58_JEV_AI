// 231 (stage D, D-c6): the parts the Products and the Tariffs sections of Settings share. A product registry thing (a
// product, a condition document, a rule, a tariff) is kept as versions; these show a version's state, its versions, a
// draft's activation (what keeps it from being made active, each problem in the interface's language, and the one solid
// button only when nothing does; a product by another person than its maker), a value or a comparison as a person reads
// it (a code by its catalogue label, an amount with its currency in tabular figures), a rule's decision table and the
// clause it was read from.
import { Fragment, useState, type ReactNode } from "react";
import {
  api, ApiError, type Catalogue, type CatalogueFact, type CatalogueOutcome, type Condition, type ConditionDocument, type Money,
  type RegistryKind, type RegistryThing, type RegistryVersion, type Rule, type Said,
} from "../../api";
import { BlockerList } from "../../components/BlockerList";
import { ConfirmButton } from "../../components/ConfirmButton";
import { PageActions } from "../../components/PageActions";
import { VersionState, versionStateLabel } from "../../components/VersionState";
import { useActor, useLoad } from "../../hooks";
import { getLocale, t, useLocale } from "../../i18n";
import { numText, saidText, tmap, when } from "../../labels";

export const useRegistry = () => useLoad("product-registry", api.productRegistry);

export const RULE_KIND: Record<string, string> = tmap({
  eligibility: "Eligibility", exclusion: "Exclusion", requirement: "Requirement", sublimit: "Sublimit", deductible: "Deductible",
  premium_factor: "Premium factor", valuation: "Valuation", obligation: "Obligation",
});
export const DOCUMENT_KIND: Record<string, string> = tmap({
  general: "General conditions", special: "Special conditions", supplementary: "Supplementary rules", clause: "Clause",
});
const ROUNDING_MODE: Record<string, string> = tmap({ half_up: "half up", half_even: "half to even", down: "down" });
const UNIT: Record<string, string> = { m2: "m²", m3: "m³" };

/** The newest version first (the service's order). */
export const newest = <C,>(thing: RegistryThing<C>) => thing.versions[0];
export const versionOf = <C,>(thing: RegistryThing<C>, n: number | null) => thing.versions.find((v) => v.version === n) ?? newest(thing);
/** The version a list shows: the active one, else the newest. */
export const current = <C,>(thing: RegistryThing<C>) => versionOf(thing, thing.active);

export function day(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(getLocale());
}

export const inForce = (from: string, to: string | null) => (to ? `${day(from)} – ${day(to)}` : t("from {{day}}", { day: day(from) }));
export const amountText = (m: Money) => `${numText(m.amount, 2)} ${m.currency}`;
export const roundingText = (r: { unit: string; mode: string }, currency: string) =>
  t("to {{unit}}, {{mode}}", { unit: `${numText(r.unit, 4)} ${currency}`, mode: ROUNDING_MODE[r.mode] ?? r.mode });

/** A code as its catalogue labels it (translated); one without a label in the code face. */
export function Code({ cat, code }: { cat?: Catalogue; code: string }) {
  const label = cat?.labels[code];
  return label ? <>{t(label)}</> : <span className="mono">{code}</span>;
}

const joined = (nodes: ReactNode[]) => nodes.map((n, i) => <Fragment key={i}>{i ? ", " : null}{n}</Fragment>);

/** A typed value (a fact's, an outcome's) as a person reads it. */
export function Value({ cat, def, value }: { cat?: Catalogue; def?: CatalogueFact | CatalogueOutcome; value: unknown }) {
  useLocale();
  const v = value as Record<string, string>;
  switch (def?.type) {
    case "money": return <span className="tnum">{amountText(value as Money)}</span>;
    case "quantity": return <span className="tnum">{numText(v.value, 3)} {UNIT[v.unit] ?? v.unit}</span>;
    case "percentage": return <span className="tnum">{numText(v.value, 2)} %</span>;
    case "permille": return <span className="tnum">{numText(v.value, 4)} ‰</span>;
    case "bool": return <>{value ? t("Yes") : t("No")}</>;
    case "code": return <Code cat={cat} code={String(value)} />;
    case "codes": return <>{joined((value as string[]).map((c) => <Code key={c} cat={cat} code={c} />))}</>;
    case "count": case "decimal": return <span className="tnum">{numText(value, 4)}</span>;
    default: return <>{typeof value === "object" ? JSON.stringify(value) : String(value)}</>;
  }
}

const SIGN: Record<string, string> = { eq: "=", ne: "≠", lt: "<", lte: "≤", gt: ">", gte: "≥" };

/** A comparison ({op: value}) on a fact or an outcome, as a person reads it: "> 5 000 000 HUF", "one of …". */
export function ConditionText({ cat, def, condition }: { cat?: Catalogue; def?: CatalogueFact | CatalogueOutcome; condition: Condition }) {
  useLocale();
  const parts = Object.entries(condition).map(([op, value]) => {
    if (op in SIGN) return <span key={op}>{SIGN[op]} <Value cat={cat} def={def} value={value} /></span>;
    const values = Array.isArray(value) ? value : [value];
    const list = joined(values.map((x, i) => <Value key={i} cat={cat} def={def} value={x} />));
    if (op === "in") return <span key={op}>{t("one of")} {list}</span>;
    if (op === "not_in") return <span key={op}>{t("none of")} {list}</span>;
    if (op === "between") return <span key={op}><Value cat={cat} def={def} value={values[0]} /> – <Value cat={cat} def={def} value={values[1]} /></span>;
    if (op === "present") return <span key={op}>{value ? t("given") : t("not given")}</span>;
    if (op === "absent") return <span key={op}>{value ? t("not given") : t("given")}</span>;
    return <span key={op} className="mono">{op}</span>;
  });
  return parts.length ? <>{joined(parts)}</> : <span className="dt-any">{t("any")}</span>;
}

export const factTitle = (cat: Catalogue | undefined, name: string) => (cat?.facts[name] ? t(cat.facts[name].title) : name);
export const outcomeTitle = (cat: Catalogue | undefined, name: string) => (cat?.outcomes[name] ? t(cat.outcomes[name].title) : name);
export const levelLabel = (cat: Catalogue | undefined, level: string) => (cat?.labels[level] ? t(cat.labels[level]) : level);

/** A rule's decision table: a row per line, the facts it compares, a double rule, the outcomes it gives. */
export function DecisionTable({ rule, cat }: { rule: Rule; cat?: Catalogue }) {
  useLocale();
  // the outcomes in the catalogue's order (a stored rule's are in the order of their names)
  const known = Object.keys(cat?.outcomes ?? {});
  const rank = (o: string) => (known.includes(o) ? known.indexOf(o) : known.length);
  const outcomes = [...new Set(rule.table.rows.flatMap((r) => Object.keys(r.then)))].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  const compared = rule.facts.filter((f) => rule.table.rows.some((r) => f in r.when));
  return (
    <>
      <table className="table compact decision-table" aria-label={t("Decision table")}>
        <thead>
          <tr>
            <th className="num">#</th>
            {compared.map((f) => <th key={f}>{factTitle(cat, f)}</th>)}
            {outcomes.map((o, i) => <th key={o} className={i ? undefined : "dt-then"}>{outcomeTitle(cat, o)}</th>)}
          </tr>
        </thead>
        <tbody>
          {rule.table.rows.map((row, n) => (
            <tr key={n}>
              <td className="num muted">{n + 1}</td>
              {compared.map((f) => (
                <td key={f}>{row.when[f] ? <ConditionText cat={cat} def={cat?.facts[f]} condition={row.when[f]} /> : <span className="dt-any">{t("any")}</span>}</td>
              ))}
              {outcomes.map((o, i) => (
                <td key={o} className={i ? undefined : "dt-then"}>
                  {o in row.then ? <Value cat={cat} def={cat?.outcomes[o]} value={row.then[o]} /> : <span className="dt-any">–</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">{rule.table.hit === "first" ? t("The first row that fits decides; a row a missing fact leaves open makes the outcome not known.")
        : t("Every row that fits counts; their outcomes combine.")}</p>
    </>
  );
}

/** Where a rule was read from: the document, its page and clause, and the quoted words. */
export function Citation({ source, documents }: { source: Rule["source"]; documents: Map<string, ConditionDocument> }) {
  useLocale();
  const doc = documents.get(source.document);
  const where = [doc?.title ?? source.document, source.page != null ? t("page {{n}}", { n: source.page }) : null,
    source.clause ? t("clause {{clause}}", { clause: source.clause }) : null].filter(Boolean).join(" · ");
  return (
    <figure className="citation">
      <figcaption><span className="muted">{t("Read from")}</span> {where}</figcaption>
      {source.quote ? <blockquote lang="hu">„{source.quote}”</blockquote> : null}
    </figure>
  );
}

/** Every version of a document by its reference (`<id>@<n>`). */
export function documentsByRef(things: RegistryThing<ConditionDocument>[]): Map<string, ConditionDocument> {
  return new Map(things.flatMap((d) => d.versions.map((v) => [v.ref, v.content] as const)));
}

/** A thing's state in a list: its shown version's mark and number, and a newer draft beside it. */
export function ThingState<C>({ thing }: { thing: RegistryThing<C> }) {
  useLocale();
  const shown = current(thing);
  const draft = newest(thing).state === "draft" && newest(thing).version !== shown.version ? newest(thing) : null;
  return (
    <span className="registry-state nowrap">
      <VersionState state={shown.state} /> <span className="muted small tnum">{t("version {{n}}", { n: shown.version })}</span>
      {draft ? <span className="muted small"> · {t("draft {{n}}", { n: draft.version })}</span> : null}
      {thing.example ? <span className="muted small"> · {t("example")}</span> : null}
    </span>
  );
}

/** 231 (U0): an empty registry list, with where its things come from: a process's example material, installed where a
 *  case of the process is started. */
export function NoneYet({ text }: { text: string }) {
  useLocale();
  return (
    <p className="muted">{text} {t("A process's example material installs an invented one: ")}
      <a href="#/cases/new">{t("Cases › New case")}</a>{t(", then the process.")}</p>
  );
}

/** The version a card shows, when there is more than one. */
export function VersionPicker<C>({ thing, version, onChange }: { thing: RegistryThing<C>; version: number; onChange: (n: number) => void }) {
  useLocale();
  if (thing.versions.length < 2) return null;
  return (
    <label className="sr-label">
      <span className="sr-only">{t("Version")}</span>
      <select value={version} onChange={(e) => onChange(Number(e.target.value))}>
        {thing.versions.map((v) => <option key={v.version} value={v.version}>{t("version {{n}}", { n: v.version })} · {versionStateLabel(v.state)}</option>)}
      </select>
    </label>
  );
}

/** Who made a version and who made it active (or retired it), and when. */
export function VersionLine<C>({ version }: { version: RegistryVersion<C> }) {
  useLocale();
  return (
    <p className="registry-line">
      <VersionState state={version.state} />
      <span className="muted small tnum">
        {t("version {{n}}", { n: version.version })} · {t("made by {{who}}, {{when}}", { who: version.made_by ?? "–", when: when(version.made_at) })}
        {version.activated_by ? ` · ${t("made active by {{who}}, {{when}}", { who: version.activated_by, when: when(version.activated_at) })}` : ""}
        {version.retired_by ? ` · ${t("retired by {{who}}, {{when}}", { who: version.retired_by, when: when(version.retired_at) })}` : ""}
      </span>
    </p>
  );
}

export function VersionsTable<C>({ thing }: { thing: RegistryThing<C> }) {
  useLocale();
  return (
    <table className="table compact" aria-label={t("Versions")}>
      <thead><tr><th className="num">{t("Version")}</th><th>{t("State")}</th><th>{t("Made by")}</th><th>{t("Made active by")}</th><th>{t("When")}</th></tr></thead>
      <tbody>
        {thing.versions.map((v) => (
          <tr key={v.version}>
            <td className="num">{v.version}</td>
            <td><VersionState state={v.state} /></td>
            <td>{v.made_by ?? "–"}</td>
            <td>{v.activated_by ?? "–"}</td>
            <td className="tnum">{when(v.retired_at ?? v.activated_at ?? v.made_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function SaidLines({ items, label, warning }: { items: Said[]; label?: string; warning?: boolean }) {
  useLocale();
  return <BlockerList label={label} items={items.map((s, i) => ({ key: `${i}:${s.text}`, warning, content: <span>{saidText(s)}</span> }))} />;
}

/** A draft's activation (what keeps it from being made active, then the button), an active version's retirement. */
export function Activation<C>({ kind, thing, version, secondPerson, onDone }: {
  kind: RegistryKind; thing: RegistryThing<C>; version: RegistryVersion<C>; secondPerson?: boolean; onDone: () => void;
}) {
  useLocale();
  const actor = useActor();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ text: string; problems: Said[] } | null>(null);
  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? { text: e.message, problems: e.detail.problems ?? [] } : { text: String(e), problems: [] });
    } finally {
      setBusy(false);
    }
  }
  const failed = error ? (
    error.problems.length ? (
      <div role="alert"><p className="error-text">{t("It was not made active:")}</p><SaidLines items={error.problems} /></div>
    ) : <p className="notice error" role="alert">{error.text}</p>
  ) : null;
  if (version.state === "draft") {
    const problems = version.problems ?? [];
    const own = !!secondPerson && !!actor && actor === version.made_by;
    const blocked = problems.length > 0 || own || !actor;
    return (
      <div className="registry-activation">
        {problems.length ? (
          <>
            <h4>{t("What keeps it from being made active")}</h4>
            <SaidLines items={problems} label={t("What keeps it from being made active")} />
          </>
        ) : <p className="small ok">{t("Nothing keeps it from being made active.")}</p>}
        {secondPerson ? <p className="muted small">{t("Another person than its maker ({{who}}) makes it active.", { who: version.made_by ?? "–" })}</p> : null}
        {/* 263 (E1): the activation is the page's main action, at the right end of its title row */}
        <PageActions>
          <ConfirmButton className={blocked ? "secondary" : "primary"} disabled={busy || blocked}
            onConfirm={() => void run(() => api.activateRegistryVersion(kind, thing.ident, version.version))}>
            {t("Make version {{n}} active", { n: version.version })}
          </ConfirmButton>
        </PageActions>
        {own ? <p className="muted small">{t("You made this version: another person makes it active.")}</p>
          : !actor ? <p className="muted small">{t("Choose your name at “Who is working?” first.")}</p> : null}
        {failed}
      </div>
    );
  }
  if (version.state === "active") {
    return (
      <div className="registry-activation">
        <PageActions>
          <ConfirmButton className="secondary" disabled={busy} onConfirm={() => void run(() => api.retireRegistryThing(kind, thing.ident))}>{t("Retire")}</ConfirmButton>
        </PageActions>
        <p className="muted small">{t("A retired version stays readable: a case started with it keeps it.")}</p>
        {failed}
      </div>
    );
  }
  return null;
}
