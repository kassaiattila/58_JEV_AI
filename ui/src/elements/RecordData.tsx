// 231 (plan stage C, C1a; until then the quote's own `RequestData`): a record put together from an email or a document
// (its text, its table attachments, its attachments), shown the same way for every process: each field with the part
// it came from, its list with the columns its rows have, and the parts it was read from.
import type { RecordPart, RecordPreview } from "../api";
import { t, useLocale } from "../i18n";
import { fieldLabel, numText } from "../labels";

const valueText = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));
export const partKind = (p: RecordPart) =>
  ({ email_text: t("the email's text"), attachment: t("attachment"), document: t("document") })[p.kind] ?? p.kind;
// the list's own columns are named as the record's list rows name them; a few have a plain name of their own
const COLUMN: Record<string, string> = { description: "Description", quantity: "Quantity", unit: "Unit" };

export function RecordData({ record: r, listField, docType, compact = false }: {
  record: RecordPreview; listField: string; docType?: string | null; compact?: boolean;
}) {
  useLocale();
  const label = (f: string) => fieldLabel(f, docType ?? undefined);
  const from = (n: number | undefined | null) => {
    if (n === undefined || n === null) return "";
    const p = r.parts[n];
    if (!p) return "";
    if (compact) return p.kind === "email_text" ? partKind(p) : p.name || partKind(p);
    return `${partKind(p)}: ${p.name}`;
  };
  const rows = r.items as Record<string, unknown>[];
  const columns = [...new Set(rows.flatMap((i) => Object.keys(i)))];
  return (
    <>
      <table className="table compact quote-fields" aria-label={t("The request's data")}>
        <thead><tr><th>{t("Field")}</th><th>{t("Value")}</th><th>{t("Read from")}</th></tr></thead>
        <tbody>
          {Object.keys(r.fields).map((f) => (
            <tr key={f}>
              <td>{label(f)}</td>
              <td className={r.fields[f] ? "" : "muted"}>{valueText(r.fields[f])}</td>
              <td className="muted small">{from(r.sources[f])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="template-output-head">
        <h3>{label(listField)}</h3>
        <span className="muted small">{r.items_from === null ? t("none") : t("read from {{part}}", { part: from(r.items_from) })}</span>
      </div>
      {r.items.length ? (
        <table className="table compact quote-items" aria-label={label(listField)}>
          <thead><tr>{columns.map((c) => <th key={c} className={c === "quantity" ? "num" : undefined}>{COLUMN[c] ? t(COLUMN[c]) : label(c)}</th>)}</tr></thead>
          <tbody>
            {rows.map((i, n) => (
              <tr key={n}>
                {columns.map((c) => (
                  <td key={c} className={c === "quantity" ? "num tnum" : undefined}>
                    {c === "quantity" ? (i[c] === null || i[c] === undefined ? "—" : numText(i[c], 4)) : valueText(i[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <p className="small muted">
        {t("Parts:")} {r.parts.map((p) => `${partKind(p)} (${p.name || "—"})`).join(" · ") || t("none")}
      </p>
    </>
  );
}
