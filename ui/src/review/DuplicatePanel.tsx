// 126 (backlog F-duplicate): a suspected duplicate invoice on the review page. The code found an earlier document with
// the same invoice number and supplier (jav/duplicates.py); the two documents' compared values stand side by side, the
// differing ones highlighted, and a person decides: a copy, a modified version, or not the same invoice. The decision
// belongs to the pair and closes its to-dos on both documents; it can be changed until the run is approved.
import { useRef, useState } from "react";
import { api, ApiError, type DuplicateDecision, type DuplicateKind, type DuplicatePair, type ItemResult } from "../api";
import { getLocale, t, useLocale } from "../i18n";
import { fieldLabel, tmap } from "../labels";

const TITLE: Record<DuplicateKind, string> = tmap({
  copy: "Possible copy: an earlier document has the same invoice number, supplier, date, amount and currency",
  variant: "Possible modified version: an earlier document has the same invoice number and supplier, but some values differ",
  undecidable: "Possible duplicate: an earlier document has the same invoice number and supplier, but a compared value is missing",
});

const DECISION: Record<DuplicateDecision, string> = tmap({
  copy: "Copy",
  variant: "Modified version",
  different: "Not the same invoice",
});

const DECIDED: Record<DuplicateDecision, string> = tmap({
  copy: "Decided: a copy; it is marked and counted once",
  variant: "Decided: a modified version of the earlier document",
  different: "Decided: not the same invoice; both count",
});

function shown(field: string, v: unknown, kinds: Record<string, string> | undefined): string {
  if (v === null || v === undefined || v === "") return "–";
  const text = String(v);
  return kinds?.[field] === "money" && getLocale() === "hu-HU" ? text.replace(".", ",") : text;
}

function otherLink(p: DuplicatePair): string | null {
  return p.other_workpackage_id && p.other_item_id
    ? `#/workpackages/${encodeURIComponent(p.other_workpackage_id)}/review/${encodeURIComponent(p.other_item_id)}` : null;
}

interface Props {
  result: ItemResult;
  readOnly: boolean;
  onDecided: () => void;
}

export function DuplicatePanel({ result, readOnly, onDecided }: Props) {
  useLocale();
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false); // one request at a time (as the to-do's "resolved" button)
  const pairs = result.duplicates ?? [];
  if (!pairs.length) return null;

  async function decide(p: DuplicatePair, decision: DuplicateDecision): Promise<void> {
    if (busy.current) return;
    busy.current = true;
    setPending(p.other_doc_id);
    setError(null);
    try {
      await api.decideDuplicate(result.run_id, result.item_id, p.other_doc_id, decision);
    } catch (e) {
      setError(t("The decision could not be saved: {{reason}}", { reason: e instanceof ApiError ? e.message : String(e) }));
    } finally {
      busy.current = false;
      setPending(null);
      onDecided();
    }
  }

  return (
    <section className="duplicates" aria-label={t("Possible duplicate invoices")}>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {pairs.map((p) => {
        const link = otherLink(p);
        return (
          <div key={p.other_doc_id} className={`duplicate-pair${p.decision ? " decided" : ""}`}>
            <p className="duplicate-title"><strong>{TITLE[p.kind]}</strong></p>
            <p className="small">
              {t("Earlier document:")}{" "}
              {link ? <a href={link} target="_blank" rel="noreferrer">{p.other_file ?? p.other_doc_id.slice(0, 12)}</a>
                : <span>{p.other_file ?? p.other_doc_id.slice(0, 12)}</span>}
            </p>
            <table className="duplicate-table">
              <thead>
                <tr><th>{t("Field")}</th><th>{t("This document")}</th><th>{t("Earlier document")}</th></tr>
              </thead>
              <tbody>
                {p.fields.map((r) => (
                  <tr key={r.field} className={r.differs ? "differs" : r.missing ? "missing" : undefined}>
                    <th scope="row">{fieldLabel(r.field)}</th>
                    <td>{shown(r.field, r.value, result.kinds)}</td>
                    <td>{shown(r.field, r.other_value, result.kinds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {p.decision ? (
              <p className="small ok">{DECIDED[p.decision]}{p.decided_by ? ` (${p.decided_by})` : ""}</p>
            ) : null}
            {readOnly ? null : (
              <div className="duplicate-actions" role="group" aria-label={t("Decision on the pair")}>
                {(["copy", "variant", "different"] as DuplicateDecision[]).map((d) => (
                  <button key={d} type="button" className={p.decision === d ? "primary small-btn" : "secondary small-btn"}
                    aria-pressed={p.decision === d} disabled={pending !== null} onClick={() => void decide(p, d)}>
                    {DECISION[d]}
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
