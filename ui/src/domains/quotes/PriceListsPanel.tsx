// Price lists (191, plan F-quote-package B2, DECISIONS 191): the seller's price lists a quote is priced from. A price
// list is an Excel or CSV file with one row per item (its code, name, unit, net unit price and, optionally, its
// category); the service reads the file the system's file picker chose and checks it, and a refused file names every
// problem with its row. A stored list is a version: a draft, then active; a list can be retired. The rules that lower a
// price (a volume discount), the currency and the VAT rate are set here, not in the file (the owner's decision);
// saving them makes a new draft version with the same items, so a version never changes and a quote names one.
import { useMemo, useState } from "react";
import { api, ApiError, type OutputTemplateIssue } from "../../api";
import type { PriceList, PriceListCheck, PriceListColumn, PriceListDetail, PriceListVersion, PriceListsListing, PriceRule } from "./api";
import { BlockerList } from "../../components/BlockerList";
import { BrowseButton } from "../../components/BrowseButton";
import { ConfirmButton } from "../../components/ConfirmButton";
import { Icon } from "../../components/Icon";
import { Picker } from "../../components/Picker";
import { VersionState } from "../../components/VersionState";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { editNumber, fold, moneyText, numText, when } from "../../labels";

const COLUMNS: PriceListColumn[] = ["sku", "name", "unit", "unit_price", "category"];
export const columnName = (c: PriceListColumn) => ({
  sku: t("Item code"), name: t("Item name"), unit: t("Unit"), unit_price: t("Net unit price"), category: t("Category"),
})[c] ?? c;


/** A check's problem or warning in words; where it is (`Sheet!5`, `rule 2`) and the detail are shown beside it. */
export function priceIssueText(code: string): string {
  const text: Record<string, string> = {
    too_large: t("The file is too large."),
    not_a_table: t("The file is not an Excel workbook (.xlsx) or a CSV file."),
    unreadable: t("The file cannot be read."),
    missing_column: t("A column the price list needs is missing:"),
    sku_missing: t("The item code is missing."),
    duplicate_sku: t("An earlier row has the same item code."),
    name_missing: t("The name is missing."),
    unit_missing: t("The unit is missing."),
    price_missing: t("The unit price is missing."),
    price_not_number: t("The unit price is not a number."),
    price_ambiguous: t("The unit price can be read two ways (such as 28.5); write it as 28,5 or 28 500."),
    price_negative: t("The unit price is negative."),
    no_items: t("The file has no item under its header row."),
    too_many_items: t("The file has more items than a price list may have."),
    other_sheets: t("Only the first sheet with a header row was read; left out:"),
    rule_dropped: t("A rule was left out, because the new file has no item of its category:"),
    unknown_category: t("The list has no item of this category."),
    not_a_number: t("The quantity or the discount is not a number."),
    quantity_not_positive: t("The quantity must be more than zero."),
    percent_out_of_range: t("The discount must be more than 0 and less than 100 percent."),
    duplicate_rule: t("The same category and quantity stand in two rules."),
    too_many_rules: t("There are more rules than a price list may have."),
    currency: t("The currency is a three-letter code, such as HUF."),
    vat_percent: t("The VAT rate must be at least 0 and less than 100 percent."),
  };
  return text[code] ?? code;
}

/** The place of a problem in words: a row of a sheet, or a rule. */
const whereText = (where: string) => {
  const rule = where.match(/^rule (\d+)$/);
  if (rule) return t("rule {{n}}", { n: rule[1] });
  const row = where.match(/^(.*)!(\d+)$/);
  return row ? t("{{sheet}}, row {{n}}", { sheet: row[1], n: row[2] }) : where;
};

