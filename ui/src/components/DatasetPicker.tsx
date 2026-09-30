// Picker backed by a dataset (056 U1): the list comes from the local service, which also does the search (decision of
// 2026-09-28), so even among hundreds of runs you can choose by typing. The label of the selected item is shown even
// when it is not among the matches at the moment (we fetch it filtered on the `valueCol` column).
import { useEffect, useState } from "react";
import { api, type DsRow, type DsScope, type DsSort } from "../api";
import { useDebounced } from "../hooks";
import { getLocale, t, useLocale } from "../i18n";
import { MODE, RUN_STATUS } from "../labels";
import { Picker, type PickerOption } from "./Picker";

interface Props {
  dataset: string;
  scope?: DsScope;
  label: string;
  value: string | null;
  valueCol: string;
  toOption: (row: DsRow) => PickerOption;
  onChange: (value: string) => void;
  sort?: DsSort[];
  placeholder?: string;
  hideLabel?: boolean;
  limit?: number;
}

export function DatasetPicker(p: Props) {
  const [q, setQ] = useState("");
  const debounced = useDebounced(q, 200);
  useLocale(); // the picker's options are built at render time, so they refresh on a language change
  const [rows, setRows] = useState<DsRow[]>([]);
  const [more, setMore] = useState(0);
  const [loading, setLoading] = useState(false);
  // the selected item's row (or only its value, if it cannot be found)
  const [selected, setSelected] = useState<{ value: string; row: DsRow | null } | null>(null);
  const scopeKey = JSON.stringify(p.scope ?? {});

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.datasetQuery(p.dataset, p.scope ?? {}, { q: debounced || undefined, sort: p.sort, limit: p.limit ?? 50 })
      .then((page) => {
        if (!alive) return;
        setRows(page.rows);
        setMore(Math.max(0, page.matched - page.rows.length));
      })
      .catch(() => alive && setRows([]))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [p.dataset, scopeKey, debounced]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!p.value) { setSelected(null); return; }
    const hit = rows.find((r) => p.toOption(r).value === p.value);
    if (hit) { setSelected({ value: p.value, row: hit }); return; }
    if (selected?.value === p.value) return;
    let alive = true;
    api.datasetQuery(p.dataset, p.scope ?? {}, { filters: [{ col: p.valueCol, op: "eq", value: p.value }], limit: 1 })
      .then((page) => alive && setSelected({ value: p.value!, row: page.rows[0] ?? null }))
      .catch(() => alive && setSelected({ value: p.value!, row: null }));
    return () => { alive = false; };
  }, [p.value, rows]); // eslint-disable-line react-hooks/exhaustive-deps

  const options = rows.map(p.toOption);
  const selectedLabel = selected ? (selected.row ? p.toOption(selected.row).label : selected.value) : undefined;
  return (
    <Picker label={p.label} value={p.value} options={options} onChange={p.onChange} onSearch={setQ} loading={loading}
      selectedLabel={selectedLabel} placeholder={p.placeholder} hideLabel={p.hideLabel} more={more} />
  );
}

/** A run's picker option: start time, work package, mode — the recipe and status go in the details. */
export function runOption(r: DsRow): PickerOption {
  const d = new Date(String(r.created_at));
  const at = Number.isNaN(d.getTime()) ? String(r.created_at) : d.toLocaleString(getLocale(), { dateStyle: "short", timeStyle: "short" });
  const mode = MODE[String(r.mode)] ?? String(r.mode);
  const status = RUN_STATUS[String(r.status)] ?? String(r.status);
  return {
    value: String(r.run_id), label: `${at} · ${String(r.workpackage_name ?? "")} · ${mode}`,
    detail: t("{{recipe}} · {{status}} · {{items}} tétel", { recipe: t(String(r.recipe ?? "")), status, items: String(r.items ?? "") }),
    group: Number.isNaN(d.getTime()) ? undefined : d.toLocaleDateString(getLocale(), { year: "numeric", month: "long" }),
  };
}
