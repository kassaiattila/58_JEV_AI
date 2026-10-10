// 135 (plan 134 P2): the filter rows under the heads of the pairing page's two lists (filters.ts). Every drop-down is
// the searchable picker (U1); the amounts are typed in the chosen language's notation.
import type { ReconcileInvoice, ReconcileLine } from "../../api";
import { Picker, type PickerOption } from "../../components/Picker";
import { t, useLocale } from "../../i18n";
import {
  activeCount, NO_INVOICE_FILTERS, NO_LINE_FILTERS, NO_PARTY, supplierKey, type InvoiceFilters, type LineFilters,
} from "./filters";
import { INVOICE_STATE, KIND } from "./labels";
import { groupByPartner, kinds } from "./partners";

function counted<T>(items: T[], key: (x: T) => string | null | undefined, label: (k: string, x: T) => string): PickerOption[] {
  const seen = new Map<string, { label: string; n: number }>();
  for (const x of items) {
    const k = key(x);
    if (!k) continue;
    const s = seen.get(k) ?? { label: label(k, x), n: 0 };
    s.n += 1;
    seen.set(k, s);
  }
  return [...seen].sort((a, b) => b[1].n - a[1].n || a[1].label.localeCompare(b[1].label))
    .map(([value, s]) => ({ value, label: s.label, detail: String(s.n) }));
}

function AmountRange({ min, max, onChange }: { min: string; max: string; onChange: (min: string, max: string) => void }) {
  return (
    <span className="rc-range">
      <input type="text" inputMode="decimal" className="amount" placeholder={t("Amount from")} aria-label={t("Amount from")} value={min}
        onChange={(e) => onChange(e.target.value, max)} />
      <span aria-hidden="true">–</span>
      <input type="text" inputMode="decimal" className="amount" placeholder={t("Amount to")} aria-label={t("Amount to")} value={max}
        onChange={(e) => onChange(min, e.target.value)} />
    </span>
  );
}

export function LineFilterRow({ lines, value, onChange }: { lines: ReconcileLine[]; value: LineFilters; onChange: (f: LineFilters) => void }) {
  useLocale();
  const set = (patch: Partial<LineFilters>) => onChange({ ...value, ...patch });
  const partners: PickerOption[] = groupByPartner(lines).filter((g) => !g.key.startsWith("line:"))
    .map((g) => ({ value: g.key, label: g.name, detail: String(g.lines.length) }));
  const kindOptions = counted(lines.flatMap((l) => [...new Set(kinds(l).map((k) => k.kind))]), (k) => k, (k) => KIND[k] ?? k);
  return (
    <div className="rc-filters" role="group" aria-label={t("Filters of the lines")}>
      <Picker compact hideLabel label={t("Partner of the line")} value={value.partner} onChange={(v) => set({ partner: v })}
        options={[{ value: "", label: t("Every partner") }, ...partners]} />
      {kindOptions.length ? (
        <Picker compact hideLabel label={t("Kind (AI)")} value={value.kind} onChange={(v) => set({ kind: v })}
          options={[{ value: "", label: t("Every kind") }, ...kindOptions]} />
      ) : null}
      <Picker compact hideLabel label={t("Direction")} value={value.direction} onChange={(v) => set({ direction: v as LineFilters["direction"] })}
        options={[{ value: "", label: t("Both directions") }, { value: "debit", label: t("Outgoing") }, { value: "credit", label: t("Incoming") }]} />
      <AmountRange min={value.min} max={value.max} onChange={(min, max) => set({ min, max })} />
      {activeCount(value) ? <button type="button" className="quiet small-btn" onClick={() => onChange(NO_LINE_FILTERS)}>{t("Clear the filters")}</button> : null}
    </div>
  );
}

export function InvoiceFilterRow({ invoices, target, value, onChange }: {
  invoices: ReconcileInvoice[]; target: ReconcileLine | null; value: InvoiceFilters; onChange: (f: InvoiceFilters) => void;
}) {
  useLocale();
  const set = (patch: Partial<InvoiceFilters>) => onChange({ ...value, ...patch });
  const suppliers = counted(invoices, (i) => supplierKey(i), (_k, i) => (i.supplier_name ?? "").trim());
  const parties = counted(invoices, (i) => i.party?.id, (_k, i) => i.party?.name ?? "");
  const currencies = counted(invoices, (i) => i.currency, (k) => k);
  const states = counted(invoices, (i) => i.state, (k) => INVOICE_STATE[k] ?? k);
  return (
    <div className="rc-filters" role="group" aria-label={t("Filters of the invoices")}>
      <Picker compact hideLabel label={t("Supplier")} value={value.supplier} onChange={(v) => set({ supplier: v })}
        options={[{ value: "", label: t("Every supplier") }, ...suppliers]} />
      {parties.length ? (
        <Picker compact hideLabel label={t("Own party")} value={value.party} onChange={(v) => set({ party: v })}
          options={[{ value: "", label: t("Every party") }, ...parties, { value: NO_PARTY, label: t("No own party") }]} />
      ) : null}
      {currencies.length > 1 ? (
        <Picker compact hideLabel label={t("Currency")} value={value.currency} onChange={(v) => set({ currency: v })}
          options={[{ value: "", label: t("Every currency") }, ...currencies]} />
      ) : null}
      <Picker compact hideLabel label={t("State")} value={value.state} onChange={(v) => set({ state: v })}
        options={[{ value: "", label: t("Every state") }, ...states]} />
      <span className="rc-range">
        <input type="date" aria-label={t("Issued from")} title={t("Issued from")} value={value.from} onChange={(e) => set({ from: e.target.value })} />
        <span aria-hidden="true">–</span>
        <input type="date" aria-label={t("Issued until")} title={t("Issued until")} value={value.to} onChange={(e) => set({ to: e.target.value })} />
      </span>
      <AmountRange min={value.min} max={value.max} onChange={(min, max) => set({ min, max })} />
      <span className="rc-range">
        <label className="check small">
          <input type="checkbox" checked={value.near} disabled={!target} onChange={(e) => set({ near: e.target.checked })} />
          {t("Near the selected line's amount")}
        </label>
        <input type="text" inputMode="decimal" className="pct" aria-label={t("Allowed difference in percent")} value={value.nearPct}
          disabled={!value.near} onChange={(e) => set({ nearPct: e.target.value })} />
        <span className="small muted">%</span>
      </span>
      <label className="check small">
        <input type="checkbox" checked={value.withCandidates} onChange={(e) => set({ withCandidates: e.target.checked })} /> {t("Has a candidate")}
      </label>
      {activeCount(value) ? <button type="button" className="quiet small-btn" onClick={() => onChange(NO_INVOICE_FILTERS)}>{t("Clear the filters")}</button> : null}
    </div>
  );
}
