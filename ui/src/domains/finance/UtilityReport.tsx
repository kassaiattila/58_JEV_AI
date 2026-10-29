// Utility cost (054 K4, moved into the Result section in 057): a monthly grid of the run's utility invoices by
// consumption point and utility; the shared water summary is for information only. Every cell can be traced back to
// its source invoices (on click).
import { useState } from "react";
import { api } from "../../api";
import type { UtilityCell, UtilityReport } from "./api";
import { Icon } from "../../components/Icon";
import { TemplateChoice } from "../../components/TemplateChoice";
import { useLoad } from "../../hooks";
import { getLocale, t, useLocale } from "../../i18n";
import { tmap } from "../../labels";

// a cell that is in order (ok) has no label
const STATUS: Record<string, string> = tmap({ missing: "missing", overlap: "overlap", partial: "partial" });
const REASON: Record<string, string> = tmap({ no_period: "no billing period", no_amount: "no amount" });
const statusText = (s: string) => STATUS[s] ?? "";

export const huf = (v: string | null | undefined) =>
  v === null || v === undefined ? "" : Number(v).toLocaleString(getLocale(), { maximumFractionDigits: 2 });

/** The monthly utility cost grid for one run, with the source invoices per cell (part of the Result section, 057).
 *  172: without a run, of the package's current result (each item from its counted run). */
export function UtilityPanel({ runId, wpId }: { runId?: string; wpId: string }) {
  useLocale();
  const rep = useLoad(runId ? `utility:${runId}` : `utility:package:${wpId}`,
    () => (runId ? api.utilityCost(runId) : api.packageUtilityCost(wpId)));
  const [cell, setCell] = useState<{ key: string; month: string; data: UtilityCell } | null>(null);
  return (
    <section className="card wide" aria-label={t("Utility costs")}>
      <div className="card-head">
        <h2>{t("Utility cost by month")}</h2>
        {/* 179 (DECISIONS 178): the package's utility cost as a workbook of its own, with the package's template */}
        {runId ? null : (
          <span className="button-row">
            <TemplateChoice wpId={wpId} output="utility_cost" />
            <a className="secondary dl-btn small-btn" href={api.packageUtilityCostXlsxUrl(wpId)} download><Icon name="download" />{t("Utility cost (Excel)")}</a>
          </span>
        )}
      </div>
      {rep.error ? <p className="notice error" role="alert">{rep.error.message}</p> : null}
      {!rep.data ? <p className="muted">{t("Loading…")}</p> : <UtilityTable rep={rep.data} onCell={(key, month, data) => setCell({ key, month, data })} />}
      {cell ? <CellSources cell={cell} wpId={wpId} onClose={() => setCell(null)} /> : null}
    </section>
  );
}

export function UtilityTable({ rep, onCell }: { rep: UtilityReport; onCell: (key: string, month: string, c: UtilityCell) => void }) {
  useLocale();
  if (rep.series.length === 0) {
    return <p className="muted">{t("This run has no utility invoices (or none has both a billing period and an amount).")}</p>;
  }
  return (
    <>
      <p className="small">{t("Total (gross, excluding informational rows):")} <strong>{t("HUF {{amount}}", { amount: huf(rep.grand_total) })}</strong>.
        {" "}{t("Each amount is split across months by the days of the billing period; a settlement invoice goes to its closing month.")}</p>
      <div className="list-scroll">
        <table className="table compact utility-table">
          <thead>
            <tr>
              <th>{t("Point of consumption")}</th><th>{t("Utility")}</th><th className="num">{t("Total")}</th>
              {rep.months.map((m) => <th key={m} className="num">{m}</th>)}
            </tr>
          </thead>
          <tbody>
            {rep.series.map((s) => {
              const key = `${s.address}|${s.utility}`;
              return (
                <tr key={key} className={s.summary_only ? "summary-row" : ""}>
                  <td>{s.address}</td>
                  <td>{s.utility}{s.summary_only ? <span className="muted small"> {t("(for information, not included)")}</span> : null}
                    {s.suppliers.length ? <div className="muted small">{s.suppliers.join(", ")}</div> : null}</td>
                  <td className="num">{huf(s.total)}</td>
                  {rep.months.map((m) => {
                    const c = s.cells[m];
                    if (!c) return <td key={m} />;
                    const label = `${s.utility}, ${m}: ${c.amount ? t("HUF {{amount}}", { amount: huf(c.amount) }) : statusText(c.status)}`;
                    return (
                      <td key={m} className={`num cell-${c.status}`}>
                        <button type="button" className="cell-btn" aria-label={label} title={label} onClick={() => onCell(key, m, c)}>
                          {c.amount ? huf(c.amount) : statusText(c.status)}{c.settlement ? " *" : ""}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small legend">
        <span className="cell-missing">{STATUS.missing}</span> {t("no invoice covers the month")} ·{" "}
        <span className="cell-partial">{STATUS.partial}</span> {t("part of the month is not covered")} ·{" "}
        <span className="cell-overlap">{STATUS.overlap}</span> {t("covered by two invoices")} · * {t("settlement invoice")}
      </p>
      {rep.duplicates.length ? (
        <p className="small">{t("Duplicate invoice (same invoice number and supplier, counted once):")}{" "}
          {rep.duplicates.map((d) => `${d.file} = ${d.same_as_file}${d.status === "suspected" ? ` (${t("not yet confirmed")})` : ""}`).join("; ")}</p>
      ) : null}
      {rep.unplaced.length ? (
        <p className="small warn-text">{t("Utility invoice that cannot be allocated:")} {rep.unplaced.map((u) => `${u.file} (${REASON[u.reason] ?? u.reason})`).join("; ")}</p>
      ) : null}
    </>
  );
}

export function CellSources({ cell, wpId, onClose }: { cell: { key: string; month: string; data: UtilityCell }; wpId?: string; onClose: () => void }) {
  useLocale();
  const [address, utility] = cell.key.split("|");
  return (
    <div className="cell-sources" role="region" aria-label={t("Sources of the cell")}>
      <div className="list-head">
        <strong>{utility}, {cell.month}</strong><span className="muted small">{address}</span>
        <span className="spacer" />
        <button type="button" className="quiet small-btn" onClick={onClose}>{t("Close")}</button>
      </div>
      {cell.data.sources.length === 0 ? <p className="muted small">{statusText(cell.data.status) || t("No source invoice.")}</p> : (
        <ul className="plain">
          {cell.data.sources.map((s) => (
            <li key={s.item_id + s.amount}>
              {t("HUF {{amount}}", { amount: huf(s.amount) })} — {s.file}{s.page ? `, ${t("page {{page}}", { page: s.page })}` : ""}{s.settlement ? ` ${t("(settlement)")}` : ""}
              {s.corrected ? ` · ${t("corrected")}` : ""}{s.open_reasons ? ` · ${t("{{n}} open to-dos", { n: s.open_reasons })}` : ""}
              {wpId ? <> · <a href={`#/workpackages/${encodeURIComponent(wpId)}/review/${encodeURIComponent(s.item_id)}`}>{t("open")}</a></> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
