// Utility cost (054 K4, moved into the Result section in 057): a monthly grid of the run's utility invoices by
// consumption point and utility; the shared water summary is for information only. Every cell can be traced back to
// its source invoices (on click).
import { useState } from "react";
import { api, type UtilityCell, type UtilityReport } from "../api";
import { useLoad } from "../hooks";
import { getLocale, t, useLocale } from "../i18n";
import { tmap } from "../labels";

// a cell that is in order (ok) has no label
const STATUS: Record<string, string> = tmap({ missing: "hiányzik", overlap: "átfedés", partial: "részleges" });
const REASON: Record<string, string> = tmap({ no_period: "nincs számlázási időszak", no_amount: "nincs összeg" });
const statusText = (s: string) => STATUS[s] ?? "";

export const huf = (v: string | null | undefined) =>
  v === null || v === undefined ? "" : Number(v).toLocaleString(getLocale(), { maximumFractionDigits: 2 });

/** The monthly utility cost grid for one run, with the source invoices per cell (part of the Result section, 057). */
export function UtilityPanel({ runId, wpId }: { runId: string; wpId: string }) {
  useLocale();
  const rep = useLoad(`utility:${runId}`, () => api.utilityCost(runId));
  const [cell, setCell] = useState<{ key: string; month: string; data: UtilityCell } | null>(null);
  return (
    <section className="card wide" aria-label={t("Közmű-költség")}>
      <h2>{t("Közmű-költség havonta")}</h2>
      {rep.error ? <p className="notice error" role="alert">{rep.error.message}</p> : null}
      {!rep.data ? <p className="muted">{t("Betöltés…")}</p> : <UtilityTable rep={rep.data} onCell={(key, month, data) => setCell({ key, month, data })} />}
      {cell ? <CellSources cell={cell} wpId={wpId} onClose={() => setCell(null)} /> : null}
    </section>
  );
}

export function UtilityTable({ rep, onCell }: { rep: UtilityReport; onCell: (key: string, month: string, c: UtilityCell) => void }) {
  useLocale();
  if (rep.series.length === 0) {
    return <p className="muted">{t("Ebben a futásban nincs közmű-számla (vagy egyiknek sincs számlázási időszaka és összege).")}</p>;
  }
  return (
    <>
      <p className="small">{t("Összesen (bruttó, a tájékoztató sorok nélkül):")} <strong>{t("{{amount}} Ft", { amount: huf(rep.grand_total) })}</strong>.
        {" "}{t("A tétel a számlázási időszak napjai szerint oszlik a hónapokra; az elszámoló számla a záró hónapjába kerül.")}</p>
      <div className="list-scroll">
        <table className="table compact utility-table">
          <thead>
            <tr>
              <th>{t("Fogyasztási hely")}</th><th>{t("Közmű")}</th><th className="num">{t("Összesen")}</th>
              {rep.months.map((m) => <th key={m} className="num">{m}</th>)}
            </tr>
          </thead>
          <tbody>
            {rep.series.map((s) => {
              const key = `${s.address}|${s.utility}`;
              return (
                <tr key={key} className={s.summary_only ? "summary-row" : ""}>
                  <td>{s.address}</td>
                  <td>{s.utility}{s.summary_only ? <span className="muted small"> {t("(tájékoztató, nem számít bele)")}</span> : null}
                    {s.suppliers.length ? <div className="muted small">{s.suppliers.join(", ")}</div> : null}</td>
                  <td className="num">{huf(s.total)}</td>
                  {rep.months.map((m) => {
                    const c = s.cells[m];
                    if (!c) return <td key={m} />;
                    const label = `${s.utility}, ${m}: ${c.amount ? t("{{amount}} Ft", { amount: huf(c.amount) }) : statusText(c.status)}`;
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
        <span className="cell-missing">{STATUS.missing}</span> {t("egyik számla sem fedi a hónapot")} ·{" "}
        <span className="cell-partial">{STATUS.partial}</span> {t("a hónap egy része fedetlen")} ·{" "}
        <span className="cell-overlap">{STATUS.overlap}</span> {t("két számla is fedi")} · * {t("elszámoló számla")}
      </p>
      {rep.duplicates.length ? (
        <p className="small">{t("Ismétlődő számla (azonos típus és számlaszám, egyszer számolva):")}{" "}
          {rep.duplicates.map((d) => `${d.file} = ${d.same_as_file}`).join("; ")}</p>
      ) : null}
      {rep.unplaced.length ? (
        <p className="small warn-text">{t("Nem vetíthető közmű-számla:")} {rep.unplaced.map((u) => `${u.file} (${REASON[u.reason] ?? u.reason})`).join("; ")}</p>
      ) : null}
    </>
  );
}

export function CellSources({ cell, wpId, onClose }: { cell: { key: string; month: string; data: UtilityCell }; wpId?: string; onClose: () => void }) {
  useLocale();
  const [address, utility] = cell.key.split("|");
  return (
    <div className="cell-sources" role="region" aria-label={t("A cella forrásai")}>
      <div className="list-head">
        <strong>{utility}, {cell.month}</strong><span className="muted small">{address}</span>
        <span className="spacer" />
        <button type="button" className="quiet small-btn" onClick={onClose}>{t("Bezárás")}</button>
      </div>
      {cell.data.sources.length === 0 ? <p className="muted small">{statusText(cell.data.status) || t("Nincs forrásszámla.")}</p> : (
        <ul className="plain">
          {cell.data.sources.map((s) => (
            <li key={s.item_id + s.amount}>
              {t("{{amount}} Ft", { amount: huf(s.amount) })} — {s.file}{s.page ? `, ${t("{{page}}. oldal", { page: s.page })}` : ""}{s.settlement ? ` ${t("(elszámolás)")}` : ""}
              {s.corrected ? ` · ${t("javítva")}` : ""}{s.open_reasons ? ` · ${t("{{n}} nyitott teendő", { n: s.open_reasons })}` : ""}
              {wpId ? <> · <a href={`#/workpackages/${encodeURIComponent(wpId)}/review/${encodeURIComponent(s.item_id)}`}>{t("megnyitás")}</a></> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
