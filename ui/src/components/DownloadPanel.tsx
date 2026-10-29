// Shared download panel (056 U1): every table and report downloads the same way. The format, the row scope (all
// rows / the filtered rows / the selected rows) and the columns can be chosen; the number of rows is shown before
// downloading. The local service produces the file (formula protection, Hungarian CSV); the file name is uniform:
// dataset, scope, row scope, timestamp.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { getLocale, t, useLocale } from "../i18n";
import { api, ApiError, type DsColumn, type DsQuery, type DsScope, type ExportFormat, type ExportRows } from "../api";
import { tmap } from "../labels";
import { Popover } from "./Popover";
import { Icon } from "./Icon";

const FORMATS: { value: ExportFormat; label: string }[] = [
  { value: "xlsx", label: "Excel" },
  { value: "csv", label: "CSV" },
  { value: "json", label: "JSON" },
];
// the hint is translated when read (the Hungarian text is the key)
const FORMAT_HINT: Record<string, string> = tmap({
  xlsx: "one worksheet, numbers as numbers, filterable header",
  csv: "semicolon-separated; Hungarian Excel splits it into columns",
  json: "raw values with column descriptions, for machine processing",
});

interface Props {
  dataset: string;
  scope: DsScope;
  label: string;
  query: DsQuery;
  total: number;
  matched: number;
  filtered: boolean;
  selectedKeys: string[];
  columns: DsColumn[];
  visibleKeys: string[];
  extras?: ReactNode;
}

export function DownloadPanel(p: Props) {
  useLocale();
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<ExportFormat>("xlsx");
  const [rows, setRows] = useState<ExportRows>("all");
  const [cols, setCols] = useState<"visible" | "all">("visible");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);

  // the narrowest sensible scope is the default: selection > filter > all
  useEffect(() => {
    if (!open) return;
    setRows(p.selectedKeys.length ? "selected" : p.filtered ? "filtered" : "all");
    setMsg(null);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const count = rows === "selected" ? p.selectedKeys.length : rows === "filtered" ? p.matched : p.total;
  const colCount = cols === "all" ? p.columns.length : p.visibleKeys.length;

  const download = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const query: DsQuery = { q: p.query.q, filters: p.query.filters, sort: p.query.sort, ...(rows === "selected" ? { keys: p.selectedKeys } : {}) };
      const res = await api.datasetExport(p.dataset, p.scope, {
        format, rows, query, columns: cols === "all" ? p.columns.map((c) => c.key) : p.visibleKeys,
      });
      setMsg({ error: false, text: t("Downloaded: {{file}} ({{rows}} rows).", { file: res.filename, rows: res.rows.toLocaleString(getLocale()) }) });
    } catch (e) {
      setMsg({ error: true, text: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button ref={anchor} type="button" className="secondary small-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name="download" />{t("Download")}
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label={t("Download: {{label}}", { label: p.label })} className="download-pop" align="right">
        <h3>{t("Download — {{label}}", { label: p.label })}</h3>
        <fieldset className="dl-group">
          <legend>{t("Format")}</legend>
          {FORMATS.map((f) => (
            <label key={f.value} className="check">
              <input type="radio" name="dl-format" checked={format === f.value} onChange={() => setFormat(f.value)} />
              <span><strong>{f.label}</strong> <span className="muted small">{FORMAT_HINT[f.value]}</span></span>
            </label>
          ))}
        </fieldset>
        <fieldset className="dl-group">
          <legend>{t("Rows")}</legend>
          <label className="check"><input type="radio" name="dl-rows" checked={rows === "all"} onChange={() => setRows("all")} />
            {t("All rows ({{n}})", { n: p.total.toLocaleString(getLocale()) })}</label>
          <label className="check"><input type="radio" name="dl-rows" checked={rows === "filtered"} disabled={!p.filtered} onChange={() => setRows("filtered")} />
            {p.filtered ? t("Filtered rows ({{n}})", { n: p.matched.toLocaleString(getLocale()) }) : t("Filtered rows (no filter)")}</label>
          <label className="check"><input type="radio" name="dl-rows" checked={rows === "selected"} disabled={!p.selectedKeys.length} onChange={() => setRows("selected")} />
            {p.selectedKeys.length ? t("Selected rows ({{n}})", { n: p.selectedKeys.length }) : t("Selected rows (no selection)")}</label>
        </fieldset>
        <fieldset className="dl-group">
          <legend>{t("Columns")}</legend>
          <label className="check"><input type="radio" name="dl-cols" checked={cols === "visible"} onChange={() => setCols("visible")} />
            {t("Visible columns ({{n}})", { n: p.visibleKeys.length })}</label>
          <label className="check"><input type="radio" name="dl-cols" checked={cols === "all"} onChange={() => setCols("all")} />
            {t("All columns, including hidden ones ({{n}})", { n: p.columns.length })}</label>
        </fieldset>
        <p className="small muted">{t("Sorted as in the table. {{rows}} rows × {{cols}} columns.", { rows: count.toLocaleString(getLocale()), cols: colCount })}</p>
        <div className="button-row">
          <button type="button" className="primary" disabled={busy || count === 0} onClick={() => void download()}>
            {busy ? t("Preparing…") : t("Download ({{n}} rows)", { n: count.toLocaleString(getLocale()) })}
          </button>
        </div>
        {msg ? <p role="status" className={msg.error ? "notice error" : "notice"}>{msg.text}</p> : null}
        {p.extras ? <div className="dl-extras">{p.extras}</div> : null}
      </Popover>
    </>
  );
}