function Issues({ items, warning }: { items: OutputTemplateIssue[]; warning?: boolean }) {
  useLocale();
  return (
    <BlockerList parts items={items.map((p, i) => ({ key: `${p.code}:${p.where}:${i}`, warning, content: <>
        {p.where ? <span className="tnum">{whereText(p.where)}</span> : null}
        <span>{priceIssueText(p.code)}</span>
        {/* a missing column by its name; a code from the file (an item code, a sheet) in the code face */}
        {p.code === "missing_column" ? <strong>{columnName(p.detail as PriceListColumn)}</strong>
          : p.detail && p.code !== "unreadable" ? <span className="mono muted">{p.detail}</span> : null}
      </> }))} />
  );
}

/** A rate or a quantity as the person reads it ("27 %", "2,5 %"). */
const percentText = (v: string) => `${numText(v, 4)} %`;

export function PriceListsPanel() {
  useLocale();
  const data = useLoad("price-lists", api.priceLists);
  const [again, setAgain] = useState<PriceList | null>(null);
  const [open, setOpen] = useState<{ priceList: string; version: number } | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const lists = data.data?.price_lists ?? [];
  return (
    <section className="stage-stack" aria-label={t("Price lists")}>
      <p className="muted small">
        {t("A price list is an Excel or CSV file with one row per item: its code, name, unit and net unit price, and its category if it has one. The rules that lower a price, the currency and the VAT rate are set here, not in the file. A quote is priced from a list's active version and records which version it was.")}
      </p>
      {data.data ? <ColumnsHelp columns={data.data.columns} /> : null}
      {/* the form starts from the listing's defaults (currency, VAT rate); a new version starts it afresh (its key) */}
      {data.data ? (
        <UploadCard key={again?.price_list ?? "new"} again={again} listing={data.data}
          onCancel={() => setAgain(null)} onStart={() => setDone(null)}
          onDone={(v, text) => { setDone(text); setAgain(null); setOpen({ priceList: v.price_list, version: v.version }); data.reload(); }} />
      ) : null}
      {done ? <p role="status" className="small ok">{done}</p> : null}
      {data.error ? <p className="notice error" role="alert">{data.error.message}</p> : null}
      {!data.data && !data.error ? <p className="muted">{t("Loading…")}</p> : null}
      {data.data ? (
        <section className="card wide" aria-label={t("The price lists")}>
          <h3>{t("The price lists")}</h3>
          {lists.length === 0 ? <p className="muted small">{t("No price list yet. A quote needs an active one.")}</p> : null}
          {lists.map((pl) => (
            <PriceListVersions key={pl.price_list} list={pl} open={open} onOpen={setOpen} onNewVersion={setAgain}
              onChanged={data.reload} />
          ))}
        </section>
      ) : null}
      {open && data.data ? (
        <VersionCard key={`${open.priceList}:${open.version}`} priceList={open.priceList} version={open.version}
          currencies={data.data.currencies} onClose={() => setOpen(null)}
          onSaved={(v) => { setDone(t("Saved as version {{n}}, a draft. Make it active to price quotes from it.", { n: v.version })); setOpen({ priceList: v.price_list, version: v.version }); data.reload(); }} />
      ) : null}
    </section>
  );
}

/** The columns a file needs and the headers each is known by (`configs/price_lists.json`). */
function ColumnsHelp({ columns }: { columns: PriceListsListing["columns"] }) {
  useLocale();
  return (
    <details className="marker-help">
      <summary>{t("Which columns the file needs")}</summary>
      <ul className="plain small">
        {COLUMNS.map((c) => (
          <li key={c}>
            <strong>{columnName(c)}</strong>{" "}
            <span className="muted">{columns[c]?.required ? t("needed") : t("optional")}</span>{" · "}
            {t("headers it is known by:")} <span className="mono">{(columns[c]?.headers ?? []).slice(0, 4).join(", ")}</span>
          </li>
        ))}
      </ul>
      <p className="muted small">{t("The header row may stand below a title; letter case, a trailing colon and a note in brackets, such as the currency, do not matter.")}</p>
    </details>
  );
}

