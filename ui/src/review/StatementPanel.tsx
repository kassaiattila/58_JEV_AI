// 139 (DECISIONS 139): one valid statement per account and day, on the review page of a statement. Another statement
// of the same account and days either replaced this one, was replaced by it (by the rule of ranks: read by code and
// checked > extracted and checked > unchecked, or by a person's choice), or neither, and a person chooses
// (jav/statement_months.py). The choice belongs to the pair, closes its to-dos on both documents and can be changed
// until the run is approved; "By the rule" undoes it.
import { useRef, useState } from "react";
import { api, ApiError, type ItemResult, type StatementKeep, type StatementRelation } from "../api";
import { t, useLocale } from "../i18n";
import { tmap } from "../labels";

const RANK: Record<string, string> = tmap({
  code_checked: "read by code, balances check out",
  extracted_checked: "extracted, balances check out",
  unchecked: "balances not checked",
});

const TITLE: Record<StatementRelation["relation"], string> = tmap({
  replaced_by: "This statement is replaced: another statement of the same days is the valid one",
  replaces: "This statement replaces another statement of the same days",
  conflict: "Another statement books the same days of this account: which one is valid?",
});

function period(p: [string | null, string | null]): string {
  return `${p[0] ?? "?"} – ${p[1] ?? "?"}`;
}

function otherLink(r: StatementRelation): string | null {
  return r.other_workpackage_id && r.other_item_id
    ? `#/workpackages/${encodeURIComponent(r.other_workpackage_id)}/review/${encodeURIComponent(r.other_item_id)}` : null;
}

function how(r: StatementRelation): string {
  if (r.relation === "conflict") return t("Until a person chooses, both count and their lines may be counted twice.");
  const by = r.how === "person"
    ? t("Chosen by {{name}}.", { name: r.decided_by ?? "?" })
    : t("By the rule: the better source covering the whole period replaces the other.");
  const lines = r.carried === null ? "" : r.left_over
    ? ` ${t("{{carried}} lines found their same line; the decisions on {{left}} lines have to be made again in the reconciliation package.", { carried: r.carried, left: r.left_over })}`
    : ` ${t("Every line found its same line; the decisions made on them carry over.")}`;
  return by + lines;
}

interface Props {
  result: ItemResult;
  readOnly: boolean;
  onDecided: () => void;
}

export function StatementPanel({ result, readOnly, onDecided }: Props) {
  useLocale();
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false); // one request at a time
  const relations = result.statements ?? [];
  if (!relations.length) return null;

  async function choose(r: StatementRelation, keep: StatementKeep): Promise<void> {
    if (busy.current) return;
    busy.current = true;
    setPending(r.other_doc_id);
    setError(null);
    try {
      await api.chooseStatement(result.run_id, result.item_id, r.other_doc_id, keep, r.decision_state);
    } catch (e) {
      setError(t("The choice could not be saved: {{reason}}", { reason: e instanceof ApiError ? e.message : String(e) }));
    } finally {
      busy.current = false;
      setPending(null);
      onDecided();
    }
  }

  return (
    <section className="duplicates" aria-label={t("Statements of the same days")}>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {relations.map((r) => {
        const link = otherLink(r);
        const valid = r.relation === "replaced_by" ? "other" : r.relation === "replaces" ? "this" : null;
        return (
          <div key={r.other_doc_id} className={`duplicate-pair${r.relation === "conflict" ? "" : " decided"}`}>
            <p className="duplicate-title"><strong>{TITLE[r.relation]}</strong></p>
            <table className="duplicate-table">
              <thead>
                <tr><th /><th>{t("This statement")}</th><th>{t("The other statement")}</th></tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">{t("File")}</th><td>{t("this one")}</td>
                  <td>{link ? <a href={link} target="_blank" rel="noreferrer">{r.other_file ?? r.other_doc_id.slice(0, 12)}</a>
                    : (r.other_file ?? r.other_doc_id.slice(0, 12))}</td>
                </tr>
                <tr><th scope="row">{t("Period")}</th><td>{period(r.period)}</td><td>{period(r.other_period)}</td></tr>
                <tr><th scope="row">{t("Source")}</th><td>{RANK[r.rank] ?? r.rank}</td><td>{RANK[r.other_rank] ?? r.other_rank}</td></tr>
                <tr><th scope="row">{t("Lines")}</th><td>{r.lines}</td><td>{r.other_lines}</td></tr>
              </tbody>
            </table>
            <p className="small">{how(r)}</p>
            {readOnly ? null : (
              <div className="duplicate-actions" role="group" aria-label={t("Which statement is valid")}>
                <button type="button" className={valid === "this" ? "primary small-btn" : "secondary small-btn"} aria-pressed={valid === "this"}
                  disabled={pending !== null} onClick={() => void choose(r, "this")}>{t("This one is valid")}</button>
                <button type="button" className={valid === "other" ? "primary small-btn" : "secondary small-btn"} aria-pressed={valid === "other"}
                  disabled={pending !== null} onClick={() => void choose(r, "other")}>{t("The other one is valid")}</button>
                {r.how === "person" ? (
                  <button type="button" className="quiet small-btn" disabled={pending !== null} onClick={() => void choose(r, "rule")}>
                    {t("By the rule")}
                  </button>
                ) : null}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
