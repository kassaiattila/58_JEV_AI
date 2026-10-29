// 261 (plan B, B1f; the owner's decision of 2026-10-29: the three shared elements now, each with a first user): the
// shared element `data_table`, a registered dataset the case gives the scope of, shown with the shared table's columns,
// filters, links and download (the service's; `jav/app/datasets.py`). A pack's element names the dataset; an element
// of its own may show its dataset the same way (its first user: the cases started from a case's emails).
import { DataTable } from "../components/DataTable";
import { t, useLocale } from "../i18n";
import type { ElementProps } from "./registry";

interface TableData { dataset?: string; scope?: Record<string, string> }

/** A dataset of the case as a card: its title, the shared table. */
export function DataTableCard({ p, dataset, label, emptyText }: { p: ElementProps; dataset?: string; label?: string; emptyText?: string }) {
  useLocale();
  const d = p.element.data as TableData | null;
  const name = dataset ?? (typeof p.element.dataset === "string" ? p.element.dataset : d?.dataset);
  if (!d || !name) return <p className="muted">{t("Loading…")}</p>;
  const title = label ?? (typeof p.element.label === "string" ? t(p.element.label) : t(name));
  return (
    <section className="card wide" aria-label={title}>
      <div className="card-head"><h2>{title}</h2></div>
      <DataTable dataset={name} scope={d.scope ?? { case_id: p.caseId }} label={title} storageId={`case:${name}`}
        emptyText={emptyText ?? t("Nothing to show yet.")} />
    </section>
  );
}

/** The element: the dataset its pack names. */
export function DataTableView(p: ElementProps) {
  return <DataTableCard p={p} />;
}