/** Uploading a price list, or (`again`) a new version of one: a name, the currency and VAT rate of a new list, the path. */
function UploadCard({ again, listing, onDone, onCancel, onStart }: {
  again: PriceList | null; listing: PriceListsListing; onDone: (v: PriceListVersion, text: string) => void;
  onCancel: () => void; onStart: () => void;
}) {
  useLocale();
  const [name, setName] = useState(again?.name ?? "");
  const [currency, setCurrency] = useState(listing.currency);
  const [vat, setVat] = useState(editNumber(listing.vat_percent));
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<PriceListCheck | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const ready = !!name.trim() && !!path.trim() && (!!again || !!vat.trim()) && !busy;

  async function upload() {
    setBusy(true);
    setRefused(null);
    setMsg(null);
    onStart();
    try {
      const v = await api.uploadPriceList({
        name: name.trim(), path: path.trim(),
        ...(again ? { price_list: again.price_list } : { currency, vat_percent: vat.trim() }),
      });
      setName("");
      setPath("");
      onDone(v, t("Uploaded: {{name}}, version {{n}}, {{items}} items, as a draft. Check its items and rules below, then make it active.",
        { name: v.name, n: v.version, items: v.items }));
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "price_list_refused" && err.check && !("output" in err.check)) setRefused(err.check);
      else setMsg(err.code === "forbidden_path" ? t("The chosen place is not among the allowed places.") : err.message);
    } finally {
      setBusy(false);
    }
  }

  const title = again ? t("New version of {{name}}", { name: again.name }) : t("Upload a price list");
  return (
    <section className="card wide template-upload" aria-label={title}>
      <div className="card-head">
        <h3>{title}</h3>
        {again ? <button type="button" className="quiet small-btn" onClick={onCancel}>{t("Cancel")}</button> : null}
      </div>
      <div className="form-row">
        <label className="block grow">{t("Name")}
          <input value={name} maxLength={120} autoComplete="off" placeholder={t("for example: Price list 2026")} onChange={(e) => setName(e.target.value)} />
        </label>
        {again ? null : (
          <>
            <Picker label={t("Currency")} value={currency} className="price-currency"
              options={listing.currencies.map((c) => ({ value: c, label: c }))} onChange={setCurrency} />
            <label className="block price-vat">{t("VAT rate (%)")}
              <input value={vat} maxLength={6} inputMode="decimal" autoComplete="off" className="tnum" onChange={(e) => setVat(e.target.value)} />
            </label>
          </>
        )}
      </div>
      <div className="form-row">
        <label className="block grow">{t("The price list's full path (.xlsx or .csv)")}
          <input value={path} maxLength={2000} spellCheck={false} autoComplete="off" onChange={(e) => setPath(e.target.value)} />
        </label>
        <BrowseButton kind="files" initial={path} onPick={([p]) => setPath(p)} />
      </div>
      <div className="button-row">
        <button type="button" className="primary" disabled={!ready} onClick={() => void upload()}>
          {busy ? t("Checking…") : t("Upload and check")}
        </button>
        <span className="muted small">
          {again ? t("A new version keeps the list's rules, currency and VAT rate; a stored version never changes.")
            : t("The file is checked before it is stored; a stored version never changes.")}
        </span>
      </div>
      {refused ? (
        <div role="alert" className="template-refused">
          <p className="error-text">{t("The price list was not stored: the check found {{n}} problem(s).", { n: refused.problems.length })}</p>
          <Issues items={refused.problems} />
          {refused.warnings.length ? <Issues items={refused.warnings} warning /> : null}
        </div>
      ) : null}
      {msg ? <p role="status" className="notice error">{msg}</p> : null}
    </section>
  );
}

/** What made a version: a file, or a change of the settings of an earlier one. */
const changeText = (v: PriceListVersion) =>
  v.change === "settings" ? t("settings, from version {{n}}", { n: v.based_on ?? "" }) : t("upload");

