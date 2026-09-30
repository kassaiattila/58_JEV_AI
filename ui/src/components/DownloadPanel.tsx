// Közös letöltés-panel (056 U1): minden táblázat és riport ugyanígy tölt le. Választható a formátum, a terjedelem
// (minden sor / a szűrt sorok / a kijelölt sorok) és az oszlopok; a sorok száma letöltés előtt látszik. A fájlt a
// szolgáltatás állítja elő (képlet-védelem, magyar CSV), a fájlnév egységes: adatkészlet, hatókör, terjedelem, időpont.
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
// a tipp olvasáskor fordít (a magyar szöveg a kulcs)
const FORMAT_HINT: Record<string, string> = tmap({
  xlsx: "egy munkalap, számok számként, szűrhető fejléc",
  csv: "pontosvesszővel tagolva, a magyar Excel oszlopokra bontja",
  json: "nyers értékek oszlopleírással, gépi feldolgozáshoz",
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

  // a legszűkebb értelmes terjedelem az alap: kijelölés > szűrés > minden
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
      setMsg({ error: false, text: t("Letöltve: {{file}} ({{rows}} sor).", { file: res.filename, rows: res.rows.toLocaleString(getLocale()) }) });
    } catch (e) {
      setMsg({ error: true, text: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button ref={anchor} type="button" className="secondary small-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name="download" />{t("Letöltés")}
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchor={anchor} label={t("Letöltés: {{label}}", { label: p.label })} className="download-pop" align="right">
        <h3>{t("Letöltés — {{label}}", { label: p.label })}</h3>
        <fieldset className="dl-group">
          <legend>{t("Formátum")}</legend>
          {FORMATS.map((f) => (
            <label key={f.value} className="check">
              <input type="radio" name="dl-format" checked={format === f.value} onChange={() => setFormat(f.value)} />
              <span><strong>{f.label}</strong> <span className="muted small">{FORMAT_HINT[f.value]}</span></span>
            </label>
          ))}
        </fieldset>
        <fieldset className="dl-group">
          <legend>{t("Sorok")}</legend>
          <label className="check"><input type="radio" name="dl-rows" checked={rows === "all"} onChange={() => setRows("all")} />
            {t("Minden sor ({{n}})", { n: p.total.toLocaleString(getLocale()) })}</label>
          <label className="check"><input type="radio" name="dl-rows" checked={rows === "filtered"} disabled={!p.filtered} onChange={() => setRows("filtered")} />
            {p.filtered ? t("A szűrt sorok ({{n}})", { n: p.matched.toLocaleString(getLocale()) }) : t("A szűrt sorok (nincs szűrés)")}</label>
          <label className="check"><input type="radio" name="dl-rows" checked={rows === "selected"} disabled={!p.selectedKeys.length} onChange={() => setRows("selected")} />
            {p.selectedKeys.length ? t("A kijelölt sorok ({{n}})", { n: p.selectedKeys.length }) : t("A kijelölt sorok (nincs kijelölés)")}</label>
        </fieldset>
        <fieldset className="dl-group">
          <legend>{t("Oszlopok")}</legend>
          <label className="check"><input type="radio" name="dl-cols" checked={cols === "visible"} onChange={() => setCols("visible")} />
            {t("A látható oszlopok ({{n}})", { n: p.visibleKeys.length })}</label>
          <label className="check"><input type="radio" name="dl-cols" checked={cols === "all"} onChange={() => setCols("all")} />
            {t("Minden oszlop, a rejtettek is ({{n}})", { n: p.columns.length })}</label>
        </fieldset>
        <p className="small muted">{t("A rendezés a táblázatéval azonos. {{rows}} sor × {{cols}} oszlop.", { rows: count.toLocaleString(getLocale()), cols: colCount })}</p>
        <div className="button-row">
          <button type="button" className="primary" disabled={busy || count === 0} onClick={() => void download()}>
            {busy ? t("Készül…") : t("Letöltés ({{n}} sor)", { n: count.toLocaleString(getLocale()) })}
          </button>
        </div>
        {msg ? <p role="status" className={msg.error ? "notice error" : "notice"}>{msg.text}</p> : null}
        {p.extras ? <div className="dl-extras">{p.extras}</div> : null}
      </Popover>
    </>
  );
}