/** One price list: every version as a row, newest first, with its state, what made it, its items and rules. */
function PriceListVersions({ list, open, onOpen, onNewVersion, onChanged }: {
  list: PriceList; open: { priceList: string; version: number } | null;
  onOpen: (o: { priceList: string; version: number }) => void; onNewVersion: (pl: PriceList) => void; onChanged: () => void;
}) {
  useLocale();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);

  async function act(fn: () => Promise<PriceListVersion>, say: (v: PriceListVersion) => string) {
    setBusy(true);
    setMsg(null);
    try {
      const v = await fn();
      setMsg({ error: false, text: say(v) });
      onChanged();
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="template-output-block">
      <div className="template-output-head">
        <h3>{list.name}</h3>
        <span className="muted small">
          {list.active ? t("active: version {{n}}", { n: list.active }) : list.retired ? t("retired") : t("no active version")}
        </span>
        <button type="button" className="secondary small-btn" disabled={busy} onClick={() => onNewVersion(list)}>{t("New version")}</button>
      </div>
      <table className="table compact price-table">
        <colgroup>
          <col className="c-version" /><col className="c-state" /><col className="c-change" /><col className="c-count" />
          <col className="c-count" /><col className="c-uploaded" /><col className="c-actions" />
        </colgroup>
        <thead>
          <tr>
            <th className="num">{t("Version")}</th><th>{t("State")}</th><th>{t("Made from")}</th><th className="num">{t("Items")}</th>
            <th className="num">{t("Rules")}</th><th>{t("Saved")}</th><th><span className="sr-only">{t("Actions")}</span></th>
          </tr>
        </thead>
        <tbody>
          {list.versions.map((v) => {
            const isOpen = open?.priceList === v.price_list && open.version === v.version;
            return (
              <tr key={v.version} className={isOpen ? "row-selected" : ""}>
                <td className="num tnum">{t("version {{n}}", { n: v.version })}</td>
                <td><VersionState state={v.state} /></td>
                <td>{changeText(v)}{v.check.warnings.length ? <> <span className="status s-warn">{t("{{n}} warning(s)", { n: v.check.warnings.length })}</span></> : null}</td>
                <td className="num tnum">{v.items}</td>
                <td className="num tnum">{v.discounts.length}</td>
                <td className="template-uploaded"><span>{v.made_by}</span><span className="muted tnum">{when(v.made_at)}</span></td>
                <td className="template-actions">
                  <button type="button" className="quiet small-btn" aria-pressed={isOpen} aria-label={t("Open version {{n}}", { n: v.version })}
                    onClick={() => onOpen({ priceList: v.price_list, version: v.version })}>
                    {t("Open version")}
                  </button>
                  {v.state === "active" ? (
                    <ConfirmButton className="quiet small-btn" disabled={busy}
                      onConfirm={() => void act(() => api.retirePriceList(v.price_list),
                        () => t("Retired: {{name}}. No new quote is priced from it.", { name: list.name }))}>
                      {t("Retire")}
                    </ConfirmButton>
                  ) : (
                    <button type="button" className="secondary small-btn" disabled={busy}
                      onClick={() => void act(() => api.activatePriceList(v.price_list, v.version),
                        (r) => t("Active: {{name}}, version {{n}}. New quotes are priced from it.", { name: r.name, n: r.version }))}>
                      {t("Make active")}
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {msg ? <p role="status" className={msg.error ? "notice error" : "small ok"}>{msg.text}</p> : null}
    </div>
  );
}

interface RuleRow { key: number; category: string; min_quantity: string; percent: string }
const asRows = (rules: PriceRule[]): RuleRow[] =>
  rules.map((r, i) => ({ key: i, category: r.category, min_quantity: editNumber(r.min_quantity), percent: editNumber(r.percent) }));
const SHOWN = 300; // the items shown at once; the search narrows a long list

/** A version: its settings (the rules, the currency, the VAT rate) to change, and its items. */
function VersionCard({ priceList, version, currencies, onClose, onSaved }: {
  priceList: string; version: number; currencies: string[]; onClose: () => void; onSaved: (v: PriceListVersion) => void;
}) {
  useLocale();
  const load = useLoad(`price-list:${priceList}:${version}`, () => api.priceListVersion(priceList, version));
  const v = load.data;
  return (
    <section className="card wide price-version" aria-label={v ? t("{{name}}, version {{n}}", { name: v.name, n: v.version }) : t("Price list")}>
      <div className="card-head">
        <div className="price-version-title">
          <h3>{v ? t("{{name}}, version {{n}}", { name: v.name, n: v.version }) : t("Price list")}</h3>
          {v ? <VersionState state={v.state} /> : null}
          {v ? <a href={api.priceListFileUrl(v.price_list, v.version)} download title={v.file_name}>{t("The uploaded file")}</a> : null}
        </div>
        <button type="button" className="quiet small-btn" onClick={onClose}>{t("Close")}</button>
      </div>
      {load.error ? <p className="notice error" role="alert">{load.error.message}</p> : null}
      {!v && !load.error ? <p className="muted">{t("Loading…")}</p> : null}
      {v ? <RulesEditor detail={v} currencies={currencies} onSaved={onSaved} /> : null}
      {v ? <Items detail={v} /> : null}
    </section>
  );
}

/** The rules, the currency and the VAT rate; saving makes a new draft version with the same items. */
function RulesEditor({ detail, currencies, onSaved }: {
  detail: PriceListDetail; currencies: string[]; onSaved: (v: PriceListVersion) => void;
}) {
  useLocale();
  const [rules, setRules] = useState<RuleRow[]>(() => asRows(detail.discounts));
  const [currency, setCurrency] = useState(detail.currency);
  const [vat, setVat] = useState(editNumber(detail.vat_percent));
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<PriceListCheck | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const shape = (rs: RuleRow[]) => JSON.stringify(rs.map(({ category, min_quantity, percent }) => [category, min_quantity.trim(), percent.trim()]));
  const changed = shape(rules) !== shape(asRows(detail.discounts)) || currency !== detail.currency || vat.trim() !== editNumber(detail.vat_percent);
  const categories = detail.categories;
  const offered = currencies.includes(detail.currency) ? currencies : [detail.currency, ...currencies];

  const edit = (key: number, patch: Partial<RuleRow>) => setRules((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const add = () => setRules((rs) => [...rs, { key: Math.max(-1, ...rs.map((r) => r.key)) + 1, category: categories[0] ?? "", min_quantity: "", percent: "" }]);

  async function save() {
    setBusy(true);
    setRefused(null);
    setMsg(null);
    try {
      const saved = await api.changePriceListSettings(detail.price_list, detail.version, {
        discounts: rules.map(({ category, min_quantity, percent }) => ({ category, min_quantity: min_quantity.trim(), percent: percent.trim() })),
        currency, vat_percent: vat.trim(),
      });
      onSaved(saved);
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "price_list_refused" && err.check && !("output" in err.check)) setRefused(err.check);
      else setMsg(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="price-settings">
      <div className="template-output-head">
        <h3>{t("Rules and rates")}</h3>
        <span className="muted small">{t("Saving makes a new draft version with the same items; this version stays as it is.")}</span>
      </div>
      <div className="form-row">
        <Picker label={t("Currency")} value={currency} className="price-currency"
          options={offered.map((c) => ({ value: c, label: c }))} onChange={setCurrency} />
        <label className="block price-vat">{t("VAT rate (%)")}
          <input value={vat} maxLength={6} inputMode="decimal" autoComplete="off" className="tnum" onChange={(e) => setVat(e.target.value)} />
        </label>
      </div>
      {categories.length === 0 ? (
        <p className="muted small">{t("The items have no category, so the list can have no volume discount.")}</p>
      ) : (
        <>
          <table className="table compact price-rules">
            <thead>
              <tr>
                <th>{t("Category")}</th><th className="num">{t("From quantity")}</th><th className="num">{t("Discount (%)")}</th>
                <th><span className="sr-only">{t("Actions")}</span></th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r, i) => (
                <tr key={r.key}>
                  <td>
                    <Picker label={t("Category of rule {{n}}", { n: i + 1 })} hideLabel compact value={r.category}
                      options={categories.map((c) => ({ value: c, label: c }))} onChange={(c) => edit(r.key, { category: c })} />
                  </td>
                  <td className="num">
                    <input aria-label={t("From quantity, rule {{n}}", { n: i + 1 })} value={r.min_quantity} maxLength={12} inputMode="decimal"
                      autoComplete="off" className="tnum num-input" onChange={(e) => edit(r.key, { min_quantity: e.target.value })} />
                  </td>
                  <td className="num">
                    <input aria-label={t("Discount, rule {{n}}", { n: i + 1 })} value={r.percent} maxLength={8} inputMode="decimal"
                      autoComplete="off" className="tnum num-input" onChange={(e) => edit(r.key, { percent: e.target.value })} />
                  </td>
                  <td>
                    <button type="button" className="quiet small-btn" aria-label={t("Remove rule {{n}}", { n: i + 1 })} title={t("Remove the rule")}
                      onClick={() => setRules((rs) => rs.filter((x) => x.key !== r.key))}>
                      <Icon name="trash" />
                    </button>
                  </td>
                </tr>
              ))}
              {rules.length === 0 ? (
                <tr><td colSpan={4} className="muted small">{t("No rule: every item costs its unit price, whatever the quantity.")}</td></tr>
              ) : null}
            </tbody>
          </table>
          <p className="muted small">{t("A line of the category from the quantity on costs the percent less; of the rules a line reaches, the largest discount counts.")}</p>
        </>
      )}
      <div className="button-row">
        {categories.length ? <button type="button" className="quiet small-btn" onClick={add}><Icon name="plus" />{t("Add a rule")}</button> : null}
        <button type="button" className={changed ? "primary" : "secondary"} disabled={!changed || busy} onClick={() => void save()}>
          {busy ? t("Saving…") : t("Save as a new version")}
        </button>
      </div>
      {refused ? (
        <div role="alert" className="template-refused">
          <p className="error-text">{t("Not saved: the check found {{n}} problem(s).", { n: refused.problems.length })}</p>
          <Issues items={refused.problems} />
        </div>
      ) : null}
      {msg ? <p role="status" className="notice error">{msg}</p> : null}
    </div>
  );
}

/** The version's items, searchable; at most `SHOWN` at once. */
function Items({ detail }: { detail: PriceListDetail }) {
  useLocale();
  const [q, setQ] = useState("");
  const needle = fold(q.trim());
  const found = useMemo(() => detail.item_rows.filter((i) => !needle || fold(`${i.sku} ${i.name} ${i.category ?? ""}`).includes(needle)),
    [detail.item_rows, needle]);
  return (
    <div className="price-items">
      <div className="template-output-head">
        <h3>{t("The items")}</h3>
        <span className="muted small tnum">
          {found.length > SHOWN ? t("{{shown}} of {{n}} shown; search to narrow", { shown: SHOWN, n: found.length })
            : t("{{n}} items · VAT {{vat}} · prices net, in {{currency}}", { n: found.length, vat: percentText(detail.vat_percent), currency: detail.currency })}
        </span>
      </div>
      <label className="block price-search">{t("Search")}
        <input type="search" value={q} spellCheck={false} autoComplete="off" placeholder={t("a code, a name or a category…")} onChange={(e) => setQ(e.target.value)} />
      </label>
      <div className="marker-scroll">
        <table className="table compact price-items-table">
          <thead>
            <tr>{COLUMNS.map((c) => <th key={c} className={c === "unit_price" ? "num" : ""}>{columnName(c)}</th>)}</tr>
          </thead>
          <tbody>
            {found.slice(0, SHOWN).map((i) => (
              <tr key={i.sku}>
                <td><code className="mono">{i.sku}</code></td>
                <td>{i.name}</td>
                <td>{i.unit}</td>
                <td className="num tnum">{moneyText(i.unit_price)}</td>
                <td className="muted">{i.category ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {found.length === 0 ? <p className="muted small">{t("No item matches.")}</p> : null}
      </div>
    </div>
  );
}
